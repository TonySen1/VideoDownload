# VideoDownload — 基于 yt-dlp 的 Windows 视频下载器

一个用 tkinter 写的轻量桌面下载工具，底层用 **yt-dlp Python 库**（不是调用命令行），
调用 **ffmpeg** 完成音视频合并与音频格式转换。

主流程：**粘贴链接 → 解析 → 选清晰度 / 格式 → 选目录 → 下载**。

> 全程**不使用任何弹窗**：所有校验、告警、错误、完成提示都只出现在状态行和日志区。

---

## 1. 功能

| 能力 | 说明 |
| --- | --- |
| 解析 | 标题、时长、UP 主、缩略图，按分辨率聚合清晰度（144p ~ 4K/8K），显示估算体积 |
| 格式 | 视频：自动 / mp4 / mkv / webm；音频：mp3 / m4a / wav / flac |
| 下载 | 多线程分片、断点续传、进度条 + 速度 + 剩余时间 + 分阶段提示 |
| 合并 | DASH 流自动 `bestvideo+bestaudio`，按所选容器交给 ffmpeg 合并 |
| 容错 | 容器不兼容时自动回退 MKV 重试；无效链接 / 私密视频 / 403 / 超时 等转成中文提示 |
| 交互 | 无弹窗；记住上次链接与目录；中文目录可用；非法文件名自动清洗；打开并选中文件 |

---

## 2. 目录结构

```
VideoDownload/
├── main.py                  # 启动入口（PyInstaller 入口）
├── app/
│   ├── __init__.py
│   ├── config.py            # 路径解析、ffmpeg 查找（打包/源码两种模式）
│   ├── core.py              # 核心逻辑：解析、格式选择、下载、错误友好化（无 GUI 依赖）
│   ├── ui.py                # tkinter 界面
│   └── util.py              # 大小/时长格式化、文件名清洗、设置读写
├── assets/
│   ├── videodownload.ico    # 程序图标（多尺寸，圆角立体）
│   └── videodownload-preview.png
├── tools/
│   └── make_icon.py         # 图标生成脚本（可重新生成 ico）
├── tests/
│   └── test_download.py     # 真实链路测试（无效链接 / 解析 / 视频 / 音频）
├── requirements.txt         # 运行依赖
├── requirements-dev.txt     # 打包依赖
├── VideoDownload.spec       # PyInstaller 配置
├── build.bat                # 一键打包脚本
├── ffmpeg.exe / ffprobe.exe # 外部依赖（见第 4 节）
└── README.md
```

`core.py` 完全不 import tkinter，UI 只负责收集参数、把回调塞进队列；
所有耗时操作跑后台线程，通过 `queue.Queue` 回主线程刷新界面 —— 这是「逻辑与 UI 分离」的落点。

---

## 3. 源码运行

```bat
cd VideoDownload
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

要求 **Python 3.11+**（3.10 会被 yt-dlp 提示已废弃）。

> 本项目目录内已备好 `.venv`（Python 3.12），可直接 `.venv\Scripts\python.exe main.py`。

---

## 4. ffmpeg 的配置方式

程序启动时按下面的顺序找 `ffmpeg`，命中即用，状态栏会显示实际路径：

1. 环境变量 `YTDIP_FFMPEG` 指向的路径（可直接指 exe，也可指目录）
2. **exe 同目录** `ffmpeg.exe` ← 最省事，推荐
3. exe 同目录下的 `bin\ffmpeg.exe`
4. PyInstaller 解包目录（只有把 ffmpeg 打进 exe 时才会命中）
5. 系统 `PATH`

`ffprobe` 会从 ffmpeg 同目录自动找，找不到也不影响下载（只是少了校验手段）。

### 为什么默认不把 ffmpeg 打进 exe

ffmpeg 单文件 100~170MB，塞进单文件 exe 后每次启动都要解压到 `%TEMP%`，
启动慢且占用临时空间。**推荐把 `ffmpeg.exe` 放在 `VideoDownload.exe` 旁边**：

```
发布目录/
├── VideoDownload.exe
├── ffmpeg.exe
└── ffprobe.exe   （可选）
```

确实想做成"真·单文件"：把 `VideoDownload.spec` 里的 `BUNDLE_FFMPEG = True`，
再把 `ffmpeg.exe` 放到项目根目录或 `vendor/` 下，重新打包即可。

### ⚠️ 关于 ffmpeg 版本

**必须用较新的 ffmpeg**（2024 年以后的构建）。旧版 ffmpeg 不认识 AV1 编码，
把 YouTube 4K 的 AV1 视频轨封装进 mp4 时会报
`Could not write header ... Experimental feature` / `Conversion failed!`。

本项目根目录已附带 `ffmpeg 9.0.2`（gyan.dev essentials 构建，已验证可封装 AV1→mp4）。
如需自行更新：

- <https://www.gyan.dev/ffmpeg/builds/> → `ffmpeg-release-essentials.zip`
- <https://github.com/BtbN/FFmpeg-Builds/releases> → `ffmpeg-master-latest-win64-gpl.zip`

解压后把 `bin\ffmpeg.exe`（有 ffprobe 就一并带上）放到 `VideoDownload.exe` 同目录。

程序本身也做了兜底：mp4/webm 封装失败时会**自动改用 MKV 重试**（MKV 几乎能装下任何编码），
并优先选择非 AV1 的视频轨，所以即使 ffmpeg 偏旧，大多数 4K 内容仍能下下来。

---

## 5. 打包成 exe

### 方式 A：一键脚本（推荐）

```bat
build.bat
```

依次：建 venv → 装依赖 → 清旧产物 → 跑 PyInstaller → 把 `ffmpeg.exe`/`ffprobe.exe` 复制进 `dist\`。

### 方式 B：手动命令

```bat
cd VideoDownload
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean VideoDownload.spec

