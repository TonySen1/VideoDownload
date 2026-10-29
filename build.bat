@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   VideoDownload 一键打包（PyInstaller 单文件）
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] 创建虚拟环境...
    py -3.12 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo [错误] 找不到 Python 3.12+，请先安装。
        pause & exit /b 1
    )
)

echo [2/4] 安装依赖...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt -q
if errorlevel 1 (
    echo [错误] 依赖安装失败。
    pause & exit /b 1
)

echo [3/4] 清理旧产物...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [4/4] PyInstaller 打包...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean VideoDownload.spec
if errorlevel 1 (
    echo [错误] 打包失败，请查看上方日志。
    pause & exit /b 1
)

echo.
echo 打包完成：dist\VideoDownload.exe
echo.

rem ---- 把 ffmpeg 一起放到发布目录 ----
if exist "ffmpeg.exe" (
    copy /y "ffmpeg.exe" "dist\ffmpeg.exe" >nul
    echo 已复制 ffmpeg.exe 到 dist\
    if exist "ffprobe.exe" (
        copy /y "ffprobe.exe" "dist\ffprobe.exe" >nul
        echo 已复制 ffprobe.exe 到 dist\
    )
) else (
    echo [提示] 未找到 ffmpeg.exe，请手动放入 dist\ 目录。
)

echo.
echo 发布目录内容：
dir /b dist
echo.
pause
