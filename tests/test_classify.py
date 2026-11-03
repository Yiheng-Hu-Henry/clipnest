from __future__ import annotations

import unittest

from clipnest.classify import classify


class ClassifyTestCase(unittest.TestCase):
    def test_url(self) -> None:
        self.assertEqual(classify("https://github.com/Yiheng-Hu-Henry"), "url")
        self.assertEqual(classify("http://localhost:8000/api?x=1"), "url")

    def test_url_like_text_is_not_url(self) -> None:
        self.assertEqual(classify("what is https://example.com ?"), "text")

    def test_email(self) -> None:
        self.assertEqual(classify("1185099837@qq.com"), "email")

    def test_color(self) -> None:
        self.assertEqual(classify("#FF8800"), "color")
        self.assertEqual(classify("#fff"), "color")

    def test_windows_path(self) -> None:
        self.assertEqual(classify(r"C:\Users\Henry\Documents"), "path")
        self.assertEqual(classify(r"\\nas\share\file.txt"), "path")

    def test_posix_path(self) -> None:
        self.assertEqual(classify("/usr/local/bin"), "path")
        self.assertEqual(classify("~/projects/demo"), "path")

    def test_json(self) -> None:
        self.assertEqual(classify('{"a": [1, 2, 3]}'), "json")
        self.assertEqual(classify("[1, 2, 3]"), "json")
        self.assertEqual(classify("{not valid json}"), "text")

    def test_code(self) -> None:
        snippet = "def add(a, b):\n    return a + b\n"
        self.assertEqual(classify(snippet), "code")
        css = "const a = 1;\nconst b = 2;\nconst c = 3;\n"
        self.assertEqual(classify(css), "code")

    def test_plain_text(self) -> None:
        self.assertEqual(classify("明天上午十点评审"), "text")
        self.assertEqual(classify("hello world"), "text")

    def test_blank(self) -> None:
        self.assertEqual(classify("   "), "text")
        self.assertEqual(classify(""), "text")


if __name__ == "__main__":
    unittest.main()
