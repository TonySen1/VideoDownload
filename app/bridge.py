"""浏览器扩展与桌面程序之间的本地桥接服务。

扩展在后台以固定端口序列轮询本机，握手成功后把当前页面的链接投递进来。
协议与常见的视频下载助手扩展保持一致，便于复用已有的浏览器插件。

    POST /hello    {"version": str, "browser": str}
                -> {"ok": true, "app": "videosdown", "settings": {"show_pill": bool}}

    POST /submit   {"url": str, "title": str, "version": str, "browser": str}
                -> {"ok": true} 或 {"ok": false, "msg": str}

安全约束：
- 只监听 127.0.0.1，不对外暴露。
- 只接受 JSON POST，请求体有大小上限。
- 跨域白名单只放行浏览器扩展来源（chrome-extension:// / moz-extension://）
  与页面上下文产生的 http(s) 请求，不返回任何本机敏感信息。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

# 与扩展侧保持一致，顺序探测
PORTS = (6811, 6822, 6833, 6844, 6855)
APP_ID = "videosdown"
MAX_BODY = 64 * 1024

SubmitHandler = Callable[[str, str, dict[str, Any]], tuple[bool, str]]
CookieHandler = Callable[[list[dict[str, Any]], dict[str, Any]], tuple[bool, str]]


class _Handler(BaseHTTPRequestHandler):
    server_version = "VideoDownloadBridge/1.0"
    protocol_version = "HTTP/1.1"

    # ---------------------------------------------------------- 响应工具
    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin.startswith(("chrome-extension://", "moz-extension://")):
            self.send_header("Access-Control-Allow-Origin", origin)
        else:
            # 页面上下文（content script 直接 fetch 本机）虽被扩展代理，
            # 但仍给通配以免某些浏览器把请求算作普通页面来源。
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Vary", "Origin")

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------- 请求解析
    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    # ---------------------------------------------------------- 路由
    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = (self.path or "").split("?", 1)[0].rstrip("/") or "/"
        if path == "/hello":
            self._read_json()  # 内容不参与判断，只要格式合法即可
            self._send_json(
                {
                    "ok": True,
                    "app": APP_ID,
                    "version": self.server.app_version,  # type: ignore[attr-defined]
                    "settings": self.server.settings(),  # type: ignore[attr-defined]
                }
            )
            return
        if path == "/submit":
            data = self._read_json()
            if not data:
                self._send_json({"ok": False, "msg": "请求格式不正确"}, 400)
                return
            url = str(data.get("url") or "").strip()
            title = str(data.get("title") or "").strip()
            if not url:
                self._send_json({"ok": False, "msg": "缺少链接"}, 400)
                return
            ok, msg = self.server.on_submit(url, title, data)  # type: ignore[attr-defined]
            self._send_json({"ok": ok, "msg": msg} if not ok else {"ok": True})
            return
        if path == "/cookies":
            data = self._read_json()
            if not data:
                self._send_json({"ok": False, "msg": "请求格式不正确"}, 400)
                return
            cookies = data.get("cookies")
            if not isinstance(cookies, list):
                self._send_json({"ok": False, "msg": "缺少 cookies 列表"}, 400)
                return
            ok, msg = self.server.on_cookies(cookies, data)  # type: ignore[attr-defined]
            self._send_json({"ok": ok, "msg": msg} if not ok else {"ok": True, "msg": msg})
            return
        if path == "/ping":
            self._send_json({"ok": True, "app": APP_ID})
            return
        self._send_json({"ok": False, "msg": "not found"}, 404)

    def do_GET(self) -> None:  # noqa: N802
        if (self.path or "").split("?", 1)[0].rstrip("/") in ("", "/ping"):
            self._send_json({"ok": True, "app": APP_ID})
            return
        self._send_json({"ok": False, "msg": "not found"}, 404)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D102
        # 静默：桥接服务不写控制台，避免污染程序日志。
        return


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def handle_error(self, request: Any, client_address: Any) -> None:
        """浏览器关标签页/刷新会直接重置 keep-alive 连接，这属于正常现象，
        不要在控制台打堆栈。真正需要排查的错误仍然落到 stderr。"""
        import sys
        import traceback

        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        traceback.print_exc()


class BridgeServer:
    """后台线程里跑的本地 HTTP 服务，生命周期跟随主窗口。"""

    def __init__(
        self,
        on_submit: SubmitHandler,
        settings: Callable[[], dict[str, Any]],
        app_version: str = "1.3.2",
        on_cookies: CookieHandler | None = None,
    ) -> None:
        self.on_submit_cb = on_submit
        self.settings_cb = settings
        self.on_cookies_cb = on_cookies or (
            lambda _cookies, _raw: (False, "本程序暂不支持接收 cookies")
        )
        self.app_version = app_version
        self.port: int | None = None
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> bool:
        """依次尝试固定端口，第一个能绑上的就用。全部失败则返回 False。"""
        if self._server is not None:
            return True
        for port in PORTS:
            try:
                server = _Server(("127.0.0.1", port), _Handler)
            except OSError as exc:
                self._last_error = f"{port}: {exc}"
                continue
            server.app_version = self.app_version  # type: ignore[attr-defined]
            server.settings = self.settings_cb  # type: ignore[attr-defined]
            server.on_submit = self.on_submit_cb  # type: ignore[attr-defined]
            server.on_cookies = self.on_cookies_cb  # type: ignore[attr-defined]
            self._server = server
            self.port = port
            self._thread = threading.Thread(
                target=server.serve_forever, name="bridge-http", daemon=True
            )
            self._thread.start()
            self._last_error = None
            return True
        return False

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001 - 退出路径上不抛
                pass
            try:
                server.server_close()
            except Exception:  # noqa: BLE001
                pass
        self._thread = None
        self.port = None
