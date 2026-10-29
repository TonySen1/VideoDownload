@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title YT-DLP 一键下载
color 0A

echo ============================================
echo        YT-DLP 一键下载工具
echo ============================================
echo.

rem ---- 检查 yt-dlp.exe 是否存在 ----
if not exist "%~dp0yt-dlp.exe" (
    echo [提示] 未找到 yt-dlp.exe，请把它放在本脚本同目录下。
    pause
    exit /b
)

rem ---- 支持拖拽链接文件 / 命令行传入 ----
set "URL=%~1"

rem ---- 自动读取剪贴板 ----
if not defined URL (
    for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Clipboard"') do set "URL=%%i"
)

rem ---- 判断剪贴板内容是否像链接 ----
echo !URL! | findstr /i "http" >nul 2>&1
if errorlevel 1 set "URL="

rem ---- 剪贴板没有就手动输入 ----
if not defined URL (
    set /p "URL=请输入视频链接: "
)

if not defined URL (
    echo [错误] 未获取到有效链接，程序退出。
    pause
    exit /b
)

echo.
echo [下载中] !URL!
echo.
"%~dp0yt-dlp.exe" -f "bestvideo+bestaudio/best" --merge-output-format mkv -o "%%(title)s.%%(ext)s" "!URL!"

echo.
echo ============ 下载完成！============
pause