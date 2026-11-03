"""Win32 剪贴板读写。

只用 ``ctypes`` 调 user32 / kernel32，不引入 pywin32。所有句柄都显式声明
``restype``，否则 64 位下返回值会被截成 32 位整数 —— 这是 ctypes 调用
Win32 API 最常见的坑，表现为访问违例或读到空字符串。
"""

from __future__ import annotations

import ctypes
import sys
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

if IS_WINDOWS:  # pragma: no cover - 平台相关
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL

    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalFree.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = wintypes.LPVOID
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL


def available() -> bool:
    """当前平台是否支持剪贴板读写。"""
    return IS_WINDOWS


def read_clipboard_text() -> Optional[str]:
    """读取剪贴板文本；不是文本或读不到时返回 ``None``。"""
    if not IS_WINDOWS:  # pragma: no cover
        return None

    if not _user32.OpenClipboard(None):
        return None
    try:
        if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()


def write_clipboard_text(text: str) -> bool:
    """把文本写回剪贴板；成功返回 ``True``。"""
    if not IS_WINDOWS:  # pragma: no cover
        return False

    buffer = (text + "\x00").encode("utf-16-le")
    handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(buffer))
    if not handle:
        return False

    pointer = _kernel32.GlobalLock(handle)
    if not pointer:
        _kernel32.GlobalFree(handle)
        return False
    try:
        ctypes.memmove(pointer, buffer, len(buffer))
    finally:
        _kernel32.GlobalUnlock(handle)

    if not _user32.OpenClipboard(None):
        _kernel32.GlobalFree(handle)
        return False
    try:
        _user32.EmptyClipboard()
        if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
            _kernel32.GlobalFree(handle)
            return False
    finally:
        _user32.CloseClipboard()
    return True
