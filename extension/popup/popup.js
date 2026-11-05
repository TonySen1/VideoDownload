/**
 * 工具栏弹窗：一键发送当前页链接，或同步登录 cookies 给桌面程序。
 */

const $ = (id) => document.getElementById(id);

let currentTab = null;

/** 设置一行结果文字。 */
function setResult(text, kind) {
  const el = $("result");
  el.textContent = text || "";
  el.className = "result" + (kind ? " " + kind : "");
}

/** 设置连接状态灯与端口。 */
function setConnection(online, port) {
  const dot = $("status-dot");
  dot.className = "status " + (online ? "online" : "offline");
  dot.title = online ? "已连接" : "未连接";
  $("port").textContent = online ? `127.0.0.1:${port}` : "未连接";
}

async function init() {
  const manifest = chrome.runtime.getManifest();
  $("version").textContent = "v" + manifest.version;

  [currentTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (currentTab) {
    $("page-title").textContent = currentTab.title || currentTab.url || "—";
  }

  // 连接状态
  setResult("正在连接程序…", "busy");
  try {
    const info = await chrome.runtime.sendMessage({ type: "test-connection" });
    if (info && info.ok) {
      setConnection(true);
      setResult("");
    } else {
      setConnection(false);
      setResult("未连接到 VideoDownload，请先启动桌面程序。", "err");
    }
  } catch {
    setConnection(false);
    setResult("后台服务未就绪，请重新加载扩展。", "err");
  }
}

async function onSend() {
  if (!currentTab || !currentTab.url) {
    setResult("当前页面没有可用链接。", "err");
    return;
  }
  const btn = $("send-btn");
  btn.disabled = true;
  setResult("正在发送…", "busy");
  try {
    const res = await chrome.runtime.sendMessage({
      type: "submit",
      url: currentTab.url,
      title: currentTab.title,
    });
    if (res && res.ok) {
      setResult("✓ 已发送，请在 VideoDownload 中查看解析结果。", "ok");
    } else {
      setResult("发送失败：" + ((res && res.msg) || "未知原因"), "err");
    }
  } catch (e) {
    setResult("发送失败：" + (e.message || "后台无响应"), "err");
  } finally {
    btn.disabled = false;
  }
}

async function onSyncCookies() {
  const btn = $("cookies-btn");
  btn.disabled = true;
  setResult("正在读取登录 cookies…", "busy");
  try {
    const res = await chrome.runtime.sendMessage({ type: "export-cookies" });
    if (res && res.ok) {
      setResult(
        `✓ 已同步 ${res.count} 条 cookies。${res.msg || ""} 现在可以下载需要登录的视频了。`,
        "ok"
      );
    } else {
      setResult("同步失败：" + ((res && res.msg) || "未知原因"), "err");
    }
  } catch (e) {
    setResult("同步失败：" + (e.message || "后台无响应"), "err");
  } finally {
    btn.disabled = false;
  }
}

$("send-btn").addEventListener("click", onSend);
$("cookies-btn").addEventListener("click", onSyncCookies);
init();
