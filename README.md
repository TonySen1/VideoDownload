# VideoDownload — 基于 yt-dlp 的 Windows 视频下载器

一个用 tkinter 写的轻量桌面下载工具，底层用 **yt-dlp Python 库**（不是调用命令行），
调用 **ffmpeg** 完成音视频合并与音频格式转换。

主流程：**粘贴链接 → 解析 → 选清晰度 / 格式 → 选目录 → 下载**。

> 全程**不使用任何弹窗**：所有校验、告警、错误、完成提示都只出现在状态行和日志区。

> [!IMPORTANT]
> **使用须知**
>
> 本项目仅供个人学习、研究与**自有内容的备份**使用。
>
> - 请遵守目标网站的服务条款与当地法律。未获得授权时，下载受版权保护的内容可能侵权。
> - `yt-dlp` 等第三方组件的行为由其各自项目负责，本项目仅提供图形界面。
> - 请勿将本工具用于商业用途、批量抓取或再分发他人作品。
>
> 使用本软件即表示你已知悉并自行承担相应责任。

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
| 浏览器扩展 | 支持站点页面右下角悬浮按钮 / 工具栏弹窗一键发送链接，程序自动填入并解析 |
| 登录 cookies | 扩展一键同步登录态，用于访问本人账号下已获授权观看的内容 |
| JS 运行时 | 自动探测 Node/deno 并启用 EJS 组件，保证完整清晰度可用 |

---

## 2. 目录结构

```
VideoDownload/
├── main.py                  # 启动入口（PyInstaller 入口）
├── app/
│   ├── __init__.py
│   ├── bridge.py            # 本地 HTTP 桥接服务（给浏览器扩展投递链接用）
│   ├── cookies.py           # cookies.txt 生成与域名白名单校验
│   ├── config.py            # 路径解析、ffmpeg 查找（打包/源码两种模式）
│   ├── core.py              # 核心逻辑：解析、格式选择、下载、错误友好化（无 GUI 依赖）
│   ├── ui.py                # tkinter 界面
│   └── util.py              # 大小/时长格式化、文件名清洗、设置读写
├── extension/               # 浏览器扩展（Chrome / Edge，Manifest V3）
│   ├── manifest.json
│   ├── background/
│   │   ├── service_worker.js
│   │   └── cookies.js       # 收集并转发登录 cookies
│   ├── content/pill.js      # 页面右下角悬浮按钮
│   ├── popup/               # 工具栏弹窗（发送链接 / 同步 cookies）
│   └── icons/               # 由 tools/make_icon.py 生成
├── assets/
│   ├── videodownload.ico    # 程序图标（多尺寸，圆角立体）
│   └── videodownload-preview.png
├── tools/
│   └── make_icon.py         # 图标生成脚本（ico + 扩展图标）
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

## 6. 浏览器扩展

`extension/` 是一个 Manifest V3 扩展，用于把浏览器当前页面的链接一键送到本程序。

### 安装（加载未打包扩展）

1. 打开 `chrome://extensions`（Edge 为 `edge://extensions`）。
2. 打开右上角 **开发者模式**。
3. 点 **加载已解压的扩展程序**，选择本项目的 `extension` 目录。
4. 扩展图标出现在工具栏，之后保持程序运行即可自动连接。

### 用法

- **悬浮按钮**：在支持的站点页面上，右下角会出现蓝色胶囊「用 VideoDownload 下载」，
  点一下即发送。按钮可拖拽，位置按站点分别记忆。
- **工具栏弹窗**：点扩展图标打开，可「发送到 VideoDownload」或「同步 cookies 到程序」。

支持的站点：YouTube（含 Shorts / Music）、Vimeo、Instagram、Facebook、
X / Twitter、Bilibili、StashMedia、TikTok。

### 同步 cookies（登录后才能访问的视频）

部分视频需要登录账号才能观看（例如账号可见、好友分享、已订阅会员内容）。
这类视频不带 cookie 时解析会报 `Sign in to confirm your age` 或 `login required`。

> 请仅同步**你自己账号**的登录状态，并确保对这些内容有观看权限。
> cookies 等同于账号凭据，请勿分享 `cookies.txt` 文件。

**为什么不能直接用 yt-dlp 读浏览器**：

- Chrome 127+ 用 App-Bound Encryption 加密 cookie（数据库里是 `v20` 前缀），
  yt-dlp 读取会报 `Failed to decrypt with DPAPI`；
- Edge 会因数据库被浏览器占用而复制失败。

**解决办法**：让扩展用 `chrome.cookies` API 取明文，转发给本程序。

1. 浏览器里正常登录 YouTube；
2. 点扩展图标 → **同步 cookies 到程序**；
3. 程序日志显示「✓ 浏览器扩展已同步 cookies：N 条」；
4. 之后这类视频可直接解析下载。

