"""clipnest —— 一个不依赖第三方库的 Windows 剪贴板历史管理器。

模块划分::

    classify  内容分类（url / code / path / json ...）
    filter    敏感内容识别（密钥、密码、身份证号等）
    store     SQLite 持久层
    reader    Win32 剪贴板读写（ctypes）
    daemon    轮询监听
    gui       tkinter 界面
    cli       命令行入口
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
