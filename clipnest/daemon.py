"""轮询式监听。

Windows 的剪贴板没有跨进程的变更通知（``AddClipboardFormatListener`` 要求
消息循环），对一个后台采集器来说，固定间隔轮询更省事也更稳。

关键细节:必须记住「上一次读到的内容指纹」。否则每轮轮询都会命中同一条记录,
把 ``hits`` 刷成天文数字。
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from .filter import find_sensitive
from .reader import read_clipboard_text
from .store import Clip, Store, digest_of

Reader = Callable[[], Optional[str]]
Observer = Callable[[Clip, bool], None]


class ClipboardWatcher:
    """把剪贴板里的文本采集进 ``Store``。"""

    def __init__(
        self,
        store: Store,
        *,
        reader: Reader = read_clipboard_text,
        interval: float = 0.6,
        skip_sensitive: bool = True,
        on_new: Optional[Observer] = None,
    ) -> None:
        self.store = store
        self.reader = reader
        self.interval = max(0.05, interval)
        self.skip_sensitive = skip_sensitive
        self.on_new = on_new
        self._last_digest: Optional[str] = None
        self._stop = threading.Event()

    # ------------------------------------------------------------- 单次采样

    def prime(self) -> None:
        """把启动那一刻剪贴板里的内容记为"已见过",避免开机就收录旧内容。"""
        try:
            text = self.reader()
        except Exception:  # 剪贴板被别的程序占住时会抛错,直接忽略
            return
        if text:
            self._last_digest = digest_of(text)

    def poll(self) -> Optional[Clip]:
        """采样一次。返回新写入的记录；无变化、被过滤时返回 ``None``。"""
        try:
            text = self.reader()
        except Exception:
            return None

        if text is None or not text.strip():
            return None

        digest = digest_of(text)
        if digest == self._last_digest:
            return None
        self._last_digest = digest

        if self.skip_sensitive and find_sensitive(text):
            return None

        clip, _ = self.store.add(text)
        if clip is not None and self.on_new is not None:
            self.on_new(clip, True)
        return clip

    # ------------------------------------------------------------- 循环

    def run(self, *, stop_event: Optional[threading.Event] = None) -> None:
        """阻塞轮询,直到 ``stop_event`` 被置位。"""
        event = stop_event or self._stop
        self.prime()
        while not event.is_set():
            self.poll()
            event.wait(self.interval)

    def start(self) -> threading.Event:
        """在后台线程里跑起来,返回用于停止的事件对象。"""
        self._stop.clear()
        thread = threading.Thread(target=self.run, name="clipnest-watcher", daemon=True)
        thread.start()
        return self._stop

    def stop(self) -> None:
        self._stop.set()


def watch_forever(
    store: Store,
    *,
    interval: float = 0.6,
    skip_sensitive: bool = True,
    on_new: Optional[Observer] = None,
) -> None:
    """便捷入口：一直采集到 ``KeyboardInterrupt``。"""
    watcher = ClipboardWatcher(
        store, interval=interval, skip_sensitive=skip_sensitive, on_new=on_new
    )
    try:
        watcher.run()
    except KeyboardInterrupt:
        pass
