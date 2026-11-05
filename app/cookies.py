"""把浏览器扩展送来的 cookies 落成 yt-dlp 能读的 Netscape cookies.txt。

背景：Chrome 127+ 对 cookie 启用了 App-Bound Encryption（`v20` 前缀），
yt-dlp 从磁盘读取会直接失败，Edge 也会因为数据库被占用而复制失败。
扩展通过 chrome.cookies API 拿到的是**解密后的明文**，由它转发给本程序，
是当前唯一稳定的取法。

安全约束（这一层是最后一道闸，不能只靠扩展自觉）：
- 只接受白名单站点及其登录所需的相关域，其它域一律丢弃；
- 单条 cookie 总大小、条数都有上限；
- 写入前清洗控制字符，避免破坏文件结构；
- 返回值只报数量，不回传任何 cookie 内容。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

# 支持的视频站点 + 各站点登录态依赖的相关域。
# 必须与 extension/content/pill.js 的 SITE_PATTERNS 保持一致。
ALLOWED_DOMAINS: tuple[str, ...] = (
    "youtube.com",
    "youtu.be",
    "google.com",          # YouTube 登录态的一部分 cookie 在 google.com 下
    "vimeo.com",
    "instagram.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "bilibili.com",
    "stashmedia.tv",
    "tiktok.com",
)

MAX_COOKIES = 3000
MAX_TOTAL_BYTES = 2 * 1024 * 1024
NETSCAPE_HEADER = (
    "# Netscape HTTP Cookie File\n"
    "# 由 VideoDownload 浏览器扩展导出，请勿手工编辑。\n"
)


def _norm(domain: str) -> str:
    return (domain or "").strip().lstrip(".").lower()


def is_allowed_domain(domain: str) -> bool:
    """域名必须等于白名单项或是其子域。"""
    host = _norm(domain)
    if not host:
        return False
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_DOMAINS)


def _clean(value: Any) -> str | None:
    """清洗 cookie 字段：含换行/制表符/空字节会破坏文件结构，直接丢弃该条。"""
    text = "" if value is None else str(value)
    if any(ch in text for ch in ("\n", "\r", "\x00", "\t")):
        return None
    return text


def to_netscape(cookies: Iterable[dict[str, Any]]) -> tuple[str, int, int]:
    """转成 Netscape cookies.txt 文本。

    返回 (文本, 实际写入条数, 丢弃条数)。
    """
    lines: list[str] = []
    written = 0
    skipped = 0
    seen: set[tuple[str, str, str]] = set()

    for raw in cookies:
        if written >= MAX_COOKIES:
            break
        if not isinstance(raw, dict):
            skipped += 1
            continue

        domain = _clean(raw.get("domain")) or ""
        name = _clean(raw.get("name")) or ""
        path = _clean(raw.get("path")) or "/"
        if not domain or not name or not is_allowed_domain(domain):
            skipped += 1
            continue

        value = _clean(raw.get("value"))
        if value is None:
            skipped += 1
            continue

        key = (domain.lower(), name, path)
        if key in seen:
            continue
        seen.add(key)

        # Chrome 用 hostOnly 表示是否包含子域；domain 通常带前导点
        host_only = bool(raw.get("hostOnly", False))
        out_domain = domain if domain.startswith(".") or host_only else "." + domain
        include_sub = "FALSE" if host_only else "TRUE"
        if not path.startswith("/"):
            path = "/"
        secure = "TRUE" if raw.get("secure") else "FALSE"

        expires = raw.get("expirationDate")
        try:
            expires_int = int(float(expires)) if expires else 0
        except (TypeError, ValueError):
            expires_int = 0
        if expires_int <= 0:
            expires_int = 0  # 会话 cookie

        lines.append(
            "\t".join([out_domain, include_sub, path, secure, str(expires_int), name, value])
        )
        written += 1

    text = NETSCAPE_HEADER + "\n".join(lines) + ("\n" if lines else "")
    return text, written, skipped


def save(path: Path, cookies: Iterable[dict[str, Any]]) -> tuple[int, int]:
    """写出 cookies.txt，返回 (写入条数, 丢弃条数)。"""
    text, written, skipped = to_netscape(cookies)
    if not written:
        raise ValueError("没有可写入的 cookies（域名不在白名单内或内容为空）。")

    data = text.encode("utf-8")
    if len(data) > MAX_TOTAL_BYTES:
        raise ValueError("cookies 体积超过上限。")

    path.parent.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再替换，避免中途失败留下半截文件
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    _restrict_permissions(path)
    return written, skipped


def _restrict_permissions(path: Path) -> None:
    """尽量把文件权限收紧到当前用户。Windows 上用 ACL，失败不致命。"""
    try:
        import os
        import subprocess

        user = os.environ.get("USERNAME")
        if not user:
            return
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except Exception:  # noqa: BLE001 - 权限收紧失败不应影响主流程
        pass
