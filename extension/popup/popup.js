/**
 * 工具栏弹窗：一键解析当前页链接、同步登录 cookie，并管理界面外观
 * （主题三档 / 悬浮标记形态 / 位置记忆）。
 *
 * 与后台 service worker 的约定不变：
 *   发 {type:"test-connection"}  -> {ok, version, browser}
 *   发 {type:"submit", url, title} -> {ok, msg?}
 *   发 {type:"export-cookies"}   -> {ok, count, msg?}
 *
 * 与内容脚本共享的设置放在 chrome.storage.local：
 *   uiTheme    "light" | "dark" | "auto"   弹窗主题（本文件读写）
 *   pillStyle  "flow" | "fab" | ...        悬浮标记形态（pill.js 读取）
 *   pillPos:<origin> {left, top}           按站点记忆的位置（pill.js 读写）
 */

const $ = (id) => document.getElementById(id);

let currentTab = null;
let siteOrigin = null;

const THEME_KEY = "uiTheme";
const STYLE_KEY = "pillStyle";
const POS_PREFIX = "pillPos:";

// ------------------------------------------------------------------ 小工具

/** 下载图标（与悬浮标记内一致的小箭头）。 */
function ICON_SVG() {
  return (
    '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M8 2v7.5"/><path d="M4.5 6.5 8 10l3.5-3.5"/><path d="M2.5 13.5h11"/></svg>'
  );
}

/** 设置一行结果文字。 */
function setResult(text, kind) {
  const el = $("result");
  el.textContent = text || "";
  el.className = "result" + (kind ? " " + kind : "");
}

// ------------------------------------------------------------------ 主题

const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

function resolveTheme(pref) {
  return pref === "auto" ? (darkQuery.matches ? "dark" : "light") : pref;
}

function applyTheme(pref) {
  document.documentElement.setAttribute("data-theme", resolveTheme(pref));
  for (const btn of $("themeSeg").querySelectorAll("button")) {
    btn.classList.toggle("active", btn.dataset.pref === pref);
  }
}

async function initTheme() {
  let pref = "auto";
  try {
    const stored = await chrome.storage.local.get(THEME_KEY);
    const value = stored && stored[THEME_KEY];
    if (value === "light" || value === "dark" || value === "auto") pref = value;
  } catch {
    // 读取失败就跟随系统
  }
  applyTheme(pref);

  $("themeSeg").addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-pref]");
    if (!btn) return;
    const next = btn.dataset.pref;
    applyTheme(next);
    chrome.storage.local.set({ [THEME_KEY]: next }).catch(() => {});
  });

  // 跟随档下，系统深浅色变化要立刻反映到弹窗
  darkQuery.addEventListener("change", async () => {
    const stored = await chrome.storage.local.get(THEME_KEY).catch(() => null);
    if ((stored && stored[THEME_KEY]) === "auto") applyTheme("auto");
  });
}

// ------------------------------------------------------------------ 标记形态

async function initStyles() {
  const grid = $("styleGrid");
  const shapeHtml = {
    flow: '<span class="mini mini-flow"><i class="m-ico"></i><span class="m-txt">下载</span></span>',
    fab: `<span class="mini mini-fab"><i class="m-ico">${ICON_SVG()}</i><span class="m-txt">下载</span></span>`,
    tab: `<span class="mini mini-tab"><span class="m-txt">下载视频</span></span>`,
    dotm: '<span class="mini mini-dotm"></span>',
    ring: '<span class="mini mini-ring"><span class="m-txt">下载</span></span>',
    card: `<span class="mini mini-card"><i class="m-ico">${ICON_SVG()}</i><span class="m-txt">下载</span></span>`,
  };
  const shapes = [
    { id: "flow", name: "胶囊" },
    { id: "fab", name: "圆钮" },
    { id: "tab", name: "侧签" },
    { id: "dotm", name: "迷你点" },
    { id: "ring", name: "环钮" },
    { id: "card", name: "卡片" },
  ];

  let active = "flow";
  try {
    const stored = await chrome.storage.local.get(STYLE_KEY);
    if (stored && shapes.some((s) => s.id === stored[STYLE_KEY])) active = stored[STYLE_KEY];
  } catch {
    // 默认胶囊
  }

  grid.innerHTML = "";
  for (const shape of shapes) {
    const card = document.createElement("button");
    card.className = "style-card" + (shape.id === active ? " active" : "");
    card.dataset.shape = shape.id;
    card.title = shape.name;
    card.innerHTML =
      '<span class="sc-preview">' + shapeHtml[shape.id] + "</span>" +
      '<span class="sc-name">' + shape.name + "</span>";
    card.addEventListener("click", () => selectShape(shape.id));
    grid.appendChild(card);
  }

  const name = (id) => (shapes.find((s) => s.id === id) || shapes[0]).name;
  $("styleValue").textContent = name(active);

  function selectShape(id) {
    for (const card of grid.children) card.classList.toggle("active", card.dataset.shape === id);
    $("styleValue").textContent = name(id);
    // 内容脚本监听 storage 变化，所有已打开的标签页即时换装
    chrome.storage.local.set({ [STYLE_KEY]: id }).catch(() => {});
  }

  const toggle = $("styleToggle");
  toggle.addEventListener("click", () => {
    const open = grid.classList.toggle("open");
    toggle.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
  });
}

