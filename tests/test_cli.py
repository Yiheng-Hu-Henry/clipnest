from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from clipnest.cli import force_utf8_stdio, human_age, main


class ForceUtf8StdioTestCase(unittest.TestCase):
    """Windows 上 stdout 被重定向时会用 ANSI 代码页，中文和 ✓ 会炸。"""

    def test_reconfigures_both_streams(self) -> None:
        fake_out = mock.MagicMock()
        fake_err = mock.MagicMock()
        with mock.patch("sys.stdout", fake_out), mock.patch("sys.stderr", fake_err):
            force_utf8_stdio()

        for stream in (fake_out, fake_err):
            stream.reconfigure.assert_called_once()
            kwargs = stream.reconfigure.call_args.kwargs
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertEqual(kwargs["errors"], "replace")

    def test_stream_without_reconfigure_is_ignored(self) -> None:
        # 有些包装流（如测试框架的 capture）没有 reconfigure，不能因此崩掉。
        with mock.patch("sys.stdout", object()):
            force_utf8_stdio()

    def test_only_utf8_can_encode_the_cli_glyphs(self) -> None:
        text = "新增 id=1 (text) 中文 ✓"
        with self.assertRaises(UnicodeEncodeError):
            text.encode("cp1252")
        self.assertEqual(text.encode("utf-8").decode("utf-8"), text)


class HumanAgeTestCase(unittest.TestCase):
    def test_renders_short_units(self) -> None:
        now = 1_700_000_000.0
        self.assertEqual(human_age(None, now=now), "-")
        self.assertEqual(human_age(now - 5, now=now), "5s")
        self.assertEqual(human_age(now - 180, now=now), "3m")
        self.assertEqual(human_age(now - 7200, now=now), "2h")
        self.assertEqual(human_age(now - 86400 * 3, now=now), "3d")


class MainEntryTestCase(unittest.TestCase):
    def test_version_exits_cleanly_and_forces_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "cli.db")
            fake_out = mock.MagicMock()
            with mock.patch("sys.stdout", fake_out):
                with self.assertRaises(SystemExit) as ctx:
                    main(["--version", "--db", db])
            self.assertEqual(ctx.exception.code, 0)
            fake_out.reconfigure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
