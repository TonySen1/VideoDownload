"""UI 无关的小工具：大小/时长格式化、文件名清洗、设置读写。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import config

_INVALID_WIN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def human_size(num: float | int | None) -> str:
    """字节数转人类可读字符串。"""
    if not num or num <= 0:
        return "未知"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def human_duration(seconds: float | int | None) -> str:
    """秒数转 HH:MM:SS / MM:SS。"""
    if seconds is None:
        return "未知"
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "未知"
    if total < 0:
        return "未知"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def human_speed(bps: float | int | None) -> str:
    if not bps or bps <= 0:
        return "--"
    return f"{human_size(bps)}/s"


def human_eta(seconds: float | int | None) -> str:
    if seconds is None or seconds < 0:
        return "--"
    return human_duration(seconds)


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """清洗为 Windows 合法文件名（yt-dlp 自身也会处理，这里作为兜底）。"""
    cleaned = _INVALID_WIN_CHARS.sub("_", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned.upper() in _RESERVED:
        cleaned = f"_{cleaned}"
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")
    return cleaned or "download"


def ensure_writable_dir(raw: str) -> Path:
    """校验并规范化输出目录：不存在则创建，必须是可写目录。"""
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise OSError(f"不是有效的目录：{path}")
    probe = path / ".videodownload_write_test"
    probe.write_bytes(b"")
    probe.unlink(missing_ok=True)
    return path.resolve()


# ---------------------------------------------------------------- 设置持久化

_DEFAULT_SETTINGS = {
    "save_dir": "",
    "out_format": "自动",
    "last_url": "",
    "cookiefile": "",
}


def load_settings() -> dict:
    path = config.settings_path()
    data = dict(_DEFAULT_SETTINGS)
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update({k: v for k, v in raw.items() if k in _DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    return data


def save_settings(data: dict) -> None:
    path = config.settings_path()
    merged = dict(_DEFAULT_SETTINGS)
    merged.update({k: v for k, v in data.items() if k in _DEFAULT_SETTINGS})
    try:
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
