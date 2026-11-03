"""剪贴板内容分类。

分类只用于给条目打标签、方便筛选，规则刻意保守：拿不准的一律算普通文本。
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
WIN_PATH_RE = re.compile(r"^(?:[a-zA-Z]:[\\/]|\\\\)[^\r\n]*$")
POSIX_PATH_RE = re.compile(r"^(?:~|\.{1,2})?/[^\r\n]*$")

#: 出现这些片段时,一个多行片段很可能是代码
CODE_HINTS = (
    "def ",
    "class ",
    "function ",
    "const ",
    "let ",
    "var ",
    "import ",
    "from ",
    "#include",
    "public ",
    "private ",
    "func ",
    "SELECT ",
    "select ",
    "<?php",
    "package ",
)

KINDS = ("text", "url", "email", "color", "path", "json", "code")


def _looks_like_url(value: str) -> bool:
    if "\n" in value or " " in value:
        return False
    parsed = urlparse(value)
    return bool(parsed.scheme in ("http", "https") and parsed.netloc)


def classify(text: str) -> str:
    """返回 ``text`` / ``url`` / ``email`` / ``color`` / ``path`` / ``json`` / ``code``。"""
    raw = text.strip()
    if not raw:
        return "text"

    if URL_RE.match(raw) and _looks_like_url(raw):
        return "url"
    if EMAIL_RE.match(raw) and "\n" not in raw:
        return "email"
    if COLOR_RE.match(raw):
        return "color"
    if (WIN_PATH_RE.match(raw) or POSIX_PATH_RE.match(raw)) and "\n" not in raw:
        return "path"

    if raw[0] in "{[" and raw[-1] in "}]":
        try:
            json.loads(raw)
        except ValueError:
            pass
        else:
            return "json"

    if "\n" in raw:
        if any(hint in raw for hint in CODE_HINTS) or raw.count(";") >= 3:
            return "code"
    elif len(raw) < 200 and any(raw.startswith(hint) for hint in CODE_HINTS):
        return "code"

    return "text"
