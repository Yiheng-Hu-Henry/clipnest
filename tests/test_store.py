from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from clipnest.store import Store


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.store = Store(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    # ------------------------------------------------------------ 基本写入

    def test_add_creates_row(self) -> None:
        clip, is_new = self.store.add("hello world")
        self.assertTrue(is_new)
        self.assertIsNotNone(clip)
        assert clip is not None
        self.assertEqual(clip.content, "hello world")
        self.assertEqual(clip.kind, "text")
        self.assertEqual(clip.hits, 0)
        self.assertFalse(clip.pinned)

    def test_empty_content_is_ignored(self) -> None:
        for value in ("", "   ", "\n\t\n"):
            clip, is_new = self.store.add(value)
            self.assertIsNone(clip)
            self.assertFalse(is_new)
        self.assertEqual(self.store.stats()["total"], 0)

    def test_duplicate_bumps_hits_and_keeps_single_row(self) -> None:
        first, new1 = self.store.add("dup", now=100.0)
        second, new2 = self.store.add("dup", now=200.0)
        self.assertTrue(new1)
        self.assertFalse(new2)
        assert first is not None and second is not None
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.hits, 1)
        self.assertEqual(second.created_at, 100.0)
        self.assertEqual(second.last_used_at, 200.0)
        self.assertEqual(self.store.stats()["total"], 1)

    def test_long_content_is_truncated(self) -> None:
        store = Store(Path(self._tmp.name) / "small.db", max_chars=10)
        try:
            clip, _ = store.add("0123456789abcdef")
            assert clip is not None
            self.assertTrue(clip.content.startswith("0123456789"))
            self.assertIn("已截断", clip.content)
        finally:
            store.close()

    def test_kind_is_detected(self) -> None:
        clip, _ = self.store.add("https://example.com/a")
        assert clip is not None
        self.assertEqual(clip.kind, "url")

    # ------------------------------------------------------------ 查询

    def test_search_filters_by_keyword(self) -> None:
        self.store.add("alpha content")
        self.store.add("beta content")
        hits = self.store.search("alpha")
        self.assertEqual([clip.content for clip in hits], ["alpha content"])

    def test_search_escapes_like_wildcards(self) -> None:
        self.store.add("progress 100% done")
        self.store.add("progress 100 percent")
        hits = self.store.search("100%")
        self.assertEqual(len(hits), 1)
        self.assertIn("100%", hits[0].content)

    def test_pinned_sorts_first(self) -> None:
        old, _ = self.store.add("older", now=10.0)
        newer, _ = self.store.add("newer", now=20.0)
        assert old is not None and newer is not None
        self.store.pin(old.id)
        ordered = self.store.search()
        self.assertEqual([clip.content for clip in ordered], ["older", "newer"])

    def test_pinned_only_filter(self) -> None:
        a, _ = self.store.add("a")
        self.store.add("b")
        assert a is not None
        self.store.pin(a.id)
        pinned = self.store.search(pinned_only=True)
        self.assertEqual([clip.content for clip in pinned], ["a"])

    def test_kind_filter(self) -> None:
        self.store.add("https://example.com")
        self.store.add("plain text")
        urls = self.store.search(kind="url")
        self.assertEqual(len(urls), 1)

    def test_limit(self) -> None:
        for index in range(5):
            self.store.add(f"item {index}", now=float(index))
        self.assertEqual(len(self.store.search(limit=3)), 3)

    # ------------------------------------------------------------ 清理

    def test_delete(self) -> None:
        clip, _ = self.store.add("kill me")
        assert clip is not None
        self.assertTrue(self.store.delete(clip.id))
        self.assertFalse(self.store.delete(clip.id))
        self.assertEqual(self.store.stats()["total"], 0)

    def test_clear_keeps_pinned(self) -> None:
        a, _ = self.store.add("keep")
        b, _ = self.store.add("drop")
        assert a is not None and b is not None
        self.store.pin(a.id)
        removed = self.store.clear(keep_pinned=True)
        self.assertEqual(removed, 1)
        self.assertEqual([clip.content for clip in self.store.search()], ["keep"])

    def test_purge_by_days(self) -> None:
        self.store.add("ancient", now=0.0)
        self.store.add("fresh", now=1_000_000.0)
        removed = self.store.purge(days=1, now=1_000_000.0)
        self.assertEqual(removed, 1)
        self.assertEqual([clip.content for clip in self.store.search()], ["fresh"])

    def test_purge_by_days_spares_pinned(self) -> None:
        pinned, _ = self.store.add("ancient pinned", now=0.0)
        self.store.add("ancient loose", now=0.0)
        assert pinned is not None
        self.store.pin(pinned.id)
        self.assertEqual(self.store.purge(days=1, now=1_000_000.0), 1)
        self.assertEqual(self.store.stats()["total"], 1)

    def test_purge_by_max_entries(self) -> None:
        for index in range(5):
            self.store.add(f"item {index}", now=float(index))
        removed = self.store.purge(max_entries=2)
        self.assertEqual(removed, 3)
        remaining = [clip.content for clip in self.store.search()]
        self.assertEqual(remaining, ["item 4", "item 3"])

    def test_purge_max_entries_spares_pinned(self) -> None:
        pinned, _ = self.store.add("pinned old", now=0.0)
        for index in range(4):
            self.store.add(f"item {index}", now=float(index + 1))
        assert pinned is not None
        self.store.pin(pinned.id)
        self.store.purge(max_entries=2)
        remaining = [clip.content for clip in self.store.search()]
        self.assertEqual(len(remaining), 3)
        self.assertIn("pinned old", remaining)

    # ------------------------------------------------------------ 统计

    def test_stats(self) -> None:
        self.store.add("https://example.com")
        self.store.add("text")
        stats = self.store.stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["pinned"], 0)
        self.assertIsInstance(stats["db_path"], str)
        self.assertGreaterEqual(int(stats["db_bytes"]), 0)

    def test_context_manager_closes(self) -> None:
        with Store(Path(self._tmp.name) / "ctx.db") as store:
            store.add("inside")
        self.assertTrue((Path(self._tmp.name) / "ctx.db").exists())

    def test_db_path_env_override(self) -> None:
        target = Path(self._tmp.name) / "env.db"
        old = os.environ.get("CLIPNEST_DB")
        os.environ["CLIPNEST_DB"] = str(target)
        try:
            from clipnest.store import default_db_path

            self.assertEqual(default_db_path(), target)
        finally:
            if old is None:
                os.environ.pop("CLIPNEST_DB", None)
            else:
                os.environ["CLIPNEST_DB"] = old


if __name__ == "__main__":
    unittest.main()
