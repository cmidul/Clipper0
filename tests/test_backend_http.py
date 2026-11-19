"""Actual loopback HTTP check, requiring local socket access."""

import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import httpx
import uvicorn

from autoclip.api import create_app
from autoclip.engine import Settings


class LoopbackHttpTests(unittest.TestCase):
    def test_real_loopback_server_health_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.dict(os.environ, {"AUTOCLIP_DB_PATH": str(folder / "queue.sqlite3")}):
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(create_app(Settings(folder)),
                                                      host="127.0.0.1", port=port, log_level="error"))
                thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
                thread.start()
                try:
                    deadline = time.monotonic() + 10
                    while not server.started and thread.is_alive() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(server.started, "Loopback server did not start")
                    with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
                        response = client.get("/health")
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json()["status"], "ok")
                        self.assertEqual(client.get("/jobs").json(), [])
                        self.assertEqual(client.post("/jobs", json={"path": "arbitrary"}).status_code, 422)
                finally:
                    server.should_exit = True
                    thread.join(timeout=15)
                    listener.close()
                self.assertFalse(thread.is_alive(), "Server failed to shut down cleanly")


if __name__ == "__main__":
    unittest.main()
