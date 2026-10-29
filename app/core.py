"""核心逻辑：解析、格式选择、下载。完全不依赖任何 GUI。

对外只暴露三个东西：
    Analyzer.parse(url)       -> VideoInfo
    DownloadTask(...).run()   -> DownloadResult
    build_format_selector()   -> yt-dlp 的 format 字符串
所有回调都在工作线程中被调用，UI 层负责切回主线程。
"""

from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yt_dlp
from yt_dlp.utils import DownloadError

from . import config
from .util import human_size, sanitize_filename

# ------------------------------------------------------------------ 常量

AUDIO_FORMATS = ("mp3", "m4a", "wav", "flac")
VIDEO_CONTAINERS = ("自动", "mp4", "mkv", "webm")
BEST_QUALITY = "最佳画质"

_QUALITY_LABELS = {
    144: "144p", 240: "240p", 360: "360p", 480: "480p",
    540: "540p", 576: "576p", 720: "720p", 1080: "1080p",
    1440: "2K", 2160: "4K", 4320: "8K",
}
# 这些高度在标签里额外标注像素值，如 "4K (2160p)"
_ANNOTATE_HEIGHTS = {1440, 2160, 4320}


def _quality_label(height: int) -> str:
    known = _QUALITY_LABELS.get(height)
    if known is None:
        return f"{height}p"
    if height in _ANNOTATE_HEIGHTS:
        return f"{known} ({height}p)"
    return known


class Cancelled(Exception):
    """用户主动取消。"""


# ------------------------------------------------------------------ 数据模型

@dataclass
class QualityOption:
    label: str
    height: int | None          # None 表示「最佳画质」
    approx_size: int | None     # 估算字节数（视频+音频）
    is_best: bool = False

    @property
    def size_text(self) -> str:
        return f"约 {human_size(self.approx_size)}" if self.approx_size else "大小未知"


@dataclass
class VideoInfo:
    url: str
    title: str
    duration: float | None = None
    thumbnail: str | None = None
    uploader: str | None = None
    webpage_url: str | None = None
    qualities: list[QualityOption] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    has_audio_only: bool = False

    @property
    def effective_title(self) -> str:
        return self.title or "未命名视频"


@dataclass
class ProgressEvent:
    status: str                  # preparing / downloading / merging / finished
    percent: float = 0.0
    speed: float | None = None
    eta: float | None = None
    downloaded: int | None = None
    total: int | None = None
    stage_text: str = ""


@dataclass
class DownloadResult:
    ok: bool
    filepath: Path | None = None
    error: str | None = None
    cancelled: bool = False


# ------------------------------------------------------------------ 错误友好化

_FRIENDLY_ERRORS: list[tuple[tuple[str, ...], str]] = [
    (("unsupported url", "is not a valid url"), "链接无效或该网站不受支持，请检查链接是否正确。"),
    (("video unavailable", "has been removed"), "视频不存在或已被删除。"),
    (("private video", "this video is private"), "该视频是私密的，无法下载。"),
    (("members-only", "join to confirm"), "该视频仅会员可见，无法下载。"),
    (("sign in", "confirm your age", "login required"), "该视频需要登录或年龄验证，无法直接下载。"),
    (("http error 403", "forbidden"), "服务器拒绝访问（403），可能需要登录或链接已失效。"),
    (("http error 404", "not found"), "资源不存在（404），请检查链接。"),
    (("http error 429", "too many requests"), "请求过于频繁（429），请稍后再试。"),
    (("timed out", "timeout"), "网络连接超时，请检查网络或代理设置。"),
    (("getaddrinfo", "name or service not known", "nodename"), "无法解析域名，请检查网络连接。"),
    (("proxy",), "代理服务器连接失败，请检查代理设置。"),
    (("ffmpeg", "postprocessing", "post-processor"), "音视频合并/转码失败，请确认 ffmpeg 可用且文件未损坏。"),
    (("no space left",), "磁盘空间不足，请清理后重试。"),
    (("permission denied", "access is denied"), "没有写入权限，请更换保存目录。"),
    (("requested format is not available",), "所选清晰度/格式不可用，请重新解析后再选择。"),
]


