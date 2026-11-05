"""tkinter 界面层。只负责显示与交互，所有耗时工作交给 app.core。"""

from __future__ import annotations

import io
import queue
import threading
import time
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from . import APP_NAME, __version__, config, cookies as cookie_util
from .bridge import BridgeServer
from .core import (
    AUDIO_FORMATS,
    BEST_QUALITY,
    VIDEO_CONTAINERS,
    Analyzer,
    DownloadResult,
    DownloadTask,
    ProgressEvent,
    VideoInfo,
    check_environment,
    open_folder,
    open_in_explorer,
)
from .util import (
    ensure_writable_dir,
    human_duration,
    human_eta,
    human_size,
    human_speed,
    load_settings,
    save_settings,
)

BG = "#f5f6f8"
CARD = "#ffffff"
ACCENT = "#2563eb"
OK_COLOR = "#15803d"
WARN_COLOR = "#b45309"
ERR_COLOR = "#b91c1c"
MUTED = "#6b7280"

FONT = ("Microsoft YaHei UI", 9)
FONT_BOLD = ("Microsoft YaHei UI", 9, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 11, "bold")


class VideoDownloadApp:
    """主窗口。"""

    POLL_MS = 80
    THUMB_SIZE = (160, 90)

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        self.settings = load_settings()
        self.info: VideoInfo | None = None
        self.analyzer: Analyzer | None = None
        self.task: DownloadTask | None = None
        self.busy = False           # 解析或下载进行中
        self.last_file: Path | None = None
        self._thumb_image: Any = None
        self._quality_options: list[Any] = []
        self.bridge: BridgeServer | None = None
        self._pending_bridge_url: str | None = None
        self._bridge_lock = threading.Lock()

        self._build_ui()
        self._load_env_async()
        self._start_bridge()
        self._poll()

    # ------------------------------------------------------------ 构建界面
    def _build_ui(self) -> None:
        self.root.title(f"{APP_NAME} v{__version__} — 视频下载器")
        self._apply_window_icon()
        self.root.geometry("880x720")
        self.root.minsize(780, 660)
        self.root.configure(bg=BG)

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure(".", font=FONT, background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, font=FONT)
        style.configure("Card.TLabel", background=CARD, font=FONT)
        style.configure("Title.TLabel", background=CARD, font=FONT_TITLE)
        style.configure("Dim.TLabel", background=CARD, font=FONT, foreground=MUTED)
        style.configure("Accent.TButton", font=FONT_BOLD)
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, font=FONT_BOLD)

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        # ---------------- 链接输入
        url_card = ttk.Frame(outer, style="Card.TFrame", padding=12)
        url_card.grid(row=0, column=0, sticky="ew")
        url_card.columnconfigure(1, weight=1)

        ttk.Label(url_card, text="视频链接", style="Card.TLabel", font=FONT_BOLD).grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self.url_var = tk.StringVar(value=self.settings.get("last_url", ""))
        self.url_entry = ttk.Entry(url_card, textvariable=self.url_var, font=FONT)
        self.url_entry.grid(row=0, column=1, sticky="ew", ipady=3)
        self.url_entry.bind("<Return>", lambda _e: self.on_parse())

        self.paste_btn = ttk.Button(url_card, text="粘贴", width=7, command=self.on_paste)
        self.paste_btn.grid(row=0, column=2, padx=(6, 0))
        self.parse_btn = ttk.Button(
            url_card, text="解析", width=9, style="Accent.TButton", command=self.on_parse
        )
        self.parse_btn.grid(row=0, column=3, padx=(6, 0))

        # ---------------- 视频信息
        info_card = ttk.Frame(outer, style="Card.TFrame", padding=12)
        info_card.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        info_card.columnconfigure(1, weight=1)

        self.thumb_label = tk.Label(
            info_card,
            text="缩略图",
            bg="#e5e7eb",
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
            width=20,
            height=5,
        )
        self.thumb_label.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 12))

        self.title_label = ttk.Label(
            info_card, text="尚未解析", style="Title.TLabel", wraplength=580, justify="left"
        )
        self.title_label.grid(row=0, column=1, sticky="w")
        self.meta_label = ttk.Label(info_card, text="", style="Dim.TLabel")
        self.meta_label.grid(row=1, column=1, sticky="w", pady=(6, 0))
        self.uploader_label = ttk.Label(info_card, text="", style="Dim.TLabel")
        self.uploader_label.grid(row=2, column=1, sticky="w", pady=(2, 0))

        # ---------------- 选项
        opt = ttk.LabelFrame(outer, text=" 下载选项 ", padding=12)
        opt.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        opt.columnconfigure(1, weight=1)
        opt.columnconfigure(3, weight=1)

        ttk.Label(opt, text="清晰度：").grid(row=0, column=0, sticky="w")
        self.quality_combo = ttk.Combobox(opt, state="readonly", font=FONT, width=26)
        self.quality_combo.grid(row=0, column=1, sticky="ew", padx=(0, 16), ipady=2)

        ttk.Label(opt, text="输出格式：").grid(row=0, column=2, sticky="w")
        self.format_combo = ttk.Combobox(
            opt, state="readonly", font=FONT, width=18,
            values=[*VIDEO_CONTAINERS, *AUDIO_FORMATS],
        )
        saved_fmt = self.settings.get("out_format", "自动")
        self.format_combo.set(saved_fmt if saved_fmt in (*VIDEO_CONTAINERS, *AUDIO_FORMATS) else "自动")
        self.format_combo.grid(row=0, column=3, sticky="ew", ipady=2)
        self.format_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_quality_state())

        ttk.Label(opt, text="保存目录：").grid(row=1, column=0, sticky="w", pady=(10, 0))
        default_dir = self.settings.get("save_dir") or str(config.default_download_dir())
        self.dir_var = tk.StringVar(value=default_dir)
        self.dir_entry = ttk.Entry(opt, textvariable=self.dir_var, font=FONT)
        self.dir_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=(10, 0), ipady=2)
        ttk.Button(opt, text="浏览…", width=8, command=self.on_browse).grid(
            row=1, column=3, sticky="ew", pady=(10, 0)
        )

        # ---------------- cookies（年龄限制 / 需登录的视频）
        ttk.Label(opt, text="cookies 文件：").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.cookies_var = tk.StringVar(value=self.settings.get("cookiefile", ""))
        self.cookies_entry = ttk.Entry(opt, textvariable=self.cookies_var, font=FONT)
        self.cookies_entry.grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=(10, 0), ipady=2
        )
        self.cookies_btn = ttk.Button(
            opt, text="选择…", width=8, command=self.on_pick_cookies
        )
        self.cookies_btn.grid(row=2, column=3, sticky="ew", pady=(10, 0))
        ttk.Label(
            opt,
            text="可选。遇到年龄限制 / 需登录的视频时，选择浏览器导出的 cookies.txt。",
            style="Card.TLabel",
            foreground=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # ---------------- 下载按钮
        action = ttk.Frame(outer)
        action.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        action.columnconfigure(2, weight=1)

        self.download_btn = ttk.Button(
            action, text="开始下载", width=14, style="Accent.TButton",
            state="disabled", command=self.on_download,
        )
        self.download_btn.grid(row=0, column=0)
        self.cancel_btn = ttk.Button(
            action, text="取消", width=8, state="disabled", command=self.on_cancel
        )
        self.cancel_btn.grid(row=0, column=1, padx=(8, 0))
        self.open_btn = ttk.Button(
            action, text="打开文件夹", width=12, state="disabled", command=self.on_open_folder
        )
        self.open_btn.grid(row=0, column=3, sticky="e")

        # ---------------- 进度
        prog_frame = ttk.Frame(outer)
        prog_frame.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        prog_frame.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(prog_frame, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.status_label = ttk.Label(outer, text="就绪", foreground=MUTED)
        self.status_label.grid(row=5, column=0, sticky="w", pady=(6, 0))

        # ---------------- 日志
        log_frame = ttk.LabelFrame(outer, text=" 日志 ", padding=8)
        log_frame.grid(row=6, column=0, sticky="nsew", pady=(10, 0))
        outer.rowconfigure(6, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame, height=8, wrap="word", font=("Consolas", 9),
            bg="#111827", fg="#d1d5db", insertbackground="#d1d5db",
            relief="flat", padx=8, pady=6, state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

        # ---------------- 状态栏
        self.env_label = ttk.Label(
            self.root, text="正在检查 ffmpeg…", foreground=MUTED, anchor="w",
            padding=(14, 4),
        )
        self.env_label.pack(fill="x", side="bottom")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._sync_quality_state()
        self._log(f"{APP_NAME} v{__version__} 已启动")

    def _apply_window_icon(self) -> None:
        """标题栏 / 任务栏图标。找不到 ico 就静默跳过（不影响功能）。"""
        for base in (config.bundle_dir(), config.app_dir()):
            icon = base / "assets" / "videodownload.ico"
            if icon.is_file():
                try:
                    self.root.iconbitmap(default=str(icon))
                    return
                except tk.TclError:
                    continue
        # 退路：用 PhotoImage 取多帧 ico 的第一帧
        try:
            icon = config.bundle_dir() / "assets" / "videodownload.ico"
            if icon.is_file():
                self._icon_photo = tk.PhotoImage(file=str(icon))
                self.root.iconphoto(True, self._icon_photo)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 环境自检
    def _load_env_async(self) -> None:
        def work() -> None:
            try:
                env = check_environment()
            except Exception as exc:  # noqa: BLE001
                env = {"ffmpeg_ok": False, "ffmpeg": None, "error": str(exc)}
            self.events.put(("env", env))

        threading.Thread(target=work, daemon=True).start()

    def _apply_env(self, env: dict) -> None:
        port = f"127.0.0.1:{self.bridge.port}" if self.bridge else "未开启"
        suffix = f"　|　扩展桥接 {port}"
        if env.get("cookies_ok"):
            suffix += "　|　cookies 已加载"
        # 设置里保存的文件优先展示
        configured = self.settings.get("cookiefile", "")
        if configured and Path(configured).is_file():
            self.cookies_var.set(configured)
        if env.get("ffmpeg_ok"):
            self.env_label.configure(
                text=f"✓ ffmpeg 已就绪：{env.get('ffmpeg')}　|　yt-dlp {env.get('yt_dlp_version')}{suffix}",
                foreground=OK_COLOR,
            )
            self._log(f"ffmpeg: {env.get('ffmpeg')}")
        else:
            self.env_label.configure(
                text="⚠ 未找到 ffmpeg：仅能下载单文件格式，无法合并音视频或转码。"
                     f"请把 ffmpeg.exe 放到程序同目录后重启。{suffix}",
                foreground=WARN_COLOR,
            )
            self._log("未检测到 ffmpeg，音视频合并与音频转换将不可用。")

    # ------------------------------------------------------------ 浏览器扩展桥接
    def _start_bridge(self) -> None:
        """启动本机桥接服务，供浏览器扩展把链接投递进来。"""
        bridge = BridgeServer(
            on_submit=self._on_bridge_submit,
            settings=lambda: {"show_pill": True},
            app_version=__version__,
            on_cookies=self._on_bridge_cookies,
        )
        if bridge.start():
            self.bridge = bridge
            self._log(f"浏览器扩展桥接已开启：http://127.0.0.1:{bridge.port}")
        else:
            self.bridge = None
            reason = bridge.last_error or "端口被占用"
            self._log(f"⚠ 浏览器扩展桥接未能启动（{reason}），扩展功能不可用。")
            self._set_status(
                "⚠ 浏览器扩展桥接端口被占用，扩展暂时无法连接", WARN_COLOR
            )

    def _on_bridge_submit(self, url: str, title: str, raw: dict[str, Any]) -> tuple[bool, str]:
        """工作线程回调：只做校验与入队，UI 操作交给主线程。"""
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return False, "只支持 http/https 链接"
        # 同一时刻只保留一个待处理链接，避免连点挤爆队列。
        # 多个 HTTP 线程可能并发进来，必须加锁。
        with self._bridge_lock:
            if self._pending_bridge_url:
                return True, ""
            self._pending_bridge_url = url
        self.events.put(("bridge", {"url": url, "title": title}))
        return True, ""

    def _on_bridge_cookies(self, cookies: list, raw: dict) -> tuple[bool, str]:
        """扩展送来的 cookies：白名单过滤后写入数据目录，并立即生效。"""
        target = config.default_cookiefile()
        try:
            written, skipped = cookie_util.save(target, cookies)
        except ValueError as exc:
            return False, str(exc)
        except OSError as exc:
            return False, f"写入 cookies 失败：{exc}"

        self.events.put(("cookies", {"path": str(target), "written": written, "skipped": skipped}))
        msg = f"已接收 {written} 条 cookies"
        if skipped:
            msg += f"（忽略 {skipped} 条非白名单/异常项）"
        return True, msg

    def _on_cookies_saved(self, payload: dict) -> None:
        path = payload.get("path") or ""
        written = payload.get("written", 0)
        skipped = payload.get("skipped", 0)

        self.settings["cookiefile"] = path
        save_settings(self.settings)
        self.cookies_var.set(path)

        self._log(f"✓ 浏览器扩展已同步 cookies：{written} 条 → {path}")
        if skipped:
            self._log(f"    其中 {skipped} 条因域名不在白名单或内容异常被忽略。")
        self._set_status(
            f"✓ 已接收 {written} 条 cookies，现在可以下载需要登录的视频了。", OK_COLOR
        )

    def _on_bridge_request(self, payload: dict) -> None:
        url = payload.get("url") or ""
        title = payload.get("title") or ""
        with self._bridge_lock:
            self._pending_bridge_url = None
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass
        self.url_var.set(url)
        self._log(f"来自浏览器扩展：{title or url}")
        if self.busy:
            self._log("当前任务进行中，链接已填入，完成后可手动点击「解析」。")
            self._set_status("已接收浏览器链接，请等待当前任务结束。", WARN_COLOR)
            return
        self.on_parse()

    # ------------------------------------------------------------ 事件循环
    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        self.root.after(self.POLL_MS, self._poll)

    def _handle_event(self, kind: str, payload: Any) -> None:
        if kind == "env":
            self._apply_env(payload)
        elif kind == "info":
            self._on_parse_done(payload)
        elif kind == "parse_error":
            self._on_parse_error(payload)
        elif kind == "progress":
            self._on_progress(payload)
        elif kind == "log":
            self._log(payload)
        elif kind == "done":
            self._on_download_done(payload)
        elif kind == "thumb":
            self._set_thumbnail(payload)
        elif kind == "bridge":
            self._on_bridge_request(payload)
        elif kind == "cookies":
            self._on_cookies_saved(payload)

    # ------------------------------------------------------------ 日志/状态
    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_status(self, text: str, color: str = MUTED) -> None:
        self.status_label.configure(text=text, foreground=color)

    def _notify(self, message: str, color: str = WARN_COLOR, icon: str = "⚠") -> None:
        """无弹窗提示：状态行变色 + 日志留痕。所有校验/错误都走这里。"""
        self._set_status(f"{icon} {message}".strip(), color)
        self._log(f"{icon} {message}".strip())

    def _set_progress_indeterminate(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="indeterminate", maximum=100)
        self.progress.start(15)

    def _set_progress_value(self, percent: float) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=max(0.0, min(percent, 100.0)))

    def _reset_progress(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=0)

    # ------------------------------------------------------------ 交互
    def on_paste(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self._log("剪贴板为空或不是文本。")
            return
        self.url_var.set(text.strip())
        self._log("已从剪贴板粘贴链接。")

    def on_browse(self) -> None:
        initial = self.dir_var.get() or str(config.default_download_dir())
        chosen = filedialog.askdirectory(title="选择保存目录", initialdir=initial)
        if chosen:
            self.dir_var.set(chosen)

    def on_pick_cookies(self) -> None:
        current = self.cookies_var.get().strip()
        initial_dir = str(Path(current).parent) if current and Path(current).is_file() else str(Path.home())
        chosen = filedialog.askopenfilename(
            title="选择 cookies.txt",
            initialdir=initial_dir,
            filetypes=[("Cookies 文件", "*.txt"), ("所有文件", "*.*")],
        )
        if chosen:
            self.cookies_var.set(chosen)
            self.settings["cookiefile"] = chosen
            save_settings(self.settings)
            self._log(f"已选择 cookies 文件：{chosen}")

    def _cookiefile(self) -> str | None:
        """返回当前可用的 cookies 路径；没填或文件不存在则返回 None。"""
        raw = self.cookies_var.get().strip()
        if raw and Path(raw).is_file():
            return raw
        if raw and not Path(raw).is_file():
            self._log(f"⚠ cookies 文件不存在，已忽略：{raw}")
        return config.find_cookiefile()

    def _sync_quality_state(self) -> None:
        """选了音频格式时，清晰度无意义，禁用下拉。"""
        fmt = self.format_combo.get()
        is_audio = fmt in AUDIO_FORMATS
        if is_audio:
            self.quality_combo.configure(state="disabled")
            self.quality_combo.set("不适用（纯音频）")
        else:
            if self._quality_options:
                self.quality_combo.configure(state="readonly")
                if not self.quality_combo.get():
                    self.quality_combo.set(self._quality_options[0].label)
            else:
                self.quality_combo.configure(state="disabled")
                self.quality_combo.set("请先解析")

    def _set_busy(self, busy: bool, mode: str = "") -> None:
        self.busy = busy
        if busy:
            self.parse_btn.configure(state="disabled")
            self.paste_btn.configure(state="disabled")
            self.url_entry.configure(state="disabled")
            self.format_combo.configure(state="disabled")
            self.dir_entry.configure(state="disabled")
            self.cookies_entry.configure(state="disabled")
            self.cookies_btn.configure(state="disabled")
            self.download_btn.configure(state="disabled")
            if mode == "download":
                self.cancel_btn.configure(state="normal")
                self.quality_combo.configure(state="disabled")
            else:
                self.cancel_btn.configure(state="disabled")
        else:
            self.parse_btn.configure(state="normal")
            self.paste_btn.configure(state="normal")
            self.url_entry.configure(state="normal")
            self.format_combo.configure(state="readonly")
            self.dir_entry.configure(state="normal")
            self.cookies_entry.configure(state="normal")
            self.cookies_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            self._sync_quality_state()
            if self.info:
                self.download_btn.configure(state="normal")
            self.open_btn.configure(state="normal" if self.last_file else "disabled")

    # ------------------------------------------------------------ 解析
    def on_parse(self) -> None:
        if self.busy:
            return
        raw = self.url_var.get()
        if not raw.strip():
            self._notify("请先粘贴视频链接。", WARN_COLOR)
            return

        self.info = None
        self._quality_options = []
        self._clear_thumbnail()
        self.quality_combo.set("解析中…")
        self.download_btn.configure(state="disabled")
        self._set_busy(True, mode="parse")
        self._set_progress_indeterminate()
        self._set_status("正在解析链接…", ACCENT)
        self._log(f"解析：{raw.strip()}")

        cookies = self._cookiefile()
        if cookies:
            self._log(f"使用 cookies：{cookies}")
        analyzer = Analyzer(cookiefile=cookies)
        self.analyzer = analyzer

        def work() -> None:
            try:
                info = analyzer.parse(raw)
            except RuntimeError as exc:
                self.events.put(("parse_error", str(exc)))
                return
            except Exception as exc:  # noqa: BLE001
                self.events.put(("parse_error", f"解析失败：{exc}"))
                return
            self.events.put(("info", info))
            if info.thumbnail:
                data = self._fetch_thumbnail(info.thumbnail)
                if data:
                    self.events.put(("thumb", data))

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _fetch_thumbnail(url: str) -> bytes | None:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read(4 * 1024 * 1024)
        except Exception:  # noqa: BLE001 - 缩略图是锦上添花，失败就跳过
            return None

    def _on_parse_done(self, info: VideoInfo) -> None:
        self.info = info
        self._set_busy(False)
        self._reset_progress()

        self.title_label.configure(text=info.effective_title)
        parts = [f"时长 {human_duration(info.duration)}"]
        if info.qualities:
            parts.append(f"{len(info.qualities)} 档清晰度")
        self.meta_label.configure(text="　·　".join(parts))
        self.uploader_label.configure(
            text=f"UP 主 / 频道：{info.uploader}" if info.uploader else ""
        )

        self._quality_options = info.qualities
        labels = [q.label for q in info.qualities]
        self.quality_combo.configure(values=labels)
        self._sync_quality_state()
        if labels and self.format_combo.get() not in AUDIO_FORMATS:
            self.quality_combo.set(labels[0])

        self.download_btn.configure(state="normal")
        self._set_status(f"解析成功，共 {len(labels)} 档清晰度可选。", OK_COLOR)
        self._log(f"标题：{info.effective_title}")
        for q in info.qualities:
            self._log(f"  · {q.label} — {q.size_text}")

        self.settings["last_url"] = self.url_var.get().strip()
        save_settings(self.settings)

    def _clear_thumbnail(self) -> None:
        self._thumb_image = None
        self.thumb_label.configure(
            image="", text="缩略图", width=20, height=5
        )

    def _on_parse_error(self, message: str) -> None:
        self._set_busy(False)
        self._reset_progress()
        self.quality_combo.set("请先解析")
        self.quality_combo.configure(state="disabled")
        self.title_label.configure(text="解析失败")
        self.meta_label.configure(text="")
        self.uploader_label.configure(text="")
        self._clear_thumbnail()
        self._set_status(message, ERR_COLOR)
        self._log(f"✗ {message}")

    # ------------------------------------------------------------ 下载
    def _selected_quality(self):
        if not self._quality_options:
            return None
        label = self.quality_combo.get()
        for q in self._quality_options:
            if q.label == label:
                return q
        return self._quality_options[0]

    def on_download(self) -> None:
        if self.busy:
            return
        if not self.info:
            self._notify("请先解析链接。", WARN_COLOR)
            return

        raw_dir = self.dir_var.get().strip()
        if not raw_dir:
            self._notify("请选择保存目录。", WARN_COLOR)
            return
        try:
            save_dir = ensure_writable_dir(raw_dir)
        except OSError as exc:
            self._notify(f"保存目录不可用：{exc}", ERR_COLOR)
            return
        self.dir_var.set(str(save_dir))

        out_format = self.format_combo.get()
        quality = None if out_format in AUDIO_FORMATS else self._selected_quality()
        if out_format not in AUDIO_FORMATS and quality is None:
            self._notify("请选择清晰度。", WARN_COLOR)
            return

        if not config.find_ffmpeg():
            self._log(
                "⚠ 未检测到 ffmpeg：无法合并音视频或转换音频格式，"
                "此次下载会在需要合并时失败。建议把 ffmpeg.exe 放到程序同目录。"
            )

        task = DownloadTask(
            url=self.info.url,
            save_dir=save_dir,
            quality=quality,
            out_format=out_format,
            expected_title=self.info.effective_title,
            on_progress=lambda e: self.events.put(("progress", e)),
            on_log=lambda m: self.events.put(("log", m)),
            cookiefile=self._cookiefile(),
        )
        self.task = task
        self.last_file = None
        self.open_btn.configure(state="disabled")
        self._set_busy(True, mode="download")
        self._set_progress_indeterminate()
        self._set_status("正在准备下载…", ACCENT)

        target = "音频" if out_format in AUDIO_FORMATS else (quality.label if quality else BEST_QUALITY)
        self._log(f"开始下载：{target} → {out_format}，保存到 {save_dir}")

        self.settings["save_dir"] = str(save_dir)
        self.settings["out_format"] = out_format
        save_settings(self.settings)

        def work() -> None:
            result: DownloadResult = task.run()
            self.events.put(("done", result))

        threading.Thread(target=work, daemon=True).start()

    def on_cancel(self) -> None:
        if self.task:
            self.task.cancel()
            self._log("已请求取消，等待当前分片结束后停止…")
            self.cancel_btn.configure(state="disabled")
            self._set_status("正在取消…", WARN_COLOR)

    def _on_progress(self, ev: ProgressEvent) -> None:
        if ev.status == "preparing":
            self._set_progress_indeterminate()
            self._set_status("正在准备下载…", ACCENT)
            return
        if ev.status == "merging":
            self._set_progress_indeterminate()
            self._set_status(ev.stage_text or "正在后处理…", ACCENT)
            return
        if ev.status == "finished":
            self._set_progress_value(100)
            return

        self._set_progress_value(ev.percent)
        bits = [f"{ev.percent:5.1f}%"]
        if ev.total:
            bits.append(f"{human_size(ev.downloaded)} / {human_size(ev.total)}")
        if ev.speed:
            bits.append(human_speed(ev.speed))
        if ev.eta is not None:
            bits.append(f"剩余 {human_eta(ev.eta)}")
        if ev.stage_text:
            bits.append(ev.stage_text)
        self._set_status("　·　".join(bits), ACCENT)

    def _on_download_done(self, result: DownloadResult) -> None:
        self.task = None
        self._set_busy(False)

        if result.ok:
            self.last_file = result.filepath
            self._set_progress_value(100)
            name = result.filepath.name if result.filepath else "（未知文件名）"
            self._set_status(f"✓ 下载完成：{name}", OK_COLOR)
            self._log(f"✓ 下载完成：{result.filepath}")
            self.open_btn.configure(state="normal")
            self._log(f"    文件：{result.filepath}")
            self._log("    点击「打开文件夹」可直接定位到该文件。")
        elif result.cancelled:
            self._reset_progress()
            self._set_status("已取消下载。", WARN_COLOR)
            self._log("下载已取消。")
        else:
            self._reset_progress()
            self._set_status(result.error or "下载失败。", ERR_COLOR)
            self._log(f"✗ {result.error or '下载失败。'}")

    def on_open_folder(self) -> None:
        if self.last_file and self.last_file.exists():
            open_in_explorer(self.last_file)
            return
        try:
            folder = ensure_writable_dir(self.dir_var.get())
        except OSError as exc:
            self._notify(f"目录不可用：{exc}", ERR_COLOR, "✗")
            return
        try:
            open_folder(folder)
        except Exception as exc:  # noqa: BLE001
            self._notify(f"无法打开目录：{exc}", ERR_COLOR, "✗")

    # ------------------------------------------------------------ 缩略图
    def _set_thumbnail(self, data: bytes) -> None:
        try:
            from PIL import Image, ImageTk

            image = Image.open(io.BytesIO(data))
            image.thumbnail(self.THUMB_SIZE)
            photo = ImageTk.PhotoImage(image)
            self._thumb_image = photo
            self.thumb_label.configure(image=photo, text="", width=self.THUMB_SIZE[0], height=self.THUMB_SIZE[1])
        except Exception:  # noqa: BLE001 - 没有 Pillow 或图片损坏时保持占位
            return

    # ------------------------------------------------------------ 关闭
    def on_close(self) -> None:
        # 关闭时不做弹窗确认：直接取消正在进行的工作并退出。
        if self.busy:
            self._log("窗口关闭，正在中止当前任务…")
            if self.task:
                self.task.cancel()
            if self.analyzer:
                self.analyzer.cancel()
        self.settings["last_url"] = self.url_var.get().strip()
        self.settings["save_dir"] = self.dir_var.get().strip()
        self.settings["out_format"] = self.format_combo.get()
        self.settings["cookiefile"] = self.cookies_var.get().strip()
        save_settings(self.settings)
        if self.bridge:
            self.bridge.stop()
        self.root.destroy()


def run() -> None:
    """程序入口：创建窗口并进入主循环。"""
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass

    root = tk.Tk()
    VideoDownloadApp(root)
    root.mainloop()