// ------------------------------------------------------------------ 位置记忆

async function initPositionMemory() {
  const posKey = siteOrigin ? POS_PREFIX + siteOrigin : null;
  const siteState = $("siteState");
  const clearSite = $("clearSiteBtn");
  const clearAll = $("clearAllBtn");
  const clearAllLabel = $("clearAllLabel");

  let saved = null;
  try {
    if (posKey) {
      const stored = await chrome.storage.local.get(posKey);
      saved = stored && stored[posKey];
    }
  } catch {
    saved = null;
  }

  if (!posKey) {
    siteState.textContent = "当前页面无法记录位置";
  } else if (saved && typeof saved.left === "number" && typeof saved.top === "number") {
    siteState.textContent = `已记住 · 左 ${Math.round(saved.left)} / 上 ${Math.round(saved.top)}`;
    clearSite.disabled = false;
  } else {
    siteState.textContent = "未记录，标记显示在右下角";
  }

  clearSite.addEventListener("click", async () => {
    if (!posKey) return;
    await chrome.storage.local.remove(posKey).catch(() => {});
    clearSite.disabled = true;
    siteState.textContent = "已清除，标记回到右下角";
  });

  // 危险操作点一次变确认态，3 秒内再点才真正执行
  let armed = false;
  let timer = null;
  clearAll.addEventListener("click", async () => {
    if (!armed) {
      armed = true;
      clearAll.classList.add("confirm");
      clearAllLabel.textContent = "再点一次确认清除";
      timer = setTimeout(() => {
        armed = false;
        clearAll.classList.remove("confirm");
        clearAllLabel.textContent = "清除所有站点的位置记忆";
      }, 3000);
      return;
    }
    clearTimeout(timer);
    armed = false;
    clearAll.classList.remove("confirm");
    clearAllLabel.textContent = "清除所有站点的位置记忆";

    try {
      const all = await chrome.storage.local.get(null);
      const keys = Object.keys(all || {}).filter((k) => k.startsWith(POS_PREFIX));
      if (keys.length) await chrome.storage.local.remove(keys);
      siteState.textContent = "已清除全部记录";
      clearSite.disabled = true;
    } catch {
      siteState.textContent = "清除失败，请重试";
    }
  });
}

// ------------------------------------------------------------------ 连接状态

/** 设置头部状态胶囊。 */
function setConnection(online, detail) {
  const head = $("status");
  head.classList.toggle("online", online);
  $("statusTitle").textContent = online ? "已连接" : "未连接";
  $("statusSub").textContent = detail || (online ? "桌面程序在线" : "请先启动 VideoDownload 桌面程序");
  $("port").textContent = online ? "已连接" : "未连接";
}

// ------------------------------------------------------------------ 初始化

async function init() {
  const manifest = chrome.runtime.getManifest();
  $("version").textContent = "v" + manifest.version;

  [currentTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (currentTab) {
    $("page-title").textContent = currentTab.title || currentTab.url || "—";
    try {
      const url = new URL(currentTab.url || "");
      siteOrigin = url.origin;
      $("page-host").textContent = url.host;
    } catch {
      $("page-host").textContent = "—";
    }
  }

  // 悬浮标记显隐状态（由桌面程序下发的 show_pill 决定）
  try {
    const resp = await chrome.runtime.sendMessage({ type: "get-settings" });
    const settings = (resp && resp.settings) || {};
    $("pillState").textContent = settings.show_pill === false ? "已隐藏" : "已显示";
  } catch {
    $("pillState").textContent = "—";
  }

  // 连接状态
  setResult("正在连接程序…", "busy");
  try {
    const info = await chrome.runtime.sendMessage({ type: "test-connection" });
    if (info && info.ok) {
      setConnection(true, (info.browser || "浏览器") + " · 已连接桌面程序");
      setResult("");
    } else {
      setConnection(false);
      setResult("未连接到 VideoDownload，请先启动桌面程序。", "err");
    }
  } catch {
    setConnection(false);
    setResult("后台服务未就绪，请重新加载扩展。", "err");
  }

  initPositionMemory();
}

/** 发送当前页面链接到桌面程序。 */
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

/** 把当前站点的登录 cookie 同步给桌面程序。 */
async function onSyncCookies() {
  const btn = $("cookies-btn");
  btn.disabled = true;
  $("cookieState").textContent = "正在读取登录 cookie…";
  setResult("正在读取登录 cookies…", "busy");
  try {
    const res = await chrome.runtime.sendMessage({ type: "export-cookies" });
    if (res && res.ok) {
      $("cookieState").textContent = `已同步 ${res.count} 条 cookie`;
      setResult(`✓ 已同步 ${res.count} 条 cookies。${res.msg || ""} 现在可以下载需要登录的视频了。`, "ok");
    } else {
      $("cookieState").textContent = "同步失败，可重试";
      setResult("同步失败：" + ((res && res.msg) || "未知原因"), "err");
    }
  } catch (e) {
    $("cookieState").textContent = "同步失败，可重试";
    setResult("同步失败：" + (e.message || "后台无响应"), "err");
  } finally {
    btn.disabled = false;
  }
}

$("send-btn").addEventListener("click", onSend);
$("cookies-btn").addEventListener("click", onSyncCookies);

initTheme();
initStyles();
init();