def friendly_error(raw: Any) -> str:
    """把 yt-dlp 原始的英文报错转成能看懂的中文提示。"""
    text = str(raw or "").strip()
    lowered = text.lower()
    for keys, message in _FRIENDLY_ERRORS:
        if any(k in lowered for k in keys):
            return message
    # 去掉 yt-dlp 的 ERROR: 前缀和冗长堆栈
    cleaned = text.replace("ERROR:", "").strip()
    first_line = cleaned.splitlines()[0] if cleaned else ""
    if len(first_line) > 300:
        first_line = first_line[:300] + "…"
    return f"操作失败：{first_line}" if first_line else "操作失败，原因未知。"


def normalize_url(raw: str) -> str:
    """从粘贴内容中提取链接；顺手去掉常见播放列表参数问题。"""
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("请输入视频链接。")
    if "://" not in text:
        # 允许用户粘贴 "www.bilibili.com/video/xxx" 这种
        if text.lower().startswith(("www.", "m.")):
            text = "https://" + text
        else:
            raise ValueError("这不是一个有效的链接，请以 http:// 或 https:// 开头。")
    if not text.lower().startswith(("http://", "https://")):
        raise ValueError("仅支持 http/https 链接。")
    return text


# ------------------------------------------------------------------ 格式选择

def _video_formats(info: dict) -> list[dict]:
    return [
        f for f in (info.get("formats") or [])
        if f.get("vcodec") not in (None, "none") and f.get("height")
    ]


def _audio_formats(info: dict) -> list[dict]:
    return [
        f for f in (info.get("formats") or [])
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
    ]


def _format_size(f: dict, duration: float | None = None) -> int | None:
    """单个格式的体积估计：精确值 > 近似值 > 码率×时长。"""
    size = f.get("filesize")
    if size:
        return int(size)
    size = f.get("filesize_approx")
    if size:
        return int(size)
    content_length = f.get("filesize_approx") or f.get("contentLength")
    if content_length:
        return int(content_length)
    tbr = f.get("tbr") or f.get("vbr") or f.get("abr")
    dur = duration or f.get("duration")
    if tbr and dur:
        return int(float(tbr) * 1000 / 8 * float(dur))
    return None


def _pick_size(formats: list[dict], duration: float | None = None) -> int | None:
    """从一组格式里取一个尽可能可靠的体积估计（取最大者，偏保守）。"""
    sizes = [s for s in (_format_size(f, duration) for f in formats) if s]
    return max(sizes) if sizes else None


def build_quality_list(info: dict) -> list[QualityOption]:
    """按高度聚合可选清晰度，从高到低排列。"""
    videos = _video_formats(info)
    audios = _audio_formats(info)
    duration = info.get("duration")
    best_audio_size = _pick_size(audios, duration) or 0

    by_height: dict[int, list[dict]] = {}
    for f in videos:
        by_height.setdefault(int(f["height"]), []).append(f)

    options: list[QualityOption] = []
    for height in sorted(by_height, reverse=True):
        video_size = _pick_size(by_height[height], duration)
        total = (video_size + best_audio_size) if video_size else None
        options.append(
            QualityOption(
                label=_quality_label(height),
                height=height,
                approx_size=total,
                is_best=(height == max(by_height)),
            )
        )

    if not options:
        # 只有合并格式（progressive）时也能给出一档
        options.append(
            QualityOption(
                label="最佳画质（无法细分）",
                height=None,
                approx_size=_pick_size(info.get("formats") or []),
                is_best=True,
            )
        )
    return options


def build_format_selector(height: int | None, container: str) -> str:
    """构造 yt-dlp 的 -f 字符串。

    优先级思路：
    1. 同高度 + 目标容器原生编码（尽量不重新封装）；
    2. 同高度但排除 AV1 —— 很多用户机器上的 ffmpeg 偏旧，封装 AV1 会失败，
       而 VP9/H.264 几乎总能进 mp4；
    3. 同高度任意编码（含 AV1）；
    4. 不超过该高度；
    5. best。
    """
    if height is None:
        cap = ""
        cap_best = ""
    else:
        cap = f"[height={height}]"
        cap_best = f"[height<={height}]"
    no_av1 = f"{cap}[vcodec!*=av01]" if cap else "[vcodec!*=av01]"

    def join(parts: list[str]) -> str:
        return "/".join(p for p in parts if p)

    if container == "mp4":
        return join([
            f"bestvideo{cap}[ext=mp4][vcodec!*=av01]+bestaudio[ext=m4a]",
            f"bestvideo{no_av1}+bestaudio[ext=m4a]",
            f"best{cap}[ext=mp4]",
            f"bestvideo{cap}+bestaudio",
            f"best{cap}",
            f"bestvideo{cap_best}+bestaudio",
            f"best{cap_best}",
            "best",
        ])
    if container == "webm":
        return join([
            f"bestvideo{cap}[ext=webm]+bestaudio[ext=webm]",
            f"best{cap}[ext=webm]",
            f"bestvideo{cap}+bestaudio",
            f"best{cap}",
            "best",
        ])
    if container == "mkv":
        # MKV 包容性最强，不用排除 AV1
        return join([
            f"bestvideo{cap}+bestaudio",
            f"best{cap}",
            "best",
        ])
    # 自动（不限容器）：优先非 AV1
    return join([
        f"bestvideo{no_av1}+bestaudio",
        f"best{cap}",
        f"bestvideo{cap}+bestaudio",
        f"best{cap_best}",
        f"bestvideo{cap_best}+bestaudio",
        f"best{cap_best}",
        "bestvideo+bestaudio",
        "best",
    ])