copy ffmpeg.exe dist\ffmpeg.exe
copy ffprobe.exe dist\ffprobe.exe
```

产物：`dist\VideoDownload.exe`（约 24MB，单文件，`console=False` 无黑框，带图标）。

### 单文件 exe 的临时目录问题

PyInstaller 单文件模式会把资源解压到 `sys._MEIPASS`（`%TEMP%\_MEIxxxx`），
**进程退出即删除**。因此项目里所有持久化数据都不放那里：

- 设置文件 → `%LOCALAPPDATA%\VideoDownload\settings.json`
- 启动失败日志 → `%LOCALAPPDATA%\VideoDownload\startup-error.log`
- 下载目录 → 用户自选，默认 `%USERPROFILE%\Downloads`
- 临时文件一律由 yt-dlp / ffmpeg 在下载目录内自行管理

`app/config.py` 用 `is_frozen()` 区分源码/打包两种运行方式，
`app_dir()` 取 exe 所在目录（而不是 `_MEIPASS`），这样"exe 旁边放 ffmpeg"才成立；
图标这类只读资源则放 `_MEIPASS/assets`，由 spec 的 `datas` 打进去。

### spec 里为什么要把 yt-dlp 的 extractor 全列出来

yt-dlp 通过 `importlib` 动态加载 `yt_dlp/extractor/*.py`（约 940 个站点模块），
PyInstaller 的静态分析抓不到。`VideoDownload.spec` 会扫描 `site-packages/yt_dlp`
下的 `extractor/ downloader/ postprocessor/ networking/ compat/ dependencies/`
并逐个加入 `hiddenimports`，否则打包后会出现
`ImportError: ... extractor ...` 或"没有可用提取器"。

---

## 6. 使用说明

1. 复制视频链接，点 **粘贴**（或 `Ctrl+V` 直接输入）。
2. 点 **解析**（或回车）。成功后显示缩略图、标题、时长和清晰度下拉框。
3. 选 **清晰度**。选音频格式（mp3/m4a/wav/flac）时清晰度自动禁用 —— 纯音频没有分辨率。
4. 选 **输出格式**。默认「自动」= 让 yt-dlp 挑最佳组合，程序按资源能否兼容决定容器。
5. 选 **保存目录**（默认 `下载` 文件夹，记住上次选择）。
6. 点 **开始下载**。进度条、速度、剩余时间、当前阶段都在状态行；详细日志在下方。
7. 完成后状态行变绿 + 日志输出文件路径；点 **打开文件夹** 会在资源管理器里**选中该文件**。

按钮状态规则：

- 未解析 → 「开始下载」禁用
- 解析中 / 下载中 → 解析、粘贴、格式选择、目录全部禁用，「取消」可用
- 下载结束（成功/失败/取消）→ 恢复可用

### 提示机制（无弹窗）

| 情况 | 表现 |
| --- | --- |
| 空链接 / 未解析就点下载 / 未选目录 | 状态行黄字 + 日志一行 |
| 解析失败 | 标题区显示"解析失败"，状态行红字 + 日志，缩略图清空 |
| 下载失败 | 状态行红字 + 日志，弹窗为零 |
| 下载完成 | 进度条满、状态行绿字、日志写入文件路径 |
| 缺 ffmpeg | 启动时状态栏黄色告警；点下载时日志再提醒一次（不阻断） |
| 关闭窗口时还在跑 | 直接取消任务并退出，不弹确认框 |

---

## 7. 格式与合并逻辑

`app/core.py: build_format_selector()` 生成的 `-f` 串示例（1080p + mp4）：

```
bestvideo[height=1080][ext=mp4][vcodec!*=av01]+bestaudio[ext=m4a]
 / bestvideo[height=1080][vcodec!*=av01]+bestaudio[ext=m4a]
 / best[height=1080][ext=mp4]
 / bestvideo[height=1080]+bestaudio
 / best[height=1080]
 / bestvideo[height<=1080]+bestaudio
 / best[height<=1080]
 / best
```

优先级：**同高度 + 目标容器 + 非 AV1** → **同高度非 AV1** → **同高度任意** → **不超过该高度** → best。
排 AV1 是因为不少用户机器上的 ffmpeg 偏旧，mp4 装不下 AV1 会直接失败。

音频：`bestaudio/best` + `FFmpegExtractAudio` 后处理器，mp3 用 `preferredquality=0`（VBR 最高），其余 192k。

合并：`merge_output_format` 设为目标容器，由 ffmpeg 无损 `-c copy` 合并（不重新编码，速度快）。

**自动回退**：mp4/webm 因编码不兼容导致后处理失败时，`DownloadTask.run()` 会捕获并
用 MKV 容器重跑一次（`force_container="mkv"`），日志说明原因。

---

## 8. 异常处理

| 场景 | 表现（仅状态行 / 日志） |
| --- | --- |
| 空输入 / 非 http 链接 | 输入阶段直接拒绝，中文原因 |
| 不支持的站点 / URL 失效 | `链接无效或该网站不受支持` |
| 视频已删除 / 私密 / 会员专享 | 对应中文提示 |
| 403 / 404 / 429 | 分别给出针对性提示 |
| 超时 / DNS / 代理失败 | 提示检查网络或代理 |
| 缺 ffmpeg | 状态栏黄色告警 + 下载前日志提醒；失败时提示确认 ffmpeg |
| 磁盘满 / 无写权限 | `磁盘空间不足` / `没有写入权限` |
| 下载中途取消 | 返回"已取消"，不残留半成品命名 |
| 任何未预期异常 | `run()` 兜底捕获，转成中文提示，**进程不崩** |

文件名：给 yt-dlp 开 `windowsfilenames=True` + `trim_file_name=120`，
输出模板 `%(title).120B [%(id)s].%(ext)s`（按**字节**截断，中文也不会超长），
再加 `util.sanitize_filename()` 兜底处理 `<>:"/\|?*`、控制字符、`CON/NUL` 等保留名。

---

## 9. 图标

`assets/videodownload.ico` 内含 16/20/24/32/40/48/64/96/128/256 十个尺寸，
设计为圆角方形 + 蓝色渐变 + 中心柔光 + 内描边倒角 + 白色下载箭头（带投影），
追求在 16px 下仍能辨认、在 256px 下有立体感。

重新生成：

```bat
.venv\Scripts\python.exe tools\make_icon.py
```

脚本用 1024×1024 画布超采样绘制，再逐尺寸 LANCZOS 缩小，避免小图标锯齿。
生成后会同时输出 `assets/videodownload-preview.png` 供预览。
颜色、圆角比例、箭头尺寸都在 `tools/make_icon.py` 顶部的常量里，改完重跑即可。

---

## 10. 测试

### 自动化脚本

```bat
rem 默认：B 站测试视频，360p/mp4 + mp3
.venv\Scripts\python.exe tests\test_download.py

rem 指定链接与清晰度（4K 测试链接）
.venv\Scripts\python.exe tests\test_download.py --url "https://www.youtube.com/watch?v=sMtHM2Z1cVQ" --height 2160 --fmt mp4

rem 只测视频，不测音频
.venv\Scripts\python.exe tests\test_download.py --height 720 --fmt mkv --skip-audio
```

脚本会真实访问网络，覆盖：

1. **无效链接**：空串、`not a url`、`ftp://`、不存在的主机 —— 全部必须被拒且不抛栈
2. **解析**：标题、时长、缩略图、清晰度档数与体积估算
3. **视频下载**：指定清晰度 + 容器，含音视频合并
4. **音频下载**：mp3 转换

输出到 `tests\_out\`，末尾打印 PASS/FAIL 汇总。

### 手工验收清单

| # | 场景 | 期望 |
| --- | --- | --- |
| 1 | 双击 `dist\VideoDownload.exe` | 窗口打开，标题栏有图标，底部显示 ffmpeg 路径 |
| 2 | 粘贴 `https://www.youtube.com/watch?v=sMtHM2Z1cVQ` → 解析 | 出现 4K/2K/1080p…/144p 共 8 档，带体积 |
| 3 | 选 4K + mp4 → 下载 | 有合并阶段提示，产出 3840×2160 的 `.mp4`，正常播放 |
| 4 | 选 720p + mkv | 产出 `.mkv` |
| 5 | 选 mp3 | 清晰度下拉禁用，产出 `.mp3` |
| 6 | 粘贴 `abc` → 解析 | 状态行红字 + 日志提示，**无弹窗**，程序不崩 |
| 7 | 未解析直接点下载 | 状态行提示"请先解析链接" |
| 8 | 下载中点「取消」 | 状态变"已取消"，按钮恢复 |
| 9 | 中文目录 `D:\我的视频`（含空格/中文）| 正常下载 |
| 10 | 把 ffmpeg.exe 移走重启 | 状态栏黄色告警；下载单文件格式仍可用 |
| 11 | 在无 Python 的机器上运行 | 能正常启动（单文件自带运行时）|
| 12 | 任意操作全程 | 除"浏览目录"的文件选择框外，不出现任何对话框 |

---

## 11. 已知限制

- 需要登录 / 年龄验证 / 会员的内容无法直接下载（未接 cookies）。
- YouTube 未安装 JS 运行时时，yt-dlp 会警告部分格式缺失；4K 通常仍可取到（VP9/AV1），
  只是某些高阶格式（如部分 H.264 高清）可能拿不到。
- 只处理播放列表的第一条。
- 未做多任务并行下载队列（一次一个任务，便于控制进度与取消）。
