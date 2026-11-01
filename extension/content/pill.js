/**
 * VideoDownload 助手 —— 页面悬浮按钮
 *
 * 在支持的视频站点右下角显示一个绿色胶囊，点击即把当前页面链接发送给
 * 桌面程序。按钮可以拖拽，位置按站点来源分别记忆。
 *
 * 与后台 service worker 的约定：
 *   发 {type:"submit", url, title}      -> {ok, msg?}
 *   发 {type:"get-settings"}            -> {settings:{show_pill}}
 *   收 {type:"settings", settings}
 */

(() => {
  if (window.__vdPillInjected) return;
  window.__vdPillInjected = true;

  const HOST_ID = "__vd_pill_host";
  const POS_KEY_PREFIX = "pillPos:";
  const DRAG_THRESHOLD = 4;

  const SITE_PATTERNS = [
    /^https?:\/\/(www|m|music)\.youtube\.com\/watch\?/,
    /^https?:\/\/(www|m)\.youtube\.com\/shorts\//,
    /^https?:\/\/youtu\.be\//,
    /^https?:\/\/(www\.)?vimeo\.com\/\d+/,
    /^https?:\/\/(www\.)?instagram\.com\/(p|reel|reels|tv)\//,
    /^https?:\/\/(www\.|m\.|web\.)?facebook\.com\/(watch(\?|\/|\b)|reel\/|[^\s]+\/videos\/)/,
    /^https?:\/\/(www\.)?(x|twitter)\.com\/[^\s]+\/status\/\d+/,
    /^https?:\/\/(www\.)?bilibili\.com\/video\//,
    /^https?:\/\/([^\s]+\.)?stashmedia\.tv\//,
    /^https?:\/\/(www\.)?tiktok\.com\/@[^\s]+\/video\/\d+/,
    /^https?:\/\/vm\.tiktok\.com\//,
  ];

  const isSupported = (url) => SITE_PATTERNS.some((re) => re.test(url));

  // 尺寸、间距、圆角、拖拽手感沿用参考扩展；配色换成项目主色（蓝色系），
  // 与桌面程序界面和 logo 保持一致。
  const STYLE = `
    :host { all: initial; }
    .wrap {
      position: fixed; right: 18px; bottom: 18px; z-index: 2147483646;
      display: flex; align-items: center; gap: 8px;
      font: 13px/1 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
      background: #2563eb; color: #fff;
      padding: 10px 16px; border-radius: 20px;
      box-shadow: 0 4px 14px rgba(0,0,0,.28);
      cursor: pointer; user-select: none; -webkit-user-select: none;
      opacity: .92; transition: opacity .15s, transform .15s;
    }
    .wrap:hover { opacity: 1; transform: translateY(-1px); }
    .wrap.dragging { opacity: .75; cursor: grabbing; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #93c5fd; }
    .label { white-space: nowrap; }
    .wrap.sent { background: #1d4ed8; }
    .wrap.err { background: #b91c1c; }
  `;

  const LABEL_IDLE = "用 VideoDownload 下载";
  const LABEL_SENDING = "发送中…";
  const LABEL_SENT = "已发送 ✓ 请查看 VideoDownload";

  let showPill = true;

  // ---------------------------------------------------------------- 位置记忆

  const posKey = () => POS_KEY_PREFIX + location.origin;

  async function restorePosition(el) {
    try {
      const stored = await chrome.storage.local.get(posKey());
      const pos = stored && stored[posKey()];
      if (!pos || typeof pos.left !== "number" || typeof pos.top !== "number") return;

      const width = el.offsetWidth || 180;
      const height = el.offsetHeight || 40;
      const left = Math.max(0, Math.min(pos.left, window.innerWidth - width));
      const top = Math.max(0, Math.min(pos.top, window.innerHeight - height));

      el.style.right = "auto";
      el.style.bottom = "auto";
      el.style.left = left + "px";
      el.style.top = top + "px";
    } catch {
      // 读取失败就用默认的右下角位置
    }
  }

  function savePosition(el) {
    const rect = el.getBoundingClientRect();
    try {
      chrome.storage.local.set({
        [posKey()]: { left: rect.left, top: rect.top },
      });
    } catch {
      // 存储不可用时忽略，下次仍是默认位置
    }
  }

  // ---------------------------------------------------------------- 构建 UI

  function buildPill() {
    const host = document.createElement("div");
    host.id = HOST_ID;

    const shadow = host.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = STYLE;
    shadow.appendChild(style);

    const wrap = document.createElement("div");
    wrap.className = "wrap";

    const dot = document.createElement("span");
    dot.className = "dot";

    const label = document.createElement("span");
    label.className = "label";
    label.textContent = LABEL_IDLE;

    wrap.appendChild(dot);
    wrap.appendChild(label);
    shadow.appendChild(wrap);
    document.documentElement.appendChild(host);

    restorePosition(wrap);
    bindDrag(wrap);
    bindClick(wrap, label);

    return host;
  }

  // ---------------------------------------------------------------- 拖拽

  // 拖拽与点击共用的状态：pointerup 先于 click 触发，所以用 justDragged
  // 表示「这一轮交互是拖拽，不是点击」，等下一轮交互开始时再清掉。
  let justDragged = false;

  function bindDrag(wrap) {
    wrap.addEventListener("pointerdown", (event) => {
      justDragged = false;

      const rect = wrap.getBoundingClientRect();
      const offsetX = event.clientX - rect.left;
      const offsetY = event.clientY - rect.top;
      const startX = event.clientX;
      const startY = event.clientY;

      wrap.setPointerCapture(event.pointerId);

      const onMove = (moveEvent) => {
        const moved =
          Math.max(
            Math.abs(moveEvent.clientX - startX),
            Math.abs(moveEvent.clientY - startY)
          ) > DRAG_THRESHOLD;
        if (!moved) return;

        justDragged = true;
        wrap.classList.add("dragging");
        wrap.style.right = "auto";
        wrap.style.bottom = "auto";
        wrap.style.left = Math.max(0, moveEvent.clientX - offsetX) + "px";
        wrap.style.top = Math.max(0, moveEvent.clientY - offsetY) + "px";
      };

      const onUp = () => {
        wrap.classList.remove("dragging");
        wrap.removeEventListener("pointermove", onMove);
        wrap.removeEventListener("pointerup", onUp);
        if (justDragged) savePosition(wrap);
      };

      wrap.addEventListener("pointermove", onMove);
      wrap.addEventListener("pointerup", onUp);
    });
  }

  // ---------------------------------------------------------------- 点击发送

  function bindClick(wrap, label) {
    wrap.addEventListener("click", async () => {
      if (justDragged) {
        justDragged = false;
        return;
      }

      label.textContent = LABEL_SENDING;
      let result = null;
      try {
        result = await chrome.runtime.sendMessage({
          type: "submit",
          url: location.href,
          title: document.title,
        });
      } catch {
        result = null;
      }

      const ok = Boolean(result && result.ok);
      wrap.classList.add(ok ? "sent" : "err");
      label.textContent = ok
        ? LABEL_SENT
        : "发送失败：" + ((result && result.msg) || "软件未运行或连接已关闭");

      setTimeout(() => {
        wrap.classList.remove("sent", "err");
        label.textContent = LABEL_IDLE;
      }, 2000);
    });
  }

  // ---------------------------------------------------------------- 显隐

  function update() {
    const existing = document.getElementById(HOST_ID);
    if (showPill && isSupported(location.href)) {
      if (!existing) buildPill();
    } else if (existing) {
      existing.remove();
    }
  }

  // SPA 路由切换时 URL 变了但页面没重载，需要主动检查
  for (const method of ["pushState", "replaceState"]) {
    const original = history[method];
    if (typeof original === "function") {
      history[method] = function (...args) {
        const result = original.apply(this, args);
        setTimeout(update, 60);
        return result;
      };
    }
  }
  window.addEventListener("popstate", () => setTimeout(update, 60));
  setInterval(update, 1200);

  // 后台下发设置变化时立即生效
  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg || msg.type !== "settings" || !msg.settings) return;
    showPill = msg.settings.show_pill !== false;
    update();
  });

  // 定期向后台要一次设置，防止 service worker 休眠导致推送丢失
  async function refreshSettings() {
    if (!isSupported(location.href)) return;
    try {
      const response = await chrome.runtime.sendMessage({ type: "get-settings" });
      if (response && response.settings) {
        showPill = response.settings.show_pill !== false;
        update();
      }
    } catch {
      // 后台还没就绪，等下一轮
    }
  }

  setInterval(refreshSettings, 15000);
  refreshSettings();
  update();
})();