# ------------------------------------------------------------------ 解析

class Analyzer:
    """封装 yt-dlp 的「只解析不下载」流程。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def _base_opts(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 20,
            "retries": 2,
            "extract_flat": False,
            "cachedir": False,
            "nocheckcertificate": False,
        }
        ffmpeg = config.ffmpeg_location()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        return opts

    def parse(self, raw_url: str) -> VideoInfo:
        url = normalize_url(raw_url)
        self._cancel.clear()
        try:
            with yt_dlp.YoutubeDL(self._base_opts()) as ydl:
                info = ydl.extract_info(url, download=False)
        except DownloadError as exc:
            raise RuntimeError(friendly_error(exc)) from exc
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        if not info:
            raise RuntimeError("解析失败：没有返回任何视频信息。")

        # 播放列表/合集：取第一个条目提示用户
        if info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                raise RuntimeError("该链接是空播放列表。")
            info = entries[0]

        qualities = build_quality_list(info)
        return VideoInfo(
            url=url,
            title=info.get("title") or "未命名视频",
            duration=info.get("duration"),
            thumbnail=info.get("thumbnail"),
            uploader=info.get("uploader") or info.get("channel"),
            webpage_url=info.get("webpage_url") or url,
            qualities=qualities,
            raw=info,
            has_audio_only=True,
        )


# ------------------------------------------------------------------ 下载

class DownloadTask:
    """一次下载任务。必须是「一次性」对象，下完即弃。"""

    def __init__(
        self,
        url: str,
        save_dir: str | Path,
        quality: QualityOption | None,
        out_format: str,
        expected_title: str = "",
        on_progress: Callable[[ProgressEvent], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.url = normalize_url(url)
        self.save_dir = Path(save_dir)
        self.quality = quality
        self.out_format = out_format
        self.expected_title = expected_title
        self.on_progress = on_progress or (lambda e: None)
        self.on_log = on_log or (lambda m: None)

        self._cancel = threading.Event()
        self._segment_done = 0
        self._segment_total = 0
        self._max_percent = 0.0
        self._counted: set[int] = set()
        self._pp_reported: set[str] = set()
        self._lock = threading.Lock()

    # -------------------------------------------------- 控制
    def cancel(self) -> None:
        self._cancel.set()

    @property
    def is_audio(self) -> bool:
        return self.out_format in AUDIO_FORMATS

    # -------------------------------------------------- 进度换算
    def _compute_totals(self, info: dict) -> None:
        """合并下载时，先算出所有分片的总体积，才有准确的总进度。"""
        formats = info.get("requested_formats") or [info]
        total = 0
        for f in formats:
            size = f.get("filesize") or f.get("filesize_approx")
            if size:
                total += int(size)
        with self._lock:
            self._segment_total = total
            self._segment_done = 0

    def _progress_hook(self, d: dict) -> None:
        if self._cancel.is_set():
            raise Cancelled()

        status = d.get("status")
        if status == "downloading":
            downloaded = int(d.get("downloaded_bytes") or 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            with self._lock:
                seg_total = self._segment_total
                seg_done = self._segment_done

            overall_total = seg_total if seg_total else (int(total) if total else 0)
            overall_done = seg_done + downloaded
            percent = (overall_done / overall_total * 100) if overall_total else 0.0

            stage = "正在下载"
            if d.get("info_dict", {}).get("vcodec") == "none":
                stage = "正在下载音频"
            self._emit_download_progress(
                percent, d.get("speed"), d.get("eta"), overall_done, overall_total or None, stage
            )
        elif status == "finished":
            # 每个分片（视频轨/音频轨）结束时会各来一次，用 info_dict 的
            # 对象身份去重，避免同一个分片被重复计入总进度。
            key = id(d.get("info_dict"))
            downloaded = int(d.get("downloaded_bytes") or 0)
            with self._lock:
                if key in self._counted:
                    downloaded = 0
                else:
                    self._counted.add(key)
                self._segment_done += downloaded
                seg_total = self._segment_total
                seg_done = self._segment_done
            if seg_total and seg_done < seg_total:
                # 还有分片没下完，不要虚报 100%
                self._emit_download_progress(
                    seg_done / seg_total * 100, None, None, seg_done, seg_total, "分片下载完成"
                )

    def _emit_download_progress(
        self,
        percent: float,
        speed: float | None,
        eta: float | None,
        downloaded: int | None,
        total: int | None,
        stage: str,
    ) -> None:
        """单调递增地发进度，避免多分片切换时百分比跳回。"""
        clamped = max(0.0, min(percent, 99.5))
        with self._lock:
            if clamped < self._max_percent:
                clamped = self._max_percent
            else:
                self._max_percent = clamped
        self.on_progress(
            ProgressEvent(
                status="downloading",
                percent=clamped,
                speed=speed if speed and speed > 0 else None,
                eta=eta if eta is not None and eta >= 0 else None,
                downloaded=downloaded,
                total=total,
                stage_text=stage,
            )
        )

    def _postprocessor_hook(self, d: dict) -> None:
        if self._cancel.is_set():
            raise Cancelled()
        if d.get("status") != "started":
            return
        pp = d.get("postprocessor", "") or ""
        label = {
            "Merger": "正在合并音视频…",
            "FFmpegExtractAudio": "正在转换音频格式…",
            "FFmpegVideoConvertor": "正在转换视频格式…",
            "FFmpegVideoRemuxer": "正在重新封装…",
            "MoveFiles": "正在整理文件…",
        }.get(pp, f"正在后处理（{pp}）…")
        with self._lock:
            if pp in self._pp_reported:
                return
            self._pp_reported.add(pp)
        self.on_log(label)
        self.on_progress(ProgressEvent(status="merging", stage_text=label))

    def _ydl_opts(self, force_container: str | None = None) -> dict[str, Any]:
        out_dir = self.save_dir
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "overwrites": True,
            "continuedl": True,
            "windowsfilenames": True,     # 直接产出 Windows 合法文件名（中文保留）
            "trim_file_name": 120,
            "restrictfilenames": False,
            "paths": {"home": str(out_dir)},
            # %(title).120B 按字节截断，避免中文标题过长导致路径超限
            "outtmpl": {"default": "%(title).120B [%(id)s].%(ext)s"},
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 4,
            "ignoreerrors": False,
            "logger": _NullLogger(),
        }

        ffmpeg = config.ffmpeg_location()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg

        if self.is_audio:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.out_format,
                    "preferredquality": "0" if self.out_format == "mp3" else "192",
                    "nopostoverwrites": False,
                }
            ]
        else:
            container = force_container or self.out_format
            height = self.quality.height if self.quality else None
            if force_container:
                # 回退重试：容器已定死，格式选择也要跟着放宽
                opts["format"] = build_format_selector(height, force_container)
            else:
                opts["format"] = build_format_selector(height, container)
            if container in ("mp4", "mkv", "webm"):
                opts["merge_output_format"] = container
        return opts

    # -------------------------------------------------- 执行
    def run(self) -> DownloadResult:
        try:
            self.save_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return DownloadResult(ok=False, error=f"无法创建保存目录：{exc}")

        self.on_progress(ProgressEvent(status="preparing", stage_text="正在准备下载…"))

        try:
            final_path = self._download_once()
        except Cancelled:
            return DownloadResult(ok=False, cancelled=True, error="已取消下载。")
        except DownloadError as exc:
            if self._cancel.is_set():
                return DownloadResult(ok=False, cancelled=True, error="已取消下载。")
            if self._should_fallback_to_mkv(exc):
                self.on_log("当前 ffmpeg 无法封装该编码，自动改用 MKV 容器重试…")
                try:
                    final_path = self._download_once(force_container="mkv")
                except Cancelled:
                    return DownloadResult(ok=False, cancelled=True, error="已取消下载。")
                except Exception as exc2:  # noqa: BLE001
                    if self._cancel.is_set():
                        return DownloadResult(ok=False, cancelled=True, error="已取消下载。")
                    return DownloadResult(ok=False, error=friendly_error(exc2))
            else:
                return DownloadResult(ok=False, error=friendly_error(exc))
        except Exception as exc:  # noqa: BLE001 - 兜底，保证 UI 不崩
            if self._cancel.is_set():
                return DownloadResult(ok=False, cancelled=True, error="已取消下载。")
            return DownloadResult(ok=False, error=friendly_error(exc))

        self.on_progress(ProgressEvent(status="finished", percent=100.0, stage_text="下载完成"))
        return DownloadResult(ok=True, filepath=final_path)

    def _should_fallback_to_mkv(self, exc: Exception) -> bool:
        """mp4/webm 封装失败时（常见于 AV1 + 老 ffmpeg），MKV 几乎总能装下。"""
        if self.is_audio:
            return False
        if self.out_format not in ("mp4", "webm", "自动"):
            return False
        if self._cancel.is_set():
            return False
        text = str(exc).lower()
        markers = (
            "conversion failed",
            "postprocessing",
            "incorrect codec parameters",
            "could not write header",
            "experimental feature",
            "only vp8 or vp9",
            "invalid argument",
        )
        return any(m in text for m in markers)

    def _download_once(self, force_container: str | None = None) -> Path | None:
        opts = self._ydl_opts(force_container)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(self.url, download=False)
            if info.get("_type") == "playlist":
                entries = [e for e in (info.get("entries") or []) if e]
                if not entries:
                    raise RuntimeError("该链接是空播放列表。")
                info = entries[0]
            self._compute_totals(info)
            ydl.process_ie_result(info, download=True)
            return self._resolve_output_path(info, ydl)

    def _resolve_output_path(self, info: dict, ydl: yt_dlp.YoutubeDL) -> Path | None:
        """根据 yt-dlp 的最终文件名，反推磁盘上真实存在的文件。"""
        try:
            filename = ydl.prepare_filename(info)
        except Exception:  # noqa: BLE001
            filename = ""
        base = Path(filename)
        target_dir = base.parent if str(base.parent) not in ("", ".") else self.save_dir

        # 音频后处理改了扩展名
        if self.is_audio:
            ext = _audio_ext(self.out_format)
            candidate = base.with_suffix(f".{ext}")
            if candidate.is_file():
                return candidate
            matches = sorted(
                target_dir.glob(f"{base.stem}.*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if matches:
                return matches[0]

        if base.is_file():
            return base
        # 合并后扩展名可能变
        matches = sorted(
            target_dir.glob(f"{base.stem}.*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return matches[0] if matches else None


def _audio_ext(codec: str) -> str:
    return {"m4a": "m4a", "mp3": "mp3", "wav": "wav", "flac": "flac"}.get(codec, codec)


class _NullLogger:
    """吞掉 yt-dlp 的调试输出，避免污染控制台。"""

    def debug(self, msg: str) -> None:  # noqa: D102
        pass

    def info(self, msg: str) -> None:  # noqa: D102
        pass

    def warning(self, msg: str) -> None:  # noqa: D102
        pass

    def error(self, msg: str) -> None:  # noqa: D102
        pass


def check_environment() -> dict[str, Any]:
    """启动时自检：ffmpeg 是否就位。返回给 UI 展示。"""
    ffmpeg = config.find_ffmpeg()
    return {
        "ffmpeg": str(ffmpeg) if ffmpeg else None,
        "ffmpeg_ok": ffmpeg is not None,
        "yt_dlp_version": getattr(yt_dlp.version, "__version__", "unknown"),
        "save_dir": str(config.default_download_dir()),
    }


def suggest_filename(title: str) -> str:
    return sanitize_filename(title)


def path_is_inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (ValueError, OSError):
        return False


def open_folder(folder: Path) -> None:
    """在资源管理器中打开目录。"""
    target = Path(folder)
    if not target.is_dir():
        raise FileNotFoundError(f"目录不存在：{target}")
    os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606


def open_in_explorer(path: Path | None) -> None:
    """在资源管理器中定位并选中文件；没有文件时打开其所在目录。"""
    if not path:
        return
    target = Path(path)
    if target.is_file():
        # /select 需要反斜杠路径
        subprocess.Popen(["explorer", "/select,", str(target)])  # noqa: S603,S607
        return
    if target.is_dir():
        open_folder(target)