同步结果保存在 `%LOCALAPPDATA%\VideoDownload\cookies.txt`。
也可以在界面「下载选项 → cookies 文件」里手动指定自己导出的 `cookies.txt`。

> 前提：`%LOCALAPPDATA%` 数据目录里没有 cookies.txt 时，程序也会自动探测
> exe 同目录的 `cookies.txt`；环境变量 `YTDIP_COOKIES` 优先级最高。

### 为什么还需要 JS 运行时

只配 cookies 还不够。yt-dlp 2025.11 起把 YouTube 页面脚本求值的组件拆成了
可下载模块，默认不启用，表现是**解析成功但只返回 storyboard 缩略图格式**
（日志里 `format is not available` 或格式列表只有 `sb0..sb3`）。

程序启动时会自动配置两项：
- `js_runtimes`：探测 `deno` / `node` / `bun` / `quickjs`，命中即用；
  也可以用环境变量 `YTDIP_JS_RUNTIME` 指定。
- `remote_components: ["ejs:github"]`：首次使用会联网拉取该组件（几秒）。

> Windows 机器上通常装有 Node.js，能直接满足要求。如果既没有 Node 也没装
> deno，部分视频会拿不到可用格式（大多数普通视频不受影响）。

### 工作方式

程序启动时在 `127.0.0.1` 上按 `6811 → 6822 → 6833 → 6844 → 6855` 顺序绑定第一个可用端口，
扩展后台每分钟探测一次并记住可用端口。状态栏会显示实际端口，例如：

```
✓ ffmpeg 已就绪：... | yt-dlp 2026.11.23 | 扩展桥接 127.0.0.1:6811
```

接口有三个：

| 接口 | 请求 | 响应 |
| --- | --- | --- |
| `POST /hello` | `{version, browser}` | `{ok, app:"videosdown", settings:{show_pill}}` |
| `POST /submit` | `{url, title, version, browser}` | `{ok:true}` 或 `{ok:false, msg}` |
| `POST /cookies` | `{cookies:[...], source}` | `{ok:true, msg:"已接收 N 条"}` 或 `{ok:false, msg}` |

`/cookies` 的域名白名单在 `app/cookies.py` 与 `extension/background/cookies.js`
两处各校验一次，只接受视频站点及其登录依赖域（如 YouTube 需要 `google.com`），
其它域一律丢弃；返回值只含条数，不回传 cookie 内容。

只监听回环地址，请求体上限 64 KB，跨域只放行扩展来源与本机页面。
收到链接后程序会自动置前、填入地址栏并立即解析；若当前正在解析/下载，
只填入不解析，并在日志里说明。

### 图标

扩展图标与桌面程序同源：`tools/make_icon.py` 每次运行会同时写出
`assets/videodownload.ico` 和 `extension/icons/icon{16,48,128}.png`，
改图标只需改那一个脚本后重跑。

---

## 7. 使用说明

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

## 8. 格式与合并逻辑

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

## 9. 异常处理

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

## 10. 图标

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

## 11. 测试

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
| 13 | 加载扩展后打开 YouTube 视频页 | 右下角出现蓝色胶囊按钮，可拖拽 |
| 14 | 点胶囊 / 弹窗「发送到 VideoDownload」 | 程序置前、自动填链接并解析 |
| 15 | 在非支持站点（如 `example.org`） | 不出现悬浮按钮 |
| 16 | 关闭程序后点扩展按钮 | 提示"软件未运行或连接已关闭"，不崩不阻塞 |
| 17 | 弹窗点「同步 cookies 到程序」 | 日志显示「✓ 已同步 cookies：N 条」，`cookies.txt` 落盘 |
| 18 | 同步 cookies 后解析需登录的视频 | 出现完整清晰度列表，不再报 Sign in to confirm your age |
| 19 | 机器上没有 Node/deno | 部分视频仍拿不到格式（多数普通视频正常），日志提示缺 JS 运行时 |

---

## 12. 已知限制

- 需要登录的内容要在扩展里同步一次 cookies；没有登录态时这类视频无法解析。
- 机器上没有 Node/deno 时，部分视频会缺格式（多数普通视频不受影响）。
- `remote_components` 首次使用需联网下载组件，离线环境下会失败。
- 只处理播放列表的第一条。
- 未做多任务并行下载队列（一次一个任务，便于控制进度与取消）。
- cookies 明文保存在本机，等同于账号凭据；请勿分享 `cookies.txt`。

---

## 13. 许可证

本项目以 [MIT License](LICENSE) 发布。

第三方依赖各自遵循其许可证：`yt-dlp`（Unlicense）、`Pillow`（HPND）、
`ffmpeg`（未随仓库分发，按需自行获取并遵守其 LGPL/GPL 条款）。
