/**
 * VideoDownload 助手 —— 后台服务工作线程
 *
 * 职责：
 *  1. 在本机固定端口序列里找到正在运行的 VideoDownload 桌面程序；
 *  2. 把页面链接通过 HTTP POST 投递给它；
 *  3. 把桌面程序下发的设置（是否显示页面悬浮按钮）同步给所有标签页。
 *
 * 桌面端协议见 app/bridge.py：
 *   POST /hello  {version, browser} -> {ok, app:"videosdown", settings:{show_pill}}
 *   POST /submit {url, title, version, browser} -> {ok, msg?}
 */

const PORTS = [6811, 6822, 6833, 6844, 6855];
const APP_ID = "videosdown";
const HELLO_TIMEOUT_MS = 2500;
const SUBMIT_TIMEOUT_MS = 4000;
const SYNC_ALARM = "videodownload-sync";

let cachedPort = null;
let extensionSettings = { show_pill: true };
let syncing = null;

const extensionVersion = chrome.runtime.getManifest().version;

const settingsReady = chrome.storage.local
  .get("videosdownSettings")
  .then((stored) => {
    if (stored && stored.videosdownSettings) extensionSettings = stored.videosdownSettings;
  })
  .catch(() => {});

function getBrowserName() {
  const ua = navigator.userAgent;
  if (ua.includes("Edg/")) return "Edge";
  if (ua.includes("Chrome/")) return "Chrome";
  return "Chromium";
}

function candidatePorts() {
  if (!cachedPort) return PORTS;
  return [cachedPort, ...PORTS.filter((p) => p !== cachedPort)];
}

async function fetchJson(url, body, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const data = await resp.json().catch(() => null);
    return { resp, data };
  } finally {
    clearTimeout(timer);
  }
}

/** 探测桌面程序；成功后把设置广播给所有标签页。 */
async function probeApp() {
  await settingsReady;
  for (const port of candidatePorts()) {
    try {
      const { resp, data } = await fetchJson(
        `http://127.0.0.1:${port}/hello`,
        { version: extensionVersion, browser: getBrowserName() },
        HELLO_TIMEOUT_MS
      );
      if (!data || data.app !== APP_ID) continue;
      if (!resp.ok || !data.ok) continue;

      cachedPort = port;
      if (data.settings) extensionSettings = data.settings;
      chrome.storage.local.set({ videosdownSettings: extensionSettings }).catch(() => {});

      const tabs = await chrome.tabs.query({});
      for (const tab of tabs) {
        if (!tab.id || !/^https?:/.test(tab.url || "")) continue;
        chrome.tabs
          .sendMessage(tab.id, { type: "settings", settings: extensionSettings })
          .catch(() => {});
      }
      return true;
    } catch {
      // 端口没人监听或超时，继续试下一个
    }
  }
  return false;
}

/** 同一时刻只跑一次探测，避免事件叠加时并发打满端口。 */
function syncWithApp() {
  if (!syncing) {
    syncing = probeApp().finally(() => {
      syncing = null;
    });
  }
  return syncing;
}

/** 把链接投递给桌面程序。返回 {ok, msg?}。 */
async function sendToApp(url, title) {
  for (const port of candidatePorts()) {
    try {
      const { resp, data } = await fetchJson(
        `http://127.0.0.1:${port}/submit`,
        {
          url,
          title: title || "",
          version: extensionVersion,
          browser: getBrowserName(),
        },
        SUBMIT_TIMEOUT_MS
      );
      // 端口上可能是别的程序，用 app 字段排除
      if (data && data.app && data.app !== APP_ID) continue;
      if (resp.ok && data && data.ok) {
        cachedPort = port;
        syncWithApp();
        return { ok: true };
      }
      return { ok: false, msg: (data && data.msg) || "软件拒绝" };
    } catch {
      // 换下一个端口
    }
  }
  return { ok: false, msg: "请启动软件并在扩展中心开启连接" };
}

// ------------------------------------------------------------------ 生命周期

chrome.runtime.onStartup.addListener(syncWithApp);
chrome.runtime.onInstalled.addListener(syncWithApp);

chrome.alarms.create(SYNC_ALARM, { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === SYNC_ALARM) syncWithApp();
});

syncWithApp();

// ------------------------------------------------------------------ 消息

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg) return false;

  if (msg.type === "get-settings") {
    syncWithApp().then(() => sendResponse({ settings: extensionSettings }));
    return true;
  }

  if (msg.type === "test-connection") {
    syncWithApp().then((ok) =>
      sendResponse({ ok, version: extensionVersion, browser: getBrowserName() })
    );
    return true;
  }

  if (msg.type === "submit" && msg.url) {
    sendToApp(msg.url, msg.title).then(sendResponse);
    return true;
  }

  return false;
});

// ------------------------------------------------------------------ 工具栏图标

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || !tab.url) return;
  const result = await sendToApp(tab.url, tab.title);
  chrome.action.setBadgeText({ tabId: tab.id, text: result.ok ? "✓" : "!" });
  chrome.action.setBadgeBackgroundColor({
    tabId: tab.id,
    color: result.ok ? "#2563eb" : "#b91c1c",
  });
  chrome.action.setTitle({
    tabId: tab.id,
    title: result.ok ? "已发送，请在 VideoDownload 中查看解析结果" : result.msg,
  });
});
