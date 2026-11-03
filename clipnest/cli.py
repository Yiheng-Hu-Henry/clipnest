"""命令行入口。

用法概览::

    clipnest list --search 正则 --limit 20
    clipnest stats
    clipnest pin 12 / unpin 12 / rm 12
    clipnest purge --days 30 --max 500
    clipnest export backup.json
    clipnest watch
    clipnest serve
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import List, Optional

from . import __version__
from .store import Clip, Store, default_db_path


def force_utf8_stdio() -> None:
    """把 stdout/stderr 切到 UTF-8。

    Windows 上输出被重定向（管道、文件、CI 日志）时，Python 会用系统 ANSI 代码页
    （cp1252 / cp936）编码，打印中文或 ``✓`` 这类字符会直接抛 ``UnicodeEncodeError``。
    控制台本身走 WriteConsoleW，在这里把编码固定成 UTF-8 不会造成乱码。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # pragma: no cover - 被替换成非 TextIOWrapper 的流
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):  # pragma: no cover - 极少数不可重配的流
            pass


def human_age(timestamp: Optional[float], *, now: Optional[float] = None) -> str:
    """把时间戳渲染成 ``3m`` / ``2h`` / ``5d`` 这样的短形式。"""
    if not timestamp:
        return "-"
    delta = (time.time() if now is None else now) - float(timestamp)
    if delta < 0:
        return "now"
    if delta < 60:
        return f"{int(delta)}s"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    return f"{int(delta // 86400)}d"


def human_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:.1f}GB"


def _print_table(clips: List[Clip]) -> None:
    if not clips:
        print("（没有匹配的条目）")
        return
    header = f"{'ID':>5}  {'KIND':<6} {'HITS':>4}  {'AGE':>5}  PREVIEW"
    print(header)
    print("-" * min(len(header) + 20, 100))
    for clip in clips:
        flag = "*" if clip.pinned else " "
        print(
            f"{clip.id:>5}{flag} {clip.kind:<6} {clip.hits:>4}  "
            f"{human_age(clip.last_used_at):>5}  {clip.preview}"
        )


# --------------------------------------------------------------------- 子命令


def cmd_list(args: argparse.Namespace, store: Store) -> int:
    clips = store.search(
        args.search or "",
        limit=args.limit,
        kind=args.kind,
        pinned_only=args.pinned,
    )
    if args.json:
        print(json.dumps([clip.__dict__ for clip in clips], ensure_ascii=False, indent=2))
        return 0
    _print_table(clips)
    return 0


def cmd_show(args: argparse.Namespace, store: Store) -> int:
    clip = store.get(args.id)
    if clip is None:
        print(f"找不到 id={args.id} 的条目", file=sys.stderr)
        return 1
    print(clip.content)
    return 0


def cmd_stats(args: argparse.Namespace, store: Store) -> int:
    data = store.stats()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"库文件   {data['db_path']}  ({human_bytes(float(data['db_bytes']))})")
    print(f"条目总数 {data['total']}   置顶 {data['pinned']}")
    first = data["first_at"]
    print(f"最早一条 {human_age(first) + ' 前' if first else '-'}")
    by_kind = data["by_kind"] or {}
    if by_kind:
        print("按类型   " + "  ".join(f"{k}:{v}" for k, v in by_kind.items()))
    return 0


def cmd_pin(args: argparse.Namespace, store: Store) -> int:
    return 0 if store.pin(args.id, pinned=True) else 1


def cmd_unpin(args: argparse.Namespace, store: Store) -> int:
    return 0 if store.pin(args.id, pinned=False) else 1


def cmd_rm(args: argparse.Namespace, store: Store) -> int:
    if not store.delete(args.id):
        print(f"找不到 id={args.id} 的条目", file=sys.stderr)
        return 1
    return 0


def cmd_clear(args: argparse.Namespace, store: Store) -> int:
    removed = store.clear(keep_pinned=not args.all)
    print(f"已删除 {removed} 条" + ("" if args.all else "（置顶条目保留）"))
    return 0


def cmd_purge(args: argparse.Namespace, store: Store) -> int:
    removed = store.purge(
        days=args.days,
        max_entries=args.max,
        keep_pinned=not args.include_pinned,
    )
    print(f"已清理 {removed} 条")
    return 0


