"""真实链路测试：解析 + 下载 + 合并 + 音频转换。

用法（在项目根目录）：
    .venv\\Scripts\\python.exe tests\\test_download.py
    .venv\\Scripts\\python.exe tests\\test_download.py --url <视频链接> --height 360 --fmt mp4

注意：会真实访问网络并下载文件，输出到 tests/_out/。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.core import Analyzer, DownloadTask, build_quality_list, normalize_url  # noqa: E402

DEFAULT_URL = "https://www.bilibili.com/video/BV1GJ411x7h7"
OUT = ROOT / "tests" / "_out"


def log(msg: str) -> None:
    print(msg, flush=True)


def test_bad_url() -> bool:
    log("[1] 无效链接")
    cases = ["", "not a url", "ftp://example.com/x", "https://example.invalid/definitely-nope-123"]
    ok = True
    for case in cases:
        try:
            Analyzer().parse(case)
        except Exception as exc:  # noqa: BLE001
            log(f"    ✓ 已拒绝 {case!r} → {str(exc)[:90]}")
            continue
        log(f"    ✗ 居然通过了 {case!r}")
        ok = False
    for case in ["", " ".join([])]:
        try:
            normalize_url(case)
            log(f"    ✗ normalize_url 未拦截 {case!r}")
            ok = False
        except ValueError as exc:
            log(f"    ✓ normalize_url 拦截 {case!r} → {exc}")
    return ok


def test_parse(url: str) -> object | None:
    log(f"[2] 解析 {url}")
    try:
        info = Analyzer().parse(url)
    except Exception as exc:  # noqa: BLE001
        log(f"    ✗ 解析失败：{exc}")
        return None
    log(f"    ✓ 标题：{info.title}")
    log(f"      时长：{info.duration}s　缩略图：{'有' if info.thumbnail else '无'}")
    for q in info.qualities:
        log(f"      · {q.label:<14} {q.size_text}")
    return info


def run_download(info, height: int | None, fmt: str) -> bool:
    tag = "音频" if fmt in ("mp3", "m4a", "wav", "flac") else f"{height}p"
    log(f"[3] 下载 {tag} → {fmt}")
    quality = None
    if height is not None:
        candidates = [q for q in info.qualities if q.height == height]
        if not candidates:
            log(f"    ! 没有 {height}p，改用最高档")
            quality = info.qualities[0]
        else:
            quality = candidates[0]
    elif fmt not in ("mp3", "m4a", "wav", "flac"):
        quality = info.qualities[0]

    OUT.mkdir(parents=True, exist_ok=True)
    last = {"pct": -1.0}

    def on_progress(ev) -> None:
        if ev.status == "downloading" and abs(ev.percent - last["pct"]) >= 10:
            last["pct"] = ev.percent
            log(f"      {ev.percent:5.1f}%  {ev.speed and round(ev.speed/1024/1024, 2)}MB/s  "
                f"剩余 {ev.eta if ev.eta is not None else '--'}s")
        elif ev.status == "merging":
            log(f"      {ev.stage_text}")

    task = DownloadTask(
        url=info.url,
        save_dir=OUT,
        quality=quality,
        out_format=fmt,
        expected_title=info.title,
        on_progress=on_progress,
        on_log=lambda m: log(f"      {m}"),
    )
    started = time.time()
    result = task.run()
    elapsed = time.time() - started
    if not result.ok:
        log(f"    ✗ 失败：{result.error}")
        return False
    path: Path = result.filepath
    log(f"    ✓ 成功：{path.name}　{path.stat().st_size/1024/1024:.2f} MB　{elapsed:.1f}s")
    if not path.is_file():
        log("    ✗ 文件不存在")
        return False
    # 用 ffprobe 有的话校验一下容器
    probe = config.find_ffprobe()
    if probe:
        import subprocess

        proc = subprocess.run(
            [str(probe), "-v", "error", "-show_entries", "format=format_name,duration",
             "-of", "default=nw=1", str(path)],
            capture_output=True, text=True,
        )
        log(f"      ffprobe: {proc.stdout.strip().replace(chr(10), ' | ')}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--height", type=int, default=360)
    ap.add_argument("--fmt", default="mp4")
    ap.add_argument("--skip-audio", action="store_true")
    args = ap.parse_args()

    log(f"ffmpeg: {config.find_ffmpeg()}")
    results: list[tuple[str, bool]] = []

    results.append(("无效链接", test_bad_url()))
    info = test_parse(args.url)
    if info is None:
        log("\n解析失败，后续下载测试跳过。")
        return 1

    results.append((f"视频下载 {args.height}p/{args.fmt}", run_download(info, args.height, args.fmt)))
    if not args.skip_audio:
        results.append(("音频下载 mp3", run_download(info, None, "mp3")))

    log("\n===== 汇总 =====")
    for name, ok in results:
        log(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
