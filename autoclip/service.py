"""Managed imports and one durable queue worker around the existing engine."""

from dataclasses import asdict
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import threading
import uuid

from .engine import (ClipError, JobCancelled, Settings, inspect_media, process,
                     processing_control, run_tool, validate_framing_source, worker_lock, write_manifest)
from .store import Store


def safe_filename(filename: str) -> str:
    if (not filename or len(filename) > 255 or any(c in filename for c in "/\\:\x00")
            or any(ord(c) < 32 for c in filename) or filename in {".", ".."}
            or Path(filename).suffix.lower() not in {".mp4", ".mkv"}):
        raise ClipError("Supply an MP4/MKV filename without a directory or control characters.")
    return filename


def contained_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ClipError("The requested file is outside managed storage.")
    return path


def managed_asset_stat(root: Path, path: Path):
    """Inspect a managed path without accepting symbolic links or reparse points."""
    relative = path.relative_to(root)
    current = root
    for part in ("", *relative.parts):
        current = current / part
        info = current.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ClipError("Path uses a symbolic link or reparse point.")
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise ClipError("An asset parent is not a directory.")
    if path.resolve(strict=True) != path:
        raise ClipError("Path does not resolve to its expected managed location.")
    return info


class Service:
    def __init__(self, settings: Settings, database: Path, recordings: Path):
        self.settings = settings
        self.store = Store(database)
        self.recordings = recordings.resolve()
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread: threading.Thread | None = None
        self.worker_error: str | None = None
        self.imports = contained_path(settings.data_dir, "imports")
        self.imports.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        self.store.recover()
        self.thread = threading.Thread(target=self.work, name="autoclip-worker", daemon=False)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join()

    def begin_import(self, filename: str) -> tuple[str, Path]:
        safe_filename(filename)
        media_id = uuid.uuid4().hex
        staging = contained_path(self.settings.data_dir, f"imports/{media_id}.partial{Path(filename).suffix.lower()}")
        return media_id, staging

    def finish_import(self, media_id: str, filename: str, staging: Path, digest: str) -> dict:
        media = inspect_media(staging, self.settings)
        metadata = asdict(media)
        metadata.pop("path")
        final = self.imports / f"{media_id}{staging.suffix}"
        staging.replace(final)
        try:
            return self.store.add_media(media_id, filename, final.name, digest, metadata)
        except BaseException:
            final.unlink(missing_ok=True)
            raise

    def import_local(self, filename: str) -> dict:
        safe_filename(filename)
        source = contained_path(self.recordings, filename)
        if not source.is_file():
            raise ClipError("Recording was not found in the configured recordings directory.")
        before = source.stat()
        if not 0 < before.st_size <= self.settings.max_bytes:
            raise ClipError("Recording is empty or exceeds the configured input size limit.")
        if shutil.disk_usage(self.imports).free < before.st_size + 512 * 1024**2:
            raise ClipError("Insufficient space to copy this recording into managed storage.")
        media_id, staging = self.begin_import(filename)
        try:
            digest = hashlib.sha256()
            size = 0
            with source.open("rb") as incoming, staging.open("xb") as outgoing:
                while chunk := incoming.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.settings.max_bytes:
                        raise ClipError("Recording exceeded the configured input size limit while copying.")
                    digest.update(chunk)
                    outgoing.write(chunk)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ClipError("The recording changed during import. Wait for OBS to finish and retry.")
            return self.finish_import(media_id, filename, staging, digest.hexdigest())
        finally:
            staging.unlink(missing_ok=True)

    def delete_project_assets(self, media_id: str) -> dict | None:
        """Delete files in the project's managed namespaces and keep its history."""
        media = self.store.begin_asset_deletion(media_id)
        if media is None:
            return None
        failures: list[dict[str, str]] = []
        if media["asset_status"] == "deleted":
            return {"media": media, "failures": failures}

        root = self.settings.data_dir.absolute()

        def remove_file(path: Path) -> None:
            if path.is_relative_to(self.recordings):
                raise ClipError("Path is inside the protected recordings directory.")
            info = managed_asset_stat(root, path)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ClipError("Asset is not a uniquely owned regular file.")
            path.unlink()

        def report(asset: str, error: Exception) -> None:
            if isinstance(error, ClipError):
                reason = str(error)
            else:
                reason = "Could not access or remove the asset. Check permissions and close any open players."
            failures.append({"asset": asset, "reason": reason})

        finished_scan = False
        try:
            for job_id in self.store.project_job_ids(media_id):
                if not re.fullmatch(r"[0-9a-f]{32}", job_id):
                    report("Job output", ClipError("Invalid managed job identifier."))
                    continue
                directory = root / "clips" / job_id
                try:
                    if directory.is_relative_to(self.recordings):
                        raise ClipError("Path is inside the protected recordings directory.")
                    if not stat.S_ISDIR(managed_asset_stat(root, directory).st_mode):
                        raise ClipError("Expected a managed job directory.")
                    for path in sorted(directory.iterdir()):
                        asset = path.relative_to(root).as_posix()
                        if path.name not in {"manifest.json", "transcript.json", "frame.jpg", "frame.partial.jpg"} and not re.fullmatch(
                                r"clip-[0-9]{2}\.(?:mp4|ass|srt)|\.clip-[0-9]{2}-[0-9a-f]{32}\.partial\.mp4", path.name):
                            report(asset, ClipError("Unrecognized file in the job directory."))
                            continue
                        try:
                            remove_file(path)
                        except FileNotFoundError:
                            pass
                        except (ClipError, OSError) as exc:
                            report(asset, exc)
                except FileNotFoundError:
                    pass
                except (ClipError, OSError) as exc:
                    report(f"clips/{job_id}", exc)

            stored_name = media["stored_name"]
            if (not re.fullmatch(r"[0-9a-f]{32}", media_id)
                    or stored_name not in {f"{media_id}.mp4", f"{media_id}.mkv"}):
                report("Managed import", ClipError("The import name does not match this project's identifier."))
            else:
                try:
                    remove_file(root / "imports" / stored_name)
                except FileNotFoundError:
                    pass
                except (ClipError, OSError) as exc:
                    report(f"imports/{stored_name}", exc)
            finished_scan = True
        finally:
            updated = self.store.finish_asset_deletion(media_id, complete=finished_scan and not failures)
        return {"media": updated, "failures": failures}

    def cancelled(self, job_id: str) -> bool:
        job = self.store.job(job_id)
        return self.stop_event.is_set() or job is None or bool(job["cancel_requested"])

    def finalize(self, job_id: str, **outcome) -> None:
        while True:
            try:
                self.store.finish(job_id, **outcome)
                self.worker_error = None
                return
            except sqlite3.Error as exc:
                self.worker_error = str(exc)
                if self.stop_event.wait(0.5):
                    return

    def revision_transcript(self, job: dict, media: dict, options: dict) -> dict | None:
        """Load only a managed parent transcript for a speech-enabled framing revision."""
        candidate_id = job.get("source_candidate_id")
        if not candidate_id or not (options.get("captions") or options.get("speech_ranking")):
            return None
        candidate = self.store.candidate(candidate_id)
        if candidate is None:
            raise ClipError("The revision's source candidate is missing.")
        parent = self.store.job(candidate["job_id"])
        if parent is None or parent["media_id"] != media["id"] or job["media_id"] != media["id"]:
            raise ClipError("The revision's parent job does not match its imported recording.")
        parent_options = json.loads(parent["request_json"])
        if options.get("framing") is None and parent_options.get("framing") is None:
            return None
        metadata = json.loads(media["metadata_json"])
        if not metadata.get("audio_present"):
            return None  # No audio means the ordinary speech path performs no inference.
        if parent["state"] != "completed" or not parent.get("manifest_json"):
            raise ClipError("The revision's completed parent transcript is unavailable.")
        manifest = json.loads(parent["manifest_json"])
        if manifest.get("transcript_file") != "transcript.json":
            raise ClipError("The parent job has no managed saved transcript for this framing revision.")
        path = contained_path(self.settings.data_dir, f"clips/{parent['id']}/transcript.json")
        try:
            if not path.is_file() or not 0 < path.stat().st_size <= 32 * 1024**2:
                raise ClipError("The parent transcript is missing, empty or exceeds the reuse size limit.")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise ClipError("The parent transcript could not be read; restore it before retrying this revision.") from exc
        from .speech import validate_saved_transcript
        return validate_saved_transcript(payload, media["sha256"], metadata["duration"],
                                         language=options.get("language", "auto"))

    def frame_preview(self, job: dict, media: dict, source: Path, options: dict) -> Path:
        """A bounded still extraction on the same single queue as all rendering."""
        time = options.get("time")
        duration = json.loads(media["metadata_json"])["duration"]
        if isinstance(time, bool) or not isinstance(time, (int, float)) or not math.isfinite(time) or not 0 <= time < duration:
            raise ClipError("Preview timestamp must be inside the recording.")
        directory = contained_path(self.settings.data_dir, f"clips/{job['id']}")
        with processing_control(lambda: self.cancelled(job["id"]),
                                lambda manifest: self.store.update_progress(job["id"], manifest)), \
                worker_lock(self.settings.data_dir):
            directory.mkdir(parents=True)
            manifest = {"state": "running", "phase": "preview", "progress_pct": 10, "clips": []}
            write_manifest(directory, manifest)
            partial = directory / "frame.partial.jpg"
            try:
                filters = ["-map", "0:V:0", "-filter_threads", "1", "-vf", "scale='min(960,iw)':-2"]
                composition = options.get("composition")
                if composition is not None:
                    from .composition import build_filtergraph
                    from .reframing import FramingSettings
                    from .vision import plan_candidate_framing

                    start, end = composition["start"], composition["end"]
                    if not (start <= time < end <= duration and 15 <= end - start <= 60):
                        raise ClipError("Composition preview timestamp must be inside a valid clip interval.")
                    video = inspect_media(source, self.settings)
                    validate_framing_source(video)
                    framing = FramingSettings.from_dict(composition["framing"])
                    plan, effective, _ = plan_candidate_framing(
                        video, start, end, framing, self.settings,
                        aspect_ratio=composition["aspect_ratio"], source_sha256=media["sha256"])
                    graph = build_filtergraph(plan, effective, aspect_ratio=composition["aspect_ratio"],
                                              resolution=composition["resolution"])
                    # Input seeking starts at the requested still. Restore clip-relative
                    # timestamps to evaluate the same tracking and emphasis expressions.
                    timeline = f"[0:V:0]setpts=PTS+{time-start:.6f}/TB[preview];"
                    filters = ["-map", graph.output_label, "-filter_complex_threads", "1", "-filter_complex",
                               timeline + graph.filtergraph.replace("[0:V:0]", "[preview]")]
                    manifest["selected_mode"] = plan.selected_mode
                run_tool([self.settings.ffmpeg, "-nostdin", "-v", "error", "-n", "-threads", "1",
                          "-protocol_whitelist", "file,pipe", "-ss", f"{time:.6f}", "-i", str(source),
                          *filters, "-frames:v", "1", "-an", "-sn", "-dn", "-q:v", "3",
                          "-threads", "1", str(partial)], timeout=60)
                if not partial.is_file() or partial.stat().st_size == 0:
                    raise ClipError("No frame is available at this timestamp. Try an earlier time.")
                partial.replace(directory / "frame.jpg")
                manifest.update(state="completed", phase="done", progress_pct=100,
                                frame_file="frame.jpg", frame_time=time)
                write_manifest(directory, manifest)
            finally:
                partial.unlink(missing_ok=True)
        return directory / "manifest.json"

    def execute(self, job: dict) -> None:
        job_id = job["id"]
        try:
            media = self.store.media(job["media_id"])
            if media is None:
                raise ClipError("The job's imported media record is missing.")
            source = contained_path(self.settings.data_dir, f"imports/{media['stored_name']}")
            options = json.loads(job["request_json"])
            if options.get("operation") == "frame_preview":
                manifest_path = self.frame_preview(job, media, source, options)
                self.finalize(job_id, manifest=json.loads(manifest_path.read_text(encoding="utf-8")))
                return
            if options.get("framing") is not None:
                from .reframing import FramingSettings
                options["framing"] = FramingSettings.from_dict(options["framing"])
                options["source_sha256"] = media["sha256"]
            transcript = self.revision_transcript(job, media, options)
            if transcript is not None:
                options["saved_transcript"] = transcript
                options["source_sha256"] = media["sha256"]
            manifest_path = process(
                source, self.settings, **options, output_id=job_id,
                cancelled=lambda: self.cancelled(job_id),
                progress_callback=lambda manifest: self.store.update_progress(job_id, manifest),
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for clip in manifest["clips"]:
                path = contained_path(self.settings.data_dir, f"clips/{job_id}/{clip['file']}")
                if not path.is_file():
                    raise ClipError("A rendered clip is missing. Results were not published.")
            self.finalize(job_id, manifest=manifest)
        except JobCancelled:
            self.finalize(job_id, cancelled=True)
        except Exception as exc:
            logging.getLogger(__name__).exception("Job %s failed", job_id)
            self.finalize(job_id, error=str(exc))

    def work(self) -> None:
        while not self.stop_event.is_set():
            try:
                job = self.store.claim()
                self.worker_error = None
            except sqlite3.Error as exc:
                self.worker_error = str(exc)
                self.stop_event.wait(0.5)
                continue
            if job is None:
                self.wake.wait(0.25)
                self.wake.clear()
            else:
                self.execute(job)
