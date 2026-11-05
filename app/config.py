"""路径与外部依赖（ffmpeg）的定位逻辑。

设计要点：
- 单文件 exe 打包时，资源被解压到 sys._MEIPASS，退出即删除，因此不能把
  临时路径写死，也不能把用户的数据存进 _MEIPASS。
- ffmpeg 的查找优先级：环境变量 > exe 同目录 > exe 同目录 bin/ > 打包解压目录 > PATH。
  这样用户既能用打包内置的 ffmpeg，也能在 exe 旁边放一个新版本覆盖。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "VideoDownload"


def is_frozen() -> bool:
    """是否是 PyInstaller 打包后的运行状态。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """可执行文件所在目录（源码运行时是项目根目录）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """PyInstaller 解包目录；源码运行时等于 app_dir。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return app_dir()


def data_dir() -> Path:
    """存放设置、日志等持久化数据的目录，绝不放在 _MEIPASS。"""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / APP_NAME if base else app_dir() / "data"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        root = app_dir() / "data"
        root.mkdir(parents=True, exist_ok=True)
    return root


def settings_path() -> Path:
    return data_dir() / "settings.json"


def default_cookiefile() -> Path:
    """用户放置 cookies.txt 的默认位置，程序启动时自动探测。"""
    return data_dir() / "cookies.txt"


def find_cookiefile() -> Path | None:
    """按优先级找可用的 cookies 文件：环境变量 > 数据目录 > exe 同目录。"""
    env = os.environ.get("YTDIP_COOKIES")
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()

    for candidate in (default_cookiefile(), app_dir() / "cookies.txt"):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate.resolve()
    return None


def default_download_dir() -> Path:
    """默认保存目录：当前用户的「下载」文件夹，不存在则退回用户主目录。"""
    home = Path.home()
    downloads = home / "Downloads"
    if downloads.is_dir():
        return downloads
    return home


def _as_executable(p: Path) -> Path | None:
    if p.is_file():
        return p
    if p.is_dir():
        candidate = p / "ffmpeg.exe" if os.name == "nt" else p / "ffmpeg"
        if candidate.is_file():
            return candidate
    return None


def find_ffmpeg() -> Path | None:
    """按优先级查找 ffmpeg，返回可执行文件的绝对路径。"""
    candidates: list[Path] = []

    env = os.environ.get("YTDIP_FFMPEG")
    if env:
        candidates.append(Path(env))

    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates.append(app_dir() / name)
    candidates.append(app_dir() / "bin" / name)
    candidates.append(bundle_dir() / name)
    candidates.append(bundle_dir() / "bin" / name)

    for c in candidates:
        found = _as_executable(c)
        if found:
            return found.resolve()

    which = shutil.which("ffmpeg")
    if which:
        return Path(which).resolve()
    return None


def find_ffprobe() -> Path | None:
    """ffprobe 与 ffmpeg 同目录，能找到就用，找不到也不是致命问题。"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    probe = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    return probe if probe.is_file() else None


def ffmpeg_location() -> str | None:
    """传给 yt-dlp 的 ffmpeg_location 参数。"""
    p = find_ffmpeg()
    return str(p) if p else None


# yt-dlp 支持的 JS 运行时名（用于 YouTube 的 JS 挑战求解）
_JS_RUNTIMES = ("deno", "node", "bun", "quickjs")


def find_js_runtime() -> str | None:
    """找一个可用的 JS 运行时。

    yt-dlp 默认只启用 deno，但 Windows 用户机器上更常见的是 Node.js。
    没有运行时时 YouTube 部分格式（含年龄限制视频的全部格式）会缺失。
    """
    env = os.environ.get("YTDIP_JS_RUNTIME")
    if env and shutil.which(env):
        return env

    # exe 同目录优先，方便放一个便携版 node.exe
    for name in _JS_RUNTIMES:
        exe = name + (".exe" if os.name == "nt" else "")
        local = app_dir() / exe
        if local.is_file():
            return name
        if shutil.which(name):
            return name
    return None
