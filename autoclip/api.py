"""Loopback API for managed media, durable jobs and safe result access."""

from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .engine import ClipError, Settings, run_tool, worker_lock
from .service import Service, contained_path
from .store import ProjectAssetConflict


AspectRatio = Literal["9:16", "16:9", "1:1", "4:5"]
Resolution = Literal[480, 720, 1080]
Compression = Literal["higher_quality", "balanced", "smaller_file"]


class FocusPointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class RegionRequest(FocusPointRequest):
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Region must stay inside the source frame.")
        return self


class FramingRequest(BaseModel):
    """CPU visual analysis with explicit manual overrides and safe defaults."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    mode: Literal["smart_crop", "focus_crop", "hybrid_focus", "streamer_gameplay", "full_gameplay", "auto"] = "auto"
    focus_point: FocusPointRequest | None = None
    focus_region: RegionRequest | None = None
    webcam_region: RegionRequest | None = None
    background: Literal["blur", "pad"] = "blur"
    tracking_intensity: float = Field(default=0.5, ge=0, le=1)
    subtitle_position: Literal["auto", "top", "center", "bottom"] = "auto"
    safe_margin_horizontal: float = Field(default=0.08, ge=0, le=0.4)
    safe_margin_top: float = Field(default=0.08, ge=0, le=0.4)
    safe_margin_bottom: float = Field(default=0.15, ge=0, le=0.4)
    emphasis_zoom: bool = False
    foreground_zoom: float = Field(default=1, ge=1, le=2)
    auto_focus: bool = True
    smooth_tracking: bool = True
    lock_position: bool = False

    @model_validator(mode="after")
    def validate_settings(self):
        from .reframing import FramingSettings
        try:
            FramingSettings.from_dict(self.model_dump())
        except ClipError as exc:
            raise ValueError(str(exc)) from exc
        return self


class JobOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    max_clips: int = Field(default=3, ge=1, le=10, strict=True)
    clip_length: float = Field(default=30, ge=15, le=60)
    layout_mode: Literal["pad", "crop"] = "pad"
    aspect_ratio: AspectRatio = "9:16"
    framing: FramingRequest | None = None
    resolution: Resolution = 720
    compression: Compression = "balanced"
    fps: Literal[30, 60] = 30
    captions: bool = False
    speech_ranking: bool = False
    language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2,3})$")
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_interval(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("Manual trimming requires start and end.")
        if self.start is not None and not 15 <= self.end - self.start <= 60:
            raise ValueError("Manual intervals must span 15–60 seconds.")
        return self

    def engine_options(self) -> dict:
        options = self.model_dump()
        options["count"] = options.pop("max_clips")
        options["layout"] = options.pop("layout_mode")
        if options["framing"] is None:
            options.pop("framing")
        return options


class JobRequest(JobOptions):
    media_id: str = Field(pattern=r"^[0-9a-f]{32}$")

    def engine_options(self) -> dict:
        options = super().engine_options()
        options.pop("media_id")
        return options


class LocalImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)


class DeleteAssetsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirm: bool


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_state: Literal["proposed", "approved", "rejected"]


class CompositionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    aspect_ratio: AspectRatio
    resolution: Resolution
    framing: FramingRequest


class FrameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    time: float = Field(ge=0)
    composition: CompositionPreviewRequest | None = None


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    layout_mode: Literal["pad", "crop"] | None = None
    aspect_ratio: AspectRatio | None = None
    resolution: Resolution | None = None
    compression: Compression | None = None
    framing: FramingRequest | None = None

    @model_validator(mode="after")
    def validate_interval(self):
        JobOptions(start=self.start, end=self.end)
        return self


def require(record, label: str):
    if record is None:
        raise HTTPException(404, f"{label} was not found.")
    return record


def public_media(record: dict) -> dict:
    return {"id": record["id"], "filename": record["filename"], "sha256": record["sha256"],
            "created_at": record["created_at"], **json.loads(record["metadata_json"]),
            "archived_at": record["archived_at"], "asset_status": record["asset_status"]}


def public_job(record: dict) -> dict:
    result = {key: record[key] for key in (
        "id", "media_id", "source_candidate_id", "state", "phase", "progress_pct",
        "error_code", "error_message", "created_at", "started_at", "finished_at",
    )}
    result["cancel_requested"] = bool(record["cancel_requested"])
    result["options"] = json.loads(record["request_json"])
    result["options"].setdefault("aspect_ratio", "9:16")
    if result["options"].get("operation") != "frame_preview":
        result["options"].setdefault("resolution", 720)
        result["options"].setdefault("compression", "balanced")
    manifest = json.loads(record["manifest_json"]) if record["manifest_json"] else {}
    result["diagnostic"] = manifest.get("diagnostic")
    result["caption_status"] = manifest.get("caption_status")
    result["language"] = manifest.get("language")
    result["transcript_cache_hit"] = manifest.get("transcript_cache_hit")
    result["transcript_reuse_kind"] = manifest.get("transcript_reuse_kind")
    result["elapsed_seconds"] = manifest.get("elapsed_seconds")
    result["kind"] = "frame_preview" if result["options"].get("operation") == "frame_preview" else "render"
    result["frame_url"] = (f"/jobs/{record['id']}/frame"
                           if record["state"] == "completed" and manifest.get("frame_file") == "frame.jpg" else None)
    if result["kind"] == "frame_preview":
        result["frame_framing_mode"] = manifest.get("selected_mode")
    return result


def public_candidate(record: dict) -> dict:
    result = {key: record[key] for key in ("id", "job_id", "source_candidate_id", "start", "end", "score", "review_state")}
    result["evidence"] = json.loads(record["evidence_json"])
    if "clip_id" in record:
        result.update(clip_id=record["clip_id"], preview_url=f"/clips/{record['clip_id']}/preview",
                      download_url=f"/clips/{record['clip_id']}/download",
                      has_subtitles=bool(record.get("has_subtitles", False)))
    return result


def create_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    settings = settings or Settings.from_environment()
    settings = replace(settings, data_dir=settings.data_dir.resolve())
    recordings = Path(os.environ.get("AUTOCLIP_RECORDINGS_DIR", str(settings.data_dir / "recordings")))
    database = Path(os.environ.get("AUTOCLIP_DB_PATH", str(settings.data_dir / "autoclip.sqlite3")))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with worker_lock(settings.data_dir, ".server.lock"):
            service = Service(settings, database, recordings)
            app.state.service = service
            if start_worker:
                service.start()
            try:
                yield
            finally:
                await run_in_threadpool(service.stop)

    app = FastAPI(title="Clipper0 local API", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    origins = ["http://127.0.0.1:3000", "http://localhost:3000",
               "http://127.0.0.1:8000", "http://localhost:8000"]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["Content-Type", "Range"], expose_headers=["Content-Disposition"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def validate_origin(request: Request, call_next):
        if request.headers.get("origin") not in [None, *origins]:
            return JSONResponse({"detail": "This origin is not allowed to access the local API."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ClipError)
    async def clip_error(request: Request, exc: ClipError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ProjectAssetConflict)
    async def asset_conflict(request: Request, exc: ProjectAssetConflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(OSError)
    @app.exception_handler(sqlite3.Error)
    async def storage_error(request: Request, exc: Exception):
        return JSONResponse({"detail": "Local storage is unavailable. Check free space and file permissions."}, status_code=503)

    def service() -> Service:
        return app.state.service

    def project_asset_status(media_id: str) -> str:
        return require(service().store.media(media_id), "Media")["asset_status"]

    def require_project_assets(media_id: str) -> None:
        status = project_asset_status(media_id)
        if status == "deleted":
            raise HTTPException(410, "Project files have been deleted.")
        if status != "available":
            raise ProjectAssetConflict("Project files are unavailable while cleanup is in progress or incomplete.")

    def job_response(job: dict) -> dict:
        result = public_job(job)
        if result["frame_url"] and project_asset_status(job["media_id"]) != "available":
            result["frame_url"] = None
        return result

    @app.get("/health")
    def health():
        try:
            tools = {name: run_tool([getattr(settings, name), "-version"], timeout=15).splitlines()[0]
                     for name in ("ffmpeg", "ffprobe")}
        except ClipError as exc:
            raise HTTPException(503, str(exc)) from exc
        worker = service()
        if start_worker and (worker.thread is None or not worker.thread.is_alive() or worker.worker_error):
            raise HTTPException(503, "The background worker is unavailable. Check local storage and server logs.")
        return {"status": "ok", "version": __version__, "tools": tools, "worker_enabled": start_worker}

    @app.post("/media/import", status_code=201)
    async def import_upload(request: Request, filename: str = Query(min_length=1, max_length=255)):
        worker = service()
        length = request.headers.get("content-length")
        if length is not None:
            try:
                size = int(length)
            except ValueError as exc:
                raise HTTPException(400, "Invalid Content-Length.") from exc
            if size < 0 or size > settings.max_bytes:
                raise HTTPException(413, "Upload exceeds the configured size limit.")
        media_id, staging = worker.begin_import(filename)
        try:
            digest = hashlib.sha256()
            size = 0
            with staging.open("xb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > settings.max_bytes:
                        raise HTTPException(413, "Upload exceeds the configured size limit.")
                    digest.update(chunk)
                    await run_in_threadpool(output.write, chunk)
            record = await run_in_threadpool(worker.finish_import, media_id, filename, staging, digest.hexdigest())
            return public_media(record)
        finally:
            staging.unlink(missing_ok=True)

    @app.post("/media/import-local", status_code=201)
    def import_local(body: LocalImport):
        return public_media(service().import_local(body.filename))

    @app.get("/media")
    def list_media(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
                   archived: bool = False):
        return [public_media(record) for record in service().store.list_media(limit, offset, archived=archived)]

    @app.get("/media/{media_id}")
    def get_media(media_id: str):
        return public_media(require(service().store.media(media_id), "Media"))

    @app.post("/media/{media_id}/archive")
    def archive_media(media_id: str):
        return public_media(require(service().store.set_media_archived(media_id, True), "Media"))

    @app.post("/media/{media_id}/restore")
    def restore_media(media_id: str):
        return public_media(require(service().store.set_media_archived(media_id, False), "Media"))

    @app.post("/media/{media_id}/delete-assets")
    def delete_media_assets(media_id: str, body: DeleteAssetsRequest):
        if not body.confirm:
            raise HTTPException(422, "Confirm permanent deletion of project files.")
        result = require(service().delete_project_assets(media_id), "Media")
        return {"media": public_media(result["media"]), "failures": result["failures"]}

    @app.post("/media/{media_id}/frames", status_code=202)
    def request_frame(media_id: str, body: FrameRequest):
        media = require(service().store.media(media_id), "Media")
        duration = json.loads(media["metadata_json"])["duration"]
        if body.time >= duration:
            raise HTTPException(422, "Preview timestamp must be inside the recording.")
        options = {"operation": "frame_preview", "time": body.time}
        if body.composition is not None:
            composition = body.composition
            if not (composition.start <= body.time < composition.end <= duration
                    and 15 <= composition.end - composition.start <= 60):
                raise HTTPException(422, "Composition preview requires a 15–60 second clip and a timestamp inside it.")
            options["composition"] = composition.model_dump()
        job = service().store.create_job(media_id, options)
        service().wake.set()
        return public_job(job)

    def enqueue(media_id: str, options: dict, source_candidate_id: str | None = None):
        media = require(service().store.media(media_id), "Media")
        duration = json.loads(media["metadata_json"])["duration"]
        if options.get("end") is not None and options["end"] > duration:
            raise HTTPException(422, "The clip interval extends beyond the recording.")
        job = service().store.create_job(media_id, options, source_candidate_id)
        service().wake.set()
        return public_job(job)

    @app.post("/jobs", status_code=202)
    def create_job(body: JobRequest):
        return enqueue(body.media_id, body.engine_options())

    @app.get("/jobs")
    def list_jobs(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
                  archived: bool = False):
        return [job_response(record) for record in service().store.list_jobs(limit, offset, archived=archived)]

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return job_response(require(service().store.job(job_id), "Job"))

    @app.get("/jobs/{job_id}/frame")
    def frame_asset(job_id: str):
        job = require(service().store.job(job_id), "Job")
        require_project_assets(job["media_id"])
        manifest = json.loads(job["manifest_json"]) if job["manifest_json"] else {}
        if job["state"] != "completed" or manifest.get("frame_file") != "frame.jpg":
            raise HTTPException(404, "Preview frame is not ready.")
        path = contained_path(settings.data_dir, f"clips/{job['id']}/frame.jpg")
        if not path.is_file():
            raise HTTPException(404, "Preview frame is missing.")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return job_response(require(service().store.cancel(job_id), "Job"))

    @app.get("/jobs/{job_id}/candidates")
    def candidates(job_id: str):
        job = require(service().store.job(job_id), "Job")
        if project_asset_status(job["media_id"]) != "available":
            return []
        manifest = json.loads(job["manifest_json"]) if job["manifest_json"] else {}
        clips = {clip["file"]: clip for clip in manifest.get("clips", [])}
        results = []
        for record in service().store.candidates(job_id):
            result = public_candidate(record)
            clip = service().store.clip(record["clip_id"])
            metadata = clips.get(Path(clip["path"]).name, {})
            result.update(framing=metadata.get("framing"), effective_framing=metadata.get("effective_framing"),
                          visual_analysis=metadata.get("visual_analysis"))
            results.append(result)
        return results

    @app.patch("/candidates/{candidate_id}")
    def review(candidate_id: str, body: ReviewRequest):
        return public_candidate(require(service().store.review(candidate_id, body.review_state), "Candidate"))

    @app.post("/candidates/{candidate_id}/render", status_code=202)
    def render(candidate_id: str, body: RenderRequest):
        candidate = require(service().store.candidate(candidate_id), "Candidate")
        previous_job = require(service().store.job(candidate["job_id"]), "Job")
        options = json.loads(previous_job["request_json"])
        options.update(start=body.start, end=body.end)
        if body.layout_mode is not None:
            options["layout"] = body.layout_mode
        if body.aspect_ratio is not None:
            options["aspect_ratio"] = body.aspect_ratio
        if body.resolution is not None:
            options["resolution"] = body.resolution
        if body.compression is not None:
            options["compression"] = body.compression
        if "framing" in body.model_fields_set:
            if body.framing is None:
                options.pop("framing", None)
            else:
                options["framing"] = body.framing.model_dump()
        return enqueue(previous_job["media_id"], options, candidate_id)

    def clip_file(clip_id: str, field: str) -> Path:
        clip = require(service().store.clip(clip_id), "Clip")
        candidate = require(service().store.candidate(clip["candidate_id"]), "Candidate")
        job = require(service().store.job(candidate["job_id"]), "Job")
        require_project_assets(job["media_id"])
        relative = require(clip[field], "Clip asset")
        path = contained_path(settings.data_dir, relative)
        if not path.is_file():
            raise HTTPException(404, "Clip asset is missing from local storage.")
        return path

    @app.get("/clips/{clip_id}/preview")
    def preview(clip_id: str):
        return FileResponse(clip_file(clip_id, "path"), media_type="video/mp4")

    @app.get("/clips/{clip_id}/download")
    def download(clip_id: str):
        return FileResponse(clip_file(clip_id, "path"), media_type="video/mp4", filename=f"clip-{clip_id[:8]}.mp4")

    @app.get("/clips/{clip_id}/subtitles")
    def subtitles(clip_id: str):
        return FileResponse(clip_file(clip_id, "srt_path"), media_type="application/x-subrip", filename=f"clip-{clip_id[:8]}.srt")

    return app