def cmd_add(args: argparse.Namespace, store: Store) -> int:
    text = args.text
    if text is None:
        if sys.stdin.isatty():
            print("从标准输入读取内容，Ctrl-Z 回车结束…", file=sys.stderr)
        text = sys.stdin.read()
    clip, is_new = store.add(text)
    if clip is None:
        print("内容为空，已忽略", file=sys.stderr)
        return 1
    print(f"{'新增' if is_new else '已存在'} id={clip.id} ({clip.kind})")
    return 0


def cmd_export(args: argparse.Namespace, store: Store) -> int:
    clips = store.search(limit=10**9)
    payload = {
        "version": __version__,
        "exported_at": time.time(),
        "count": len(clips),
        "clips": [clip.__dict__ for clip in clips],
    }
    target = args.path
    if target == "-":
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"已导出 {len(clips)} 条到 {target}")
    return 0


def cmd_watch(args: argparse.Namespace, store: Store) -> int:
    from .daemon import watch_forever
    from .reader import available

    if not available():
        print("当前平台不支持剪贴板读取（仅 Windows）", file=sys.stderr)
        return 1

    print("采样中，Ctrl+C 结束。", file=sys.stderr)

    def announce(clip: Clip, is_new: bool) -> None:
        print(f"+ {clip.kind:<6} {clip.preview}")

    watch_forever(
        store,
        interval=args.interval,
        skip_sensitive=not args.allow_sensitive,
        on_new=announce,
    )
    return 0


def cmd_serve(args: argparse.Namespace, store: Store) -> int:
    from .web import serve

    return serve(store, port=args.port, open_browser=not args.no_browser)


# --------------------------------------------------------------------- 解析


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clipnest",
        description="剪贴板历史管理器：本地 SQLite 存储，敏感内容自动跳过。",
    )
    parser.add_argument("--db", help=f"数据库路径（默认 {default_db_path()}）")
    parser.add_argument("--version", action="version", version=f"clipnest {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="列出历史")
    p_list.add_argument("-s", "--search", help="按关键字过滤")
    p_list.add_argument("-n", "--limit", type=int, default=20, help="条数上限")
    p_list.add_argument("-k", "--kind", help="按类型过滤")
    p_list.add_argument("--pinned", action="store_true", help="只看置顶")
    p_list.add_argument("--json", action="store_true", help="输出 JSON")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="打印某条完整内容")
    p_show.add_argument("id", type=int)
    p_show.set_defaults(func=cmd_show)

    p_stats = sub.add_parser("stats", help="统计信息")
    p_stats.add_argument("--json", action="store_true")
    p_stats.set_defaults(func=cmd_stats)

    for name, handler, text in (
        ("pin", cmd_pin, "置顶"),
        ("unpin", cmd_unpin, "取消置顶"),
        ("rm", cmd_rm, "删除"),
    ):
        sub_p = sub.add_parser(name, help=text)
        sub_p.add_argument("id", type=int)
        sub_p.set_defaults(func=handler)

    p_clear = sub.add_parser("clear", help="清空历史")
    p_clear.add_argument("--all", action="store_true", help="连同置顶一起删")
    p_clear.set_defaults(func=cmd_clear)

    p_purge = sub.add_parser("purge", help="按时间/条数清理")
    p_purge.add_argument("--days", type=float, help="删除超过 N 天未使用的条目")
    p_purge.add_argument("--max", type=int, help="最多保留 N 条")
    p_purge.add_argument("--include-pinned", action="store_true", help="置顶也参与清理")
    p_purge.set_defaults(func=cmd_purge)

    p_add = sub.add_parser("add", help="手动写入一条（不给参数则读标准输入）")
    p_add.add_argument("text", nargs="?")
    p_add.set_defaults(func=cmd_add)

    p_export = sub.add_parser("export", help="导出为 JSON")
    p_export.add_argument("path", nargs="?", default="-", help="输出文件，默认标准输出")
    p_export.set_defaults(func=cmd_export)

    p_watch = sub.add_parser("watch", help="后台监听剪贴板")
    p_watch.add_argument("--interval", type=float, default=0.6, help="采样间隔（秒）")
    p_watch.add_argument(
        "--allow-sensitive", action="store_true", help="不过滤密钥/密码类内容"
    )
    p_watch.set_defaults(func=cmd_watch)

    p_ui = sub.add_parser("serve", help="启动本地 Web 界面")
    p_ui.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765）")
    p_ui.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    p_ui.set_defaults(func=cmd_serve)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    with Store(args.db) as store:
        return int(args.func(args, store) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
