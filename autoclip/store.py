"""SQLite persistence with transactional job claiming and result publication."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectAssetConflict(RuntimeError):
    """A project asset operation conflicts with the current project state."""


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError("Database schema is newer than this application supports.")
            if version == 0:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE media (
                        id TEXT PRIMARY KEY, filename TEXT NOT NULL, stored_name TEXT NOT NULL UNIQUE,
                        sha256 TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
                        archived_at TEXT,
                        asset_status TEXT NOT NULL DEFAULT 'available'
                            CHECK(asset_status IN ('available', 'deleting', 'deleted', 'deletion_incomplete'))
                    );
                    CREATE TABLE jobs (
                        id TEXT PRIMARY KEY, media_id TEXT NOT NULL REFERENCES media(id),
                        request_json TEXT NOT NULL, source_candidate_id TEXT,
                        state TEXT NOT NULL CHECK(state IN ('queued','running','completed','failed','cancelled')),
                        phase TEXT NOT NULL, progress_pct INTEGER NOT NULL DEFAULT 0,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,
                        error_code TEXT, error_message TEXT, manifest_json TEXT,
                        created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
                    );
                    CREATE INDEX jobs_queue ON jobs(state, created_at);
                    CREATE TABLE candidates (
                        id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                        source_candidate_id TEXT REFERENCES candidates(id),
                        start REAL NOT NULL, end REAL NOT NULL, score REAL NOT NULL,
                        evidence_json TEXT NOT NULL,
                        review_state TEXT NOT NULL CHECK(review_state IN ('proposed','approved','rejected'))
                    );
                    CREATE INDEX candidates_job ON candidates(job_id);
                    CREATE TABLE clips (
                        id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL UNIQUE REFERENCES candidates(id),
                        path TEXT NOT NULL, subtitle_path TEXT, srt_path TEXT
                    );
                    PRAGMA user_version=2;
                    COMMIT;
                """)
            elif version == 1:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE media ADD COLUMN archived_at TEXT;
                    ALTER TABLE media ADD COLUMN asset_status TEXT NOT NULL DEFAULT 'available'
                        CHECK(asset_status IN ('available', 'deleting', 'deleted', 'deletion_incomplete'));
                    PRAGMA user_version=2;
                    COMMIT;
                """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_media(self, media_id: str, filename: str, stored_name: str, digest: str, metadata: dict) -> dict:
        with self.connection() as db:
            db.execute("""INSERT INTO media (id, filename, stored_name, sha256, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                       (media_id, filename, stored_name, digest, json.dumps(metadata), now()))
        return self.media(media_id)

    def media(self, media_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
        return dict(row) if row else None

    def set_media_archived(self, media_id: str, archived: bool) -> dict | None:
        with self.connection() as db:
            row = db.execute("""UPDATE media
                SET archived_at=CASE WHEN ? THEN COALESCE(archived_at, ?) ELSE NULL END
                WHERE id=? RETURNING *""", (archived, now(), media_id)).fetchone()
        return dict(row) if row else None

    def list_media(self, limit: int, offset: int, *, archived: bool = False) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                """SELECT * FROM media WHERE (archived_at IS NOT NULL)=?
                ORDER BY created_at DESC, id LIMIT ? OFFSET ?""", (archived, limit, offset))]

    def begin_asset_deletion(self, media_id: str) -> dict | None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            media = db.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
            if media is None:
                return None
            if media["asset_status"] == "deleted":
                return dict(media)
            if media["asset_status"] == "deleting":
                raise ProjectAssetConflict("Project asset deletion is already in progress.")
            active = db.execute("""SELECT 1 FROM jobs
                WHERE media_id=? AND state IN ('queued', 'running') LIMIT 1""", (media_id,)).fetchone()
            if active is not None:
                raise ProjectAssetConflict("Wait for queued and running jobs to stop before deleting project files.")
            updated = db.execute("""UPDATE media SET asset_status='deleting'
                WHERE id=? RETURNING *""", (media_id,)).fetchone()
        return dict(updated)

    def finish_asset_deletion(self, media_id: str, *, complete: bool) -> dict:
        status = "deleted" if complete else "deletion_incomplete"
        with self.connection() as db:
            row = db.execute("""UPDATE media SET asset_status=?
                WHERE id=? AND asset_status='deleting' RETURNING *""", (status, media_id)).fetchone()
            if row is None:
                raise ProjectAssetConflict("Project asset deletion is no longer in progress.")
        return dict(row)

    def create_job(self, media_id: str, options: dict, source_candidate_id: str | None = None) -> dict:
        job_id = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            media = db.execute("SELECT asset_status FROM media WHERE id=?", (media_id,)).fetchone()
            if media is not None and media["asset_status"] != "available":
                raise ProjectAssetConflict("Project assets are unavailable. Import the original recording to start a new job.")
            db.execute("""INSERT INTO jobs
                (id, media_id, request_json, source_candidate_id, state, phase, created_at)
                VALUES (?, ?, ?, ?, 'queued', 'queued', ?)""",
                       (job_id, media_id, json.dumps(options, sort_keys=True, allow_nan=False), source_candidate_id, now()))
        return self.job(job_id)

    def job(self, job_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def project_job_ids(self, media_id: str) -> list[str]:
        with self.connection() as db:
            return [row["id"] for row in db.execute(
                "SELECT id FROM jobs WHERE media_id=? ORDER BY id", (media_id,))]

    def list_jobs(self, limit: int, offset: int, *, archived: bool = False) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                """SELECT jobs.* FROM jobs JOIN media ON media.id=jobs.media_id
                WHERE (media.archived_at IS NOT NULL)=?
                ORDER BY jobs.created_at DESC, jobs.id LIMIT ? OFFSET ?""", (archived, limit, offset))]

    def recover(self) -> None:
        with self.connection() as db:
            db.execute("UPDATE media SET asset_status='deletion_incomplete' WHERE asset_status='deleting'")
            db.execute("""UPDATE jobs SET
                state=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'failed' END,
                phase='interrupted', error_code='server_interrupted',
                error_message='Server stopped during processing. Submit a new job to retry.', finished_at=?
                WHERE state='running'""", (now(),))

    def claim(self) -> dict | None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY created_at, id LIMIT 1").fetchone()
            if row is None:
                return None
            job_id = row["id"]
            db.execute("UPDATE jobs SET state='running', phase='starting', progress_pct=1, started_at=? WHERE id=?",
                       (now(), job_id))
        return self.job(job_id)

    def update_progress(self, job_id: str, manifest: dict) -> None:
        with self.connection() as db:
            db.execute("""UPDATE jobs SET phase=?, progress_pct=MAX(progress_pct, ?)
                WHERE id=? AND state='running'""",
                       (manifest["phase"], min(99, manifest.get("progress_pct", 1)), job_id))

    def cancel(self, job_id: str) -> dict | None:
        with self.connection() as db:
            db.execute("""UPDATE jobs SET cancel_requested=1,
                finished_at=CASE WHEN state='queued' THEN ? ELSE finished_at END,
                phase=CASE WHEN state='queued' THEN 'cancelled' ELSE phase END,
                state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END
                WHERE id=? AND state IN ('queued','running')""", (now(), job_id))
        return self.job(job_id)

    def finish(self, job_id: str, manifest: dict | None = None, error: str | None = None,
               cancelled: bool = False) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job is None or job["state"] != "running":
                return
            if cancelled or job["cancel_requested"]:
                db.execute("UPDATE jobs SET state='cancelled', phase='cancelled', finished_at=? WHERE id=?",
                           (now(), job_id))
                return
            if error is not None:
                db.execute("""UPDATE jobs SET state='failed', phase='failed', error_code='processing_failed',
                    error_message=?, finished_at=? WHERE id=?""", (error, now(), job_id))
                return
            if manifest is None or manifest.get("state") != "completed":
                raise ValueError("A completed manifest is required to publish results.")
            for clip in manifest["clips"]:
                candidate_id, clip_id = uuid.uuid4().hex, uuid.uuid4().hex
                db.execute("INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed')",
                           (candidate_id, job_id, job["source_candidate_id"], clip["start"], clip["end"],
                            clip["score"], json.dumps(clip["evidence"], ensure_ascii=False)))
                directory = Path("clips") / job_id
                db.execute("INSERT INTO clips VALUES (?, ?, ?, ?, ?)", (
                    clip_id, candidate_id, str(directory / clip["file"]),
                    str(directory / clip["subtitle_file"]) if clip.get("subtitle_file") else None,
                    str(directory / clip["srt_file"]) if clip.get("srt_file") else None,
                ))
            db.execute("""UPDATE jobs SET state='completed', phase='done', progress_pct=100,
                manifest_json=?, finished_at=? WHERE id=?""",
                       (json.dumps(manifest, ensure_ascii=False), now(), job_id))

    def candidates(self, job_id: str) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute("""SELECT c.*, p.id AS clip_id,
                p.srt_path IS NOT NULL AS has_subtitles FROM candidates c
                JOIN clips p ON p.candidate_id=c.id WHERE c.job_id=? ORDER BY c.score DESC, c.start, c.id""", (job_id,))]

    def candidate(self, candidate_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        return dict(row) if row else None

    def review(self, candidate_id: str, state: str) -> dict | None:
        with self.connection() as db:
            db.execute("UPDATE candidates SET review_state=? WHERE id=?", (state, candidate_id))
        return self.candidate(candidate_id)

    def clip(self, clip_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        return dict(row) if row else None
