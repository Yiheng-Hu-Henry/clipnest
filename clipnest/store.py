"""SQLite 持久层。

一条剪贴板记录的去重键是内容本身的 SHA-256。同一段文字被反复复制时不会
产生新行,而是累加 ``hits`` 并刷新 ``last_used_at`` —— 这让「常用片段」自然
浮到列表顶部,不需要额外的收藏机制。
"""

from __future__ import annotations

import functools
import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TypeVar

DEFAULT_MAX_CHARS = 100_000

_T = TypeVar("_T")

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content      TEXT    NOT NULL,
    digest       TEXT    NOT NULL UNIQUE,
    kind         TEXT    NOT NULL DEFAULT 'text',
    pinned       INTEGER NOT NULL DEFAULT 0,
    hits         INTEGER NOT NULL DEFAULT 0,
    created_at   REAL    NOT NULL,
    last_used_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_last_used ON clips(last_used_at DESC);
CREATE INDEX IF NOT EXISTS idx_clips_pinned ON clips(pinned);
CREATE INDEX IF NOT EXISTS idx_clips_kind ON clips(kind);
"""


def _locked(method: Callable[..., _T]) -> Callable[..., _T]:
    """串行化对同一个 SQLite 连接的访问。

    ``sqlite3.Connection`` 默认不允许跨线程使用，但监听线程与 Web 请求线程
    天然共享同一个 Store。改用 ``check_same_thread=False`` 配一把可重入锁，
    比「每个线程各开一个连接」简单，也避开了 WAL 下的写冲突。
    """

    @functools.wraps(method)
    def wrapper(self: "Store", *args: object, **kwargs: object) -> _T:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


def default_db_path() -> Path:
    """默认库位置,可用环境变量 ``CLIPNEST_DB`` 覆盖（测试和多实例都靠它）。"""
    override = os.environ.get("CLIPNEST_DB")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".clipnest" / "clips.db"


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _escape_like(keyword: str) -> str:
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class Clip:
    id: int
    content: str
    kind: str
    pinned: bool
    hits: int
    created_at: float
    last_used_at: float

    @property
    def preview(self) -> str:
        """单行摘要,供列表展示。"""
        return self.snippet(80)

    def snippet(self, width: int) -> str:
        one_line = " ".join(self.content.split())
        if len(one_line) <= width:
            return one_line
        return one_line[: max(0, width - 3)] + "..."

    @property
    def lines(self) -> int:
        return self.content.count("\n") + 1


class Store:
    """剪贴板历史的读写入口。内部有锁，可被多个线程共享。"""

    def __init__(
        self,
        path: Optional[os.PathLike | str] = None,
        *,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.max_chars = max_chars
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path), timeout=5.0, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ---------------------------------------------------------------- 生命周期

    @_locked
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---------------------------------------------------------------- 写入

    @_locked
    def add(
        self,
        text: str,
        *,
        kind: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Tuple[Optional[Clip], bool]:
        """写入一条记录。

        返回 ``(clip, is_new)``；内容为空时返回 ``(None, False)``。超长内容按
        ``max_chars`` 截断,并在截断处补一行说明,避免无声丢数据。
        """
        if not text or not text.strip():
            return None, False

        if len(text) > self.max_chars:
            text = text[: self.max_chars] + "\n… [clipnest] 内容过长,已截断"

        stamp = time.time() if now is None else now
        digest = digest_of(text)
        if kind is None:
            from .classify import classify

            kind = classify(text)

        row = self._conn.execute(
            "SELECT * FROM clips WHERE digest = ?", (digest,)
        ).fetchone()
        if row is not None:
            self._conn.execute(
                "UPDATE clips SET hits = hits + 1, last_used_at = ? WHERE id = ?",
                (stamp, row["id"]),
            )
            self._conn.commit()
            refreshed = self._get(int(row["id"]))
            assert refreshed is not None
            return refreshed, False

        cursor = self._conn.execute(
            "INSERT INTO clips (content, digest, kind, pinned, hits, created_at, last_used_at)"
            " VALUES (?, ?, ?, 0, 0, ?, ?)",
            (text, digest, kind, stamp, stamp),
        )
        self._conn.commit()
        created = self._get(int(cursor.lastrowid))
        assert created is not None
        return created, True

    @_locked
    def pin(self, clip_id: int, pinned: bool = True) -> bool:
        cursor = self._conn.execute(
            "UPDATE clips SET pinned = ? WHERE id = ?", (1 if pinned else 0, clip_id)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    @_locked
    def delete(self, clip_id: int) -> bool:
        cursor = self._conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    @_locked
    def clear(self, *, keep_pinned: bool = True) -> int:
        sql = (
            "DELETE FROM clips"
            if not keep_pinned
            else "DELETE FROM clips WHERE pinned = 0"
        )
        cursor = self._conn.execute(sql)
        self._conn.commit()
        return cursor.rowcount

    # ---------------------------------------------------------------- 读取

    @_locked
    def get(self, clip_id: int) -> Optional[Clip]:
        return self._get(clip_id)

    def _get(self, clip_id: int) -> Optional[Clip]:
        row = self._conn.execute(
            "SELECT * FROM clips WHERE id = ?", (clip_id,)
        ).fetchone()
        return _row_to_clip(row) if row is not None else None

    @_locked
    def search(
        self,
        keyword: str = "",
        *,
        limit: int = 100,
        kind: Optional[str] = None,
        pinned_only: bool = False,
    ) -> List[Clip]:
        clauses: List[str] = []
        params: List[object] = []
        if keyword:
            clauses.append("content LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(keyword)}%")
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if pinned_only:
            clauses.append("pinned = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, limit))
        rows = self._conn.execute(
            f"SELECT * FROM clips {where} ORDER BY pinned DESC, last_used_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_clip(row) for row in rows]

    @_locked
    def recent(self, limit: int = 100) -> List[Clip]:
        return self.search(limit=limit)

    # ---------------------------------------------------------------- 维护

    @_locked
    def purge(
        self,
        *,
        days: Optional[float] = None,
        max_entries: Optional[int] = None,
        keep_pinned: bool = True,
        now: Optional[float] = None,
    ) -> int:
        """按时间或条数清理历史,返回删除行数。置顶条目默认豁免。"""
        stamp = time.time() if now is None else now
        removed = 0
        guard = "AND pinned = 0" if keep_pinned else ""

        if days is not None:
            cutoff = stamp - float(days) * 86400.0
            cursor = self._conn.execute(
                f"DELETE FROM clips WHERE last_used_at < ? {guard}", (cutoff,)
            )
            removed += cursor.rowcount

        if max_entries is not None and max_entries >= 0:
            cursor = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM clips WHERE 1=1 {guard}"
            )
            total = int(cursor.fetchone()["n"])
            excess = total - max_entries
            if excess > 0:
                cursor = self._conn.execute(
                    f"SELECT id FROM clips WHERE 1=1 {guard}"
                    " ORDER BY last_used_at DESC LIMIT ? OFFSET ?",
                    (excess, max_entries),
                )
                stale_ids = [int(row["id"]) for row in cursor.fetchall()]
                if stale_ids:
                    placeholders = ",".join("?" * len(stale_ids))
                    cursor = self._conn.execute(
                        f"DELETE FROM clips WHERE id IN ({placeholders})", stale_ids
                    )
                    removed += cursor.rowcount

        self._conn.commit()
        return removed

    @_locked
    def stats(self) -> Dict[str, object]:
        total = int(
            self._conn.execute("SELECT COUNT(*) AS n FROM clips").fetchone()["n"]
        )
        pinned = int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM clips WHERE pinned = 1"
            ).fetchone()["n"]
        )
        by_kind = {
            str(row["kind"]): int(row["n"])
            for row in self._conn.execute(
                "SELECT kind, COUNT(*) AS n FROM clips GROUP BY kind ORDER BY n DESC"
            )
        }
        span = self._conn.execute(
            "SELECT MIN(created_at) AS first, MAX(last_used_at) AS last FROM clips"
        ).fetchone()
        size = self.path.stat().st_size if self.path.exists() else 0
        return {
            "total": total,
            "pinned": pinned,
            "by_kind": by_kind,
            "first_at": span["first"],
            "last_at": span["last"],
            "db_path": str(self.path),
            "db_bytes": size,
            "max_chars": self.max_chars,
        }


def _row_to_clip(row: sqlite3.Row) -> Clip:
    return Clip(
        id=int(row["id"]),
        content=str(row["content"]),
        kind=str(row["kind"]),
        pinned=bool(row["pinned"]),
        hits=int(row["hits"]),
        created_at=float(row["created_at"]),
        last_used_at=float(row["last_used_at"]),
    )
