from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from clipnest.store import Store
from clipnest.web import make_server


class WebApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "web.db")
        self.first, _ = self.store.add("https://example.com/docs")
        self.second, _ = self.store.add("plain text note")
        assert self.first is not None and self.second is not None

        self.server = make_server(self.store, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.store.close()
        self._tmp.cleanup()

    # ------------------------------------------------------------ 辅助

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(self.url(path), timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def get_json(self, path: str) -> tuple[int, dict]:
        status, raw = self.get(path)
        return status, json.loads(raw.decode("utf-8"))

    def post(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            self.url(path),
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def delete(self, path: str) -> tuple[int, dict]:
        request = urllib.request.Request(self.url(path), method="DELETE")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    # ------------------------------------------------------------ 用例

    def test_index_page(self) -> None:
        status, raw = self.get("/")
        self.assertEqual(status, 200)
        html = raw.decode("utf-8")
        self.assertIn("clipnest", html)
        self.assertNotIn("__VERSION__", html)

    def test_list_clips(self) -> None:
        status, data = self.get_json("/api/clips")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["clips"]), 2)

    def test_list_clips_with_query(self) -> None:
        status, data = self.get_json("/api/clips?q=example")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["clips"]), 1)
        self.assertIn("example.com", data["clips"][0]["content"])

    def test_list_clips_with_kind_filter(self) -> None:
        status, data = self.get_json("/api/clips?kind=url")
        self.assertEqual(status, 200)
        self.assertEqual([clip["id"] for clip in data["clips"]], [self.first.id])

    def test_get_single_clip(self) -> None:
        status, data = self.get_json(f"/api/clips/{self.second.id}")
        self.assertEqual(status, 200)
        self.assertEqual(data["content"], "plain text note")

    def test_get_missing_clip(self) -> None:
        status, _ = self.get_json("/api/clips/999999")
        self.assertEqual(status, 404)

    def test_stats(self) -> None:
        status, data = self.get_json("/api/stats")
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 2)
        self.assertIn("clipboard", data)

    def test_pin_toggle(self) -> None:
        status, _ = self.post(f"/api/clips/{self.first.id}/pin", {"pinned": True})
        self.assertEqual(status, 200)
        self.assertTrue(self.store.get(self.first.id).pinned)

        self.post(f"/api/clips/{self.first.id}/pin", {"pinned": False})
        self.assertFalse(self.store.get(self.first.id).pinned)

    def test_copy_writes_clipboard(self) -> None:
        with mock.patch("clipnest.web.write_clipboard_text", return_value=True) as fake:
            status, data = self.post(f"/api/clips/{self.second.id}/copy")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        fake.assert_called_once_with("plain text note")
        self.assertEqual(self.store.get(self.second.id).hits, 1)

    def test_copy_reports_failure(self) -> None:
        with mock.patch("clipnest.web.write_clipboard_text", return_value=False):
            status, _ = self.post(f"/api/clips/{self.second.id}/copy")
        self.assertEqual(status, 500)

    def test_delete(self) -> None:
        status, _ = self.delete(f"/api/clips/{self.second.id}")
        self.assertEqual(status, 200)
        self.assertIsNone(self.store.get(self.second.id))

    def test_purge(self) -> None:
        status, data = self.post("/api/purge", {"days": 0, "keep_pinned": True})
        self.assertEqual(status, 200)
        self.assertGreaterEqual(data["removed"], 0)

    def test_unknown_route(self) -> None:
        status, _ = self.get_json("/api/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
