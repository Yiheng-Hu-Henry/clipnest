from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import List, Optional

from clipnest.daemon import ClipboardWatcher
from clipnest.store import Store


class SequenceReader:
    """按顺序吐出预设内容，用完后一直返回 ``None``。"""

    def __init__(self, values: List[Optional[str]]) -> None:
        self._values = list(values)

    def __call__(self) -> Optional[str]:
        if not self._values:
            return None
        return self._values.pop(0)


class BoomReader:
    def __call__(self) -> Optional[str]:
        raise OSError("clipboard is locked by another process")


class WatcherTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "test.db")

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_poll_captures_new_content(self) -> None:
        watcher = ClipboardWatcher(self.store, reader=SequenceReader(["hello"]))
        clip = watcher.poll()
        assert clip is not None
        self.assertEqual(clip.content, "hello")
        self.assertEqual(self.store.stats()["total"], 1)

    def test_same_content_is_not_recorded_twice(self) -> None:
        watcher = ClipboardWatcher(
            self.store, reader=SequenceReader(["hello", "hello", "hello"])
        )
        self.assertIsNotNone(watcher.poll())
        self.assertIsNone(watcher.poll())
        self.assertIsNone(watcher.poll())
        clip = self.store.search()[0]
        self.assertEqual(clip.hits, 0)

    def test_repeating_after_other_content_counts_as_hit(self) -> None:
        watcher = ClipboardWatcher(
            self.store, reader=SequenceReader(["a", "b", "a"]), skip_sensitive=False
        )
        watcher.poll()
        watcher.poll()
        watcher.poll()
        contents = {clip.content: clip.hits for clip in self.store.search()}
        self.assertEqual(contents, {"a": 1, "b": 0})

    def test_blank_content_ignored(self) -> None:
        watcher = ClipboardWatcher(self.store, reader=SequenceReader(["   ", "\n\n"]))
        self.assertIsNone(watcher.poll())
        self.assertIsNone(watcher.poll())
        self.assertEqual(self.store.stats()["total"], 0)

    def test_sensitive_content_is_skipped(self) -> None:
        secret = "ghp_" + "z" * 36
        watcher = ClipboardWatcher(self.store, reader=SequenceReader([secret]))
        self.assertIsNone(watcher.poll())
        self.assertEqual(self.store.stats()["total"], 0)

    def test_sensitive_content_allowed_when_flag_off(self) -> None:
        secret = "ghp_" + "z" * 36
        watcher = ClipboardWatcher(
            self.store, reader=SequenceReader([secret]), skip_sensitive=False
        )
        self.assertIsNotNone(watcher.poll())
        self.assertEqual(self.store.stats()["total"], 1)

    def test_prime_skips_existing_clipboard(self) -> None:
        watcher = ClipboardWatcher(
            self.store, reader=SequenceReader(["already there", "already there"])
        )
        watcher.prime()
        self.assertIsNone(watcher.poll())
        self.assertEqual(self.store.stats()["total"], 0)

    def test_reader_exception_is_tolerated(self) -> None:
        watcher = ClipboardWatcher(self.store, reader=BoomReader())
        self.assertIsNone(watcher.poll())

    def test_on_new_callback(self) -> None:
        seen = []
        watcher = ClipboardWatcher(
            self.store,
            reader=SequenceReader(["first"]),
            on_new=lambda clip, is_new: seen.append(clip.content),
        )
        watcher.poll()
        self.assertEqual(seen, ["first"])

    def test_interval_floor(self) -> None:
        watcher = ClipboardWatcher(self.store, reader=SequenceReader([]), interval=0)
        self.assertGreaterEqual(watcher.interval, 0.05)


if __name__ == "__main__":
    unittest.main()
