# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

用法（项目根目录）：
    .venv\\Scripts\\pyinstaller --noconfirm --clean VideoDownload.spec

产物：dist\\VideoDownload.exe（单文件，自带 Python 运行时与 yt-dlp，无需安装 Python）。

ffmpeg 的处理：
    默认不把 ffmpeg 塞进 exe（会让体积 +80~180MB）。打包后把 ffmpeg.exe
    复制到 VideoDownload.exe 同目录即可，程序启动时自动检测。
    若确实想做“真·单文件”，把下面的 BUNDLE_FFMPEG 改为 True。
"""

from pathlib import Path

ROOT = Path(SPECPATH)
BUNDLE_FFMPEG = False

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []

# ---- 窗口与任务栏图标：打进 exe，运行时从 _MEIPASS/assets 读取 ----
_icon = ROOT / "assets" / "videodownload.ico"
if _icon.is_file():
    datas.append((str(_icon), "assets"))

# ---- 可选：内置 ffmpeg ----
ffmpeg_src: Path | None = None
for candidate in (ROOT / "vendor" / "ffmpeg.exe", ROOT / "ffmpeg.exe"):
    if candidate.is_file():
        ffmpeg_src = candidate
        break
if BUNDLE_FFMPEG and ffmpeg_src:
    binaries.append((str(ffmpeg_src), "."))

# ---- yt-dlp 的 extractor 是动态导入的，必须显式收集 ----
hiddenimports: list[str] = [
    "yt_dlp",
    "yt_dlp.extractor",
    "yt_dlp.extractor.lazy_extractors",
    "yt_dlp.downloader",
    "yt_dlp.postprocessor",
    "yt_dlp.networking",
    "yt_dlp.networking._requests",
    "yt_dlp.compat",
    "tkinter",
    "tkinter.filedialog",
    "tkinter.ttk",
    "tkinter.font",
    "sqlite3",
    "json",
    "urllib.request",
    "PIL.Image",
    "PIL.ImageTk",
    "PIL._tkinter_finder",
]

# yt-dlp 自带 __pyinstaller hook（若打包版自带），加上以防漏
try:
    import yt_dlp._pyinstaller as _ypi  # type: ignore

    hiddenimports += list(getattr(_ypi, "hiddenimports", []) or [])
except Exception:
    pass

site = ROOT / ".venv" / "Lib" / "site-packages"
for sub in ("extractor", "downloader", "postprocessor", "networking", "compat", "dependencies"):
    base = site / "yt_dlp" / sub
    if not base.is_dir():
        continue
    for py in base.rglob("*.py"):
        if py.name.startswith("__"):
            continue
        if "__pycache__" in py.parts:
            continue
        rel = py.relative_to(site).with_suffix("")
        hiddenimports.append(".".join(rel.parts))

hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy", "pandas", "matplotlib", "scipy", "PyQt5", "PyQt6",
        "PySide2", "PySide6", "IPython", "pytest", "notebook",
        "setuptools", "pip", "wheel", "unittest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VideoDownload",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "videodownload.ico")
    if (ROOT / "assets" / "videodownload.ico").is_file() else None,
)
