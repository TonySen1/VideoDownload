"""VideoDownload 启动入口。

打包后 PyInstaller 会执行本文件；源码运行时用 `python main.py`。

设计约定：程序内不弹任何对话框。启动阶段的致命错误写进
`%LOCALAPPDATA%\\VideoDownload\\startup-error.log`，避免无提示静默退出。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def _write_fatal(message: str) -> None:
    """把启动失败信息落盘；GUI 不可用时这是唯一的可见通道。"""
    try:
        from app.config import data_dir

        log_path = Path(data_dir()) / "startup-error.log"
    except Exception:  # noqa: BLE001
        log_path = Path.home() / "VideoDownload-startup-error.log"
    try:
        log_path.write_text(message, encoding="utf-8")
        sys.stderr.write(f"VideoDownload 启动失败，详情见 {log_path}\n{message}\n")
    except Exception:  # noqa: BLE001
        sys.stderr.write(message + "\n")


def main() -> int:
    try:
        from app.ui import run
    except Exception:  # noqa: BLE001
        _write_fatal("无法加载程序模块：\n\n" + traceback.format_exc())
        return 1

    try:
        run()
    except Exception:  # noqa: BLE001
        _write_fatal("程序运行时发生错误：\n\n" + traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
