"""本地 Web 界面。

不依赖 tkinter：用标准库起一个只监听回环地址的 HTTP 服务，在浏览器里管理
历史。任何装了 Python 3.9+ 的机器都能直接跑，也方便从手机（同一局域网、
加个端口映射）翻看。

服务是单线程的 —— 本地单用户场景下足够，而且省掉了 SQLite 连接跨线程
使用的麻烦。所有写操作都不落外部网络。
"""

from __future__ import annotations

import json
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import __version__
from .reader import available as clipboard_available
from .reader import write_clipboard_text
from .store import Clip, Store

UI_FILE = Path(__file__).with_name("webui.html")

ClipIdRoute = Tuple[int, str]


def _clip_payload(clip: Clip) -> Dict[str, Any]:
    return {
        "id": clip.id,
        "content": clip.content,
        "kind": clip.kind,
        "pinned": clip.pinned,
        "hits": clip.hits,
        "created_at": clip.created_at,
        "last_used_at": clip.last_used_at,
        "preview": clip.preview,
        "lines": clip.lines,
    }


def _send(handler: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _send_json(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _send(handler, status, body, "application/json; charset=utf-8")


def _parse_clip_route(path: str) -> Optional[ClipIdRoute]:
    """把 ``/api/clips/12/pin`` 解析成 ``(12, "pin")``；不匹配返回 ``None``。"""
    parts = [piece for piece in path.strip("/").split("/") if piece]
    if len(parts) not in (3, 4) or parts[0] != "api" or parts[1] != "clips":
        return None
    try:
        clip_id = int(parts[2])
    except ValueError:
        return None
    action = parts[3] if len(parts) == 4 else ""
    return clip_id, action


class ClipNestHandler(BaseHTTPRequestHandler):
    store: Store
    server_version = f"clipnest/{__version__}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        """静音访问日志，终端只留一行启动提示。"""

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            try:
                html = UI_FILE.read_text(encoding="utf-8")
            except OSError:
                _send_json(self, {"error": "webui.html 缺失，请重新安装"}, 500)
                return
            body = html.replace("__VERSION__", __version__).encode("utf-8")
            _send(self, 200, body, "text/html; charset=utf-8")
            return

        if parsed.path == "/api/clips":
            keyword = (query.get("q") or [""])[0]
            kind = (query.get("kind") or [""])[0] or None
            try:
                limit = int((query.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            clips = self.store.search(keyword, limit=max(1, min(limit, 2000)), kind=kind)
            _send_json(self, {"clips": [_clip_payload(clip) for clip in clips]})
            return

        if parsed.path == "/api/stats":
            stats = self.store.stats()
            stats["clipboard"] = clipboard_available()
            _send_json(self, stats)
            return

        route = _parse_clip_route(parsed.path)
        if route is not None and route[1] == "":
            clip = self.store.get(route[0])
            if clip is None:
                _send_json(self, {"error": "not found"}, 404)
            else:
                _send_json(self, _clip_payload(clip))
            return

        _send_json(self, {"error": "not found"}, 404)

    # ----------------------------------------------------------------- POST

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = _parse_clip_route(parsed.path)

        if parsed.path == "/api/purge":
            payload = self._read_json()
            removed = self.store.purge(
                days=payload.get("days"),
                max_entries=payload.get("max_entries"),
                keep_pinned=payload.get("keep_pinned", True),
            )
            _send_json(self, {"removed": removed})
            return

        if route is None:
            _send_json(self, {"error": "not found"}, 404)
            return

        clip_id, action = route
        clip = self.store.get(clip_id)
        if clip is None:
            _send_json(self, {"error": "not found"}, 404)
            return

        if action == "pin":
            payload = self._read_json()
            self.store.pin(clip_id, pinned=bool(payload.get("pinned", True)))
            _send_json(self, {"ok": True})
            return

        if action == "copy":
            if not write_clipboard_text(clip.content):
                _send_json(self, {"error": "写剪贴板失败"}, 500)
                return
            self.store.add(clip.content)
            _send_json(self, {"ok": True})
            return

        _send_json(self, {"error": "unknown action"}, 400)

    # --------------------------------------------------------------- DELETE

    def do_DELETE(self) -> None:  # noqa: N802
        route = _parse_clip_route(urllib.parse.urlparse(self.path).path)
        if route is None or route[1] != "":
            _send_json(self, {"error": "not found"}, 404)
            return
        if not self.store.delete(route[0]):
            _send_json(self, {"error": "not found"}, 404)
            return
        _send_json(self, {"ok": True})

    # ----------------------------------------------------------------- 工具

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


def make_server(store: Store, port: int = 8765, host: str = "127.0.0.1") -> HTTPServer:
    """构造（但不启动）HTTP 服务，便于测试时自己控制生命周期。"""
    handler = type("BoundClipNestHandler", (ClipNestHandler,), {"store": store})
    server = HTTPServer((host, port), handler)
    return server


def serve(store: Store, port: int = 8765, *, open_browser: bool = True) -> int:
    """启动界面，阻塞到 Ctrl+C。"""
    server = make_server(store, port=port)
    url = f"http://127.0.0.1:{port}/"
    print(f"clipnest 界面已启动：{url}")
    print("Ctrl+C 退出。")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        server.server_close()
    return 0
