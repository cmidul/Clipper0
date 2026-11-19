"""Regression coverage for durable history and project-owned file cleanup."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from autoclip.api import create_app
from autoclip.engine import Settings
from autoclip.service import Service
from autoclip.store import ProjectAssetConflict, Store


class ProjectManagementTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.data = self.root / "app-data"
        self.recordings = self.root / "recordings"
        self.recordings.mkdir()
        self.database = self.data / "state.sqlite3"
        self.settings = Settings(self.data)
        self.service = Service(self.settings, self.database, self.recordings)
        self.store = self.service.store

    def write(self, path, content=b"fixture"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def project(self, filename="recording.mp4"):
        media_id = uuid4().hex
        name = f"{media_id}.mp4"
        path = self.write(self.data / "imports" / name)
        record = self.store.add_media(media_id, filename, name, "a" * 64, {"duration": 30})
        return record["id"], path

    def output(self, media_id):
        job = self.store.create_job(media_id, {})
        self.assertEqual(self.store.claim()["id"], job["id"])
        self.store.finish(job["id"], manifest={
            "state": "completed",
            "clips": [{"start": 0, "end": 15, "score": 1, "evidence": {}, "file": "clip-01.mp4"}],
        })
        return job["id"], self.write(self.data / "clips" / job["id"] / "clip-01.mp4")

    def test_v1_migration_preserves_existing_project_and_allows_insert(self):
        legacy = self.root / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy)) as db, db:
            db.execute("""CREATE TABLE media (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, stored_name TEXT NOT NULL UNIQUE,
                sha256 TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
            )""")
            db.execute("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?)",
                       ("old", "recording.mp4", "old.mp4", "a" * 64, json.dumps({"duration": 30}), "2026-11-19"))
            db.execute("PRAGMA user_version=1")
        upgraded = Store(legacy)
        self.assertEqual(upgraded.media("old")["filename"], "recording.mp4")
        self.assertIsNone(upgraded.media("old")["archived_at"])
        self.assertEqual(upgraded.media("old")["asset_status"], "available")
        self.assertEqual(upgraded.add_media("new", "new.mp4", "new.mp4", "b" * 64, {})["asset_status"], "available")
        with Store(legacy).connection() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_archive_hides_jobs_without_cancelling_and_restores_after_reopen(self):
        media_id, copy = self.project()
        job = self.store.create_job(media_id, {})
        self.store.set_media_archived(media_id, True)
        reopened = Store(self.database)
        self.assertEqual(reopened.list_media(100, 0), [])
        self.assertEqual(reopened.list_jobs(100, 0), [])
        self.assertEqual(reopened.list_media(100, 0, archived=True)[0]["id"], media_id)
        self.assertEqual(reopened.list_jobs(100, 0, archived=True)[0]["state"], "queued")
        self.assertTrue(copy.is_file())
        reopened.set_media_archived(media_id, False)
        self.assertEqual(Store(self.database).list_jobs(100, 0)[0]["id"], job["id"])

    def test_queued_and_running_preview_block_deletion_until_terminal(self):
        media_id, copy = self.project()
        job = self.store.create_job(media_id, {"operation": "frame_preview", "time": 0})
        with self.assertRaises(ProjectAssetConflict):
            self.service.delete_project_assets(media_id)
        self.store.claim()
        self.store.cancel(job["id"])
        with self.assertRaises(ProjectAssetConflict):
            self.service.delete_project_assets(media_id)
        self.assertTrue(copy.is_file())
        self.store.finish(job["id"], cancelled=True)
        self.assertEqual(self.service.delete_project_assets(media_id)["media"]["asset_status"], "deleted")
        with self.assertRaises(ProjectAssetConflict):
            self.store.create_job(media_id, {})

    def test_interrupted_delete_can_retry_and_blocks_new_jobs(self):
        media_id, copy = self.project()
        self.store.begin_asset_deletion(media_id)
        with self.assertRaises(ProjectAssetConflict):
            self.store.create_job(media_id, {})
        with self.assertRaises(ProjectAssetConflict):
            self.store.begin_asset_deletion(media_id)
        reopened = Service(self.settings, self.database, self.recordings)
        reopened.store.recover()
        self.assertEqual(reopened.store.media(media_id)["asset_status"], "deletion_incomplete")
        self.assertEqual(reopened.delete_project_assets(media_id)["media"]["asset_status"], "deleted")
        self.assertFalse(copy.exists())

    def test_cleanup_retains_original_other_project_and_shared_cache(self):
        media_id, copy = self.project()
        _, clip = self.output(media_id)
        transcript = self.write(clip.with_name("transcript.json"))
        original = self.write(self.recordings / "recording.mp4", b"original")
        other_id, other_copy = self.project("other.mp4")
        _, other_clip = self.output(other_id)
        cache = self.write(self.data / "transcripts" / "shared.json")
        result = self.service.delete_project_assets(media_id)
        self.assertEqual(result["media"]["asset_status"], "deleted")
        self.assertEqual(result["failures"], [])
        for path in (copy, clip, transcript):
            self.assertFalse(path.exists())
        for path in (other_copy, other_clip, cache):
            self.assertTrue(path.is_file())
        self.assertEqual(original.read_bytes(), b"original")
        self.assertEqual(len(self.store.list_media(100, 0)), 2)

    def test_cleanup_preserves_hard_links_and_can_retry_after_unlink_failure(self):
        media_id, copy = self.project()
        _, clip = self.output(media_id)
        shared = self.write(self.root / "shared.txt", b"shared")
        link = clip.with_name("transcript.json")
        os.link(shared, link)
        original_unlink = Path.unlink

        def blocked_unlink(path, *args, **kwargs):
            if path == clip:
                raise PermissionError("file in use")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", blocked_unlink):
            result = self.service.delete_project_assets(media_id)
        self.assertEqual(result["media"]["asset_status"], "deletion_incomplete")
        self.assertEqual({Path(item["asset"]).name for item in result["failures"]}, {clip.name, link.name})
        self.assertFalse(copy.exists())
        self.assertTrue(clip.is_file())
        self.assertTrue(link.is_file())
        self.assertEqual(shared.read_bytes(), b"shared")
        link.unlink()
        result = self.service.delete_project_assets(media_id)
        self.assertEqual(result["media"]["asset_status"], "deleted")
        self.assertEqual(result["failures"], [])
        self.assertFalse(clip.exists())
        self.assertEqual(shared.read_bytes(), b"shared")

    def test_invalid_managed_import_name_preserves_original(self):
        media_id = uuid4().hex
        original = self.write(self.recordings / "original.mp4", b"original")
        self.store.add_media(media_id, original.name, str(original), "a" * 64, {})
        result = self.service.delete_project_assets(media_id)
        self.assertEqual(result["media"]["asset_status"], "deletion_incomplete")
        self.assertEqual(result["failures"][0]["asset"], "Managed import")
        self.assertEqual(original.read_bytes(), b"original")

    def test_api_requires_confirmation_and_withholds_deleted_assets(self):
        media_id, copy = self.project()
        job_id, clip = self.output(media_id)
        with patch.dict(os.environ, {"AUTOCLIP_DB_PATH": str(self.database),
                                     "AUTOCLIP_RECORDINGS_DIR": str(self.recordings)}):
            with TestClient(create_app(self.settings, start_worker=False),
                            base_url="http://127.0.0.1:8000") as client:
                candidates_url = f"/jobs/{job_id}/candidates"
                candidate = client.get(candidates_url).json()[0]
                self.assertEqual(client.post(f"/media/{media_id}/archive").status_code, 200)
                self.assertEqual(client.get("/media").json(), [])
                self.assertEqual(client.get("/jobs").json(), [])
                self.assertEqual(client.get("/media?archived=true").json()[0]["id"], media_id)
                self.assertEqual(client.post(f"/media/{media_id}/restore").status_code, 200)

                url = f"/media/{media_id}/delete-assets"
                self.assertEqual(client.post(url, json={"confirm": False}).status_code, 422)
                self.assertTrue(copy.is_file())
                self.assertTrue(clip.is_file())
                response = client.post(url, json={"confirm": True})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["media"]["asset_status"], "deleted")
                self.assertEqual(client.get(candidates_url).json(), [])
                self.assertEqual(client.get(candidate["preview_url"]).status_code, 410)
                self.assertEqual(client.post("/jobs", json={"media_id": media_id}).status_code, 409)
                self.assertEqual(client.get("/jobs").json()[0]["id"], job_id)
