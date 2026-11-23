/**
 * VideoDownload 助手 —— 页面悬浮标记
 *
 * 在支持的视频站点右下角显示一个绿色悬浮标记，点击即把当前页面链接发送给
 * 桌面程序。标记共六种形态（胶囊/圆钮/侧签/迷你点/环钮/卡片），形态由
 * 弹窗「外观 → 标记形态」写入 chrome.storage.local 的 pillStyle 决定；
 * 可以拖拽，位置按站点来源分别记忆。
 *
 * 与后台 service worker 的约定：
 *   发 {type:"submit", url, title}      -> {ok, msg?}
 *   发 {type:"get-settings"}            -> {settings:{show_pill}}
 *   收 {type:"settings", settings}
 *
 * 与弹窗共享的本地存储：
 *   pillStyle           "flow" | "fab" | "tab" | "dotm" | "ring" | "card"
 *   pillPos:<origin>    {left, top}   标记被拖到的位置
 */

(() => {
  if (window.__vdPillInjected) return;
  window.__vdPillInjected = true;

  const HOST_ID = "__vd_pill_host";
  const POS_KEY_PREFIX = "pillPos:";
  const STYLE_KEY = "pillStyle";
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

  /** 六种形态的 class 后缀，顺序与弹窗网格一致。 */
  const SHAPES = ["flow", "fab", "tab", "dotm", "ring", "card"];

  const ICON_SVG =
    '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M8 2v7.5"/><path d="M4.5 6.5 8 10l3.5-3.5"/><path d="M2.5 13.5h11"/></svg>';

  // 公共基础：布局/字体/交互；形态由模板 class（style-*）决定，切换只改
  // class 不重建 DOM。六种形态：胶囊/圆钮/侧签/迷你点/环钮/卡片。
  // 动画只允许动非布局属性（opacity/transform/box-shadow/background-position/
  // max-width/margin）：拖拽定位直接改 left/top，布局属性一旦进 keyframes
  // 会在拖拽期间与定位互相覆盖。间距由 .label 的 margin 提供（wrap 不设
  // gap），配合 max-width/margin 过渡实现"hover 展开文字"。
  const STYLE = `
    :host { all: initial; }
    .wrap {
      position: fixed; right: 18px; bottom: 18px; z-index: 2147483646;
      display: flex; align-items: center;
      font: 13px/1 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
      color: #fff; background: #5bc372;
      padding: 10px 16px; border-radius: 22px;
      cursor: pointer; user-select: none; -webkit-user-select: none;
      opacity: .92; transition: opacity .15s, transform .15s, filter .15s;
    }
    .wrap:hover { opacity: 1; transform: translateY(-1px); }
    .iconbox { position: relative; display: none; align-items: center; justify-content: center; width: 22px; height: 22px; }
    .icon { font-size: 15px; font-weight: 700; line-height: 1; display: flex; }
    .ring { display: none; position: absolute; inset: -4px; border-radius: 50%;
            border: 2px solid rgba(143, 240, 182, .3); border-top-color: #8ff0b6; }
    .dot { display: none; width: 8px; height: 8px; border-radius: 50%; background: #8ff0b6; }
    .label { white-space: nowrap; margin-left: 8px; overflow: hidden;
            transition: max-width .25s ease, opacity .2s ease, margin-left .25s ease; }

    /* ---- 胶囊（默认）：主软件绿系流光渐变 ---- */
    .wrap.style-flow {
      background: linear-gradient(to right, #3a964d, #79d28c 50%, #3a964d);
      background-size: 200% 100%;
      box-shadow: 0 4px 14px rgba(0, 0, 0, .28);
      animation: vd-enter .35s ease-out, vd-flow 2.5s linear infinite;
    }
    .wrap.style-flow .dot { display: block; background: #fff;
      animation: vd-ping 2.2s cubic-bezier(0, 0, .2, 1) infinite; }
    .wrap.style-flow:hover { filter: brightness(1.1); }

    /* ---- 圆钮：主绿 FAB，品牌色光晕投影（现代 FAB 的标志性反馈） ---- */
    .wrap.style-fab {
      height: 48px; padding: 0 13px; border-radius: 24px; justify-content: center;
      background: #5bc372;
      box-shadow: 0 6px 16px rgba(91, 195, 114, .45);
      animation: vd-enter .35s ease-out;
    }
    .wrap.style-fab .iconbox { display: flex; }
    .wrap.style-fab .label { max-width: 0; opacity: 0; margin-left: 0; }
    .wrap.style-fab:hover { filter: brightness(1.06); box-shadow: 0 8px 20px rgba(91, 195, 114, .55); }
    .wrap.style-fab:hover .label { max-width: 220px; opacity: 1; margin-left: 8px; }

    /* ---- 侧签：贴屏幕右缘的竖排标签，hover 时横排展开 ----
       transform 用于垂直居中，hover 上浮写成 calc 叠加；入场动画会破坏
       居中 transform，此形态不做入场 */
    .wrap.style-tab {
      right: 0; bottom: auto; top: 50%; transform: translateY(-50%);
      writing-mode: vertical-rl;
      padding: 16px 10px; border-radius: 14px 0 0 14px;
      background: #5bc372;
      box-shadow: -4px 4px 14px rgba(91, 195, 114, .4);
      animation: none;
    }
    .wrap.style-tab .label { writing-mode: vertical-rl; margin-left: 0; letter-spacing: 3px; }
    .wrap.style-tab:hover {
      transform: translateY(calc(-50% - 1px));
      filter: brightness(1.1); padding: 16px 12px;
    }

    /* ---- 迷你点：白芯 + 品牌绿扩散环（雷达点），hover/回执胶囊化 ---- */
    .wrap.style-dotm {
      width: 20px; height: 20px; padding: 0; border-radius: 50%;
      justify-content: center; background: transparent; box-shadow: none;
      animation: vd-enter .35s ease-out;
    }
    .wrap.style-dotm .dot {
      display: block;
      width: 12px; height: 12px; background: #fff;
      animation: vd-dotping 2.4s ease-out infinite;
    }
    .wrap.style-dotm .label { max-width: 0; opacity: 0; margin-left: 0; }
    .wrap.style-dotm:hover, .wrap.style-dotm.sent, .wrap.style-dotm.err {
      width: auto; height: auto; padding: 9px 15px; border-radius: 19px;
      background: #5bc372; box-shadow: 0 4px 14px rgba(91, 195, 114, .4);
    }
    .wrap.style-dotm:hover .label,
    .wrap.style-dotm.sent .label, .wrap.style-dotm.err .label {
      max-width: 220px; opacity: 1; margin-left: 8px;
    }
    .wrap.style-dotm:hover .dot,
    .wrap.style-dotm.sent .dot, .wrap.style-dotm.err .dot { animation: none; }

    /* ---- 环钮：主绿底 + 白色渐变环（加载环语言），hover 展开 ---- */
    .wrap.style-ring {
      height: 48px; padding: 0 13px; border-radius: 24px; justify-content: center;
      background: #4aad5f;
      box-shadow: 0 4px 16px rgba(91, 195, 114, .4);
      animation: vd-enter .35s ease-out;
    }
    .wrap.style-ring .iconbox { display: flex; }
    .wrap.style-ring .ring {
      display: block;
      border: 2px solid rgba(255, 255, 255, .3); border-top-color: #fff;
      animation: vd-spin 3s linear infinite;
    }
    .wrap.style-ring .label { max-width: 0; opacity: 0; margin-left: 0; }
    .wrap.style-ring:hover { filter: brightness(1.06); }
    .wrap.style-ring:hover .label { max-width: 220px; opacity: 1; margin-left: 8px; }

    /* ---- 卡片：主软件浅色卡片语言（白底细边 + 绿色图标块 + 深色文字） ---- */
    .wrap.style-card {
      flex-direction: column; padding: 12px 16px 10px; border-radius: 10px;
      background: #fff; border: 1px solid #E4E9ED;
      box-shadow: 0 4px 14px rgba(0, 0, 0, .12);
      animation: vd-enter .35s ease-out;
    }
    .wrap.style-card .iconbox {
      display: flex; width: 26px; height: 26px;
      background: #5bc372; border-radius: 8px;
    }
    .wrap.style-card .label {
      margin-left: 0; margin-top: 6px; font-size: 12px;
      font-weight: 600; color: #2c3e50;
    }
    .wrap.style-card:hover { border-color: #5bc372; }

    @keyframes vd-enter { from { opacity: 0; transform: translateY(12px); } }
    @keyframes vd-flow { from { background-position: 0% 50%; } to { background-position: -200% 50%; } }
    @keyframes vd-ping {
      0% { box-shadow: 0 0 0 0 rgba(255, 255, 255, .6); }
      100% { box-shadow: 0 0 0 9px rgba(255, 255, 255, 0); }
    }
    @keyframes vd-dotping {
      0% { box-shadow: 0 0 0 2px rgba(91, 195, 114, .45), 0 0 0 2px rgba(91, 195, 114, .45); }
      100% { box-shadow: 0 0 0 2px rgba(91, 195, 114, .45), 0 0 0 12px rgba(91, 195, 114, 0); }
    }
    @keyframes vd-spin { to { transform: rotate(360deg); } }

    /* 拖拽中：收缩展开类形态（含回执期，拖拽时抓取点必须稳定），
       并暂停一切动画（拖拽要稳） */
    .wrap.dragging { opacity: .75; cursor: grabbing; animation-play-state: paused; }
    .wrap.dragging .label {
      max-width: 0 !important; opacity: 0 !important; margin-left: 0 !important;
    }
    .wrap.dragging .dot, .wrap.dragging .ring { animation-play-state: paused; }

    /* 回执：实色覆盖（主软件 pressed 绿 / 下载红）。属性选择器抬到与形态
       hover 规则同档特异性、再靠源顺序取胜；侧签回执横排，文字展开可见 */
    .wrap[class*="style-"].sent, .wrap[class*="style-"].err {
      border-color: transparent;
      backdrop-filter: none; -webkit-backdrop-filter: none;
      animation: none; writing-mode: horizontal-tb;
    }
    .wrap[class*="style-"].sent { background: #3a964d; }
    .wrap[class*="style-"].err { background: #F85D61; }
    .wrap[class*="style-"].sent .label, .wrap[class*="style-"].err .label {
      max-width: 260px; opacity: 1; margin-left: 8px; writing-mode: horizontal-tb;
    }
    .wrap.style-tab.sent, .wrap.style-tab.err { padding: 10px 16px; border-radius: 20px; }
    .wrap.style-tab.sent .label, .wrap.style-tab.err .label { letter-spacing: normal; }
    /* 浅色卡片是深字体系，回执换主软件浅绿/浅红底 + 同系深字 */
    .wrap.style-card.sent { background: #E8F6EB; border-color: #a9dfb6; }
    .wrap.style-card.err { background: #FDEFEF; border-color: #f5c6c6; }
    .wrap.style-card.sent .label, .wrap.style-card.err .label { margin-left: 0; }
    .wrap.style-card.sent .label { color: #2c7a4a; }
    .wrap.style-card.err .label { color: #c0453f; }

    @media (prefers-reduced-motion: reduce) {
      .wrap, .wrap[class*="style-"] { animation: none; }
      .dot, .wrap[class*="style-"] .dot, .wrap[class*="style-"] .ring { animation: none; }
      .wrap.style-flow { background-position: 50% 50%; }
    }
  `;

  const LABEL_IDLE = "用 VideoDownload 下载";
  const LABEL_SENDING = "发送中…";
  const LABEL_SENT = "已发送 ✓ 请查看 VideoDownload";

  let showPill = true;
  let pillStyle = "flow";
  let shapeReady = false;
  let wrapEl = null;
  let labelEl = null;

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

  /** 位置被弹窗清掉后，回到默认的右下角。 */
  function resetPosition(el) {
    if (!el) return;
    el.style.left = "auto";
    el.style.top = "auto";
    el.style.right = "";
    el.style.bottom = "";
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

  // ---------------------------------------------------------------- 形态

  /** 切换形态：只换 class，不重建 DOM。 */
  function applyShape(style) {
    pillStyle = SHAPES.includes(style) ? style : "flow";
    if (!wrapEl) return;
    for (const shape of SHAPES) wrapEl.classList.remove("style-" + shape);
    wrapEl.classList.add("style-" + pillStyle);
    if (labelEl) labelEl.textContent = LABEL_IDLE;
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
    wrap.className = "wrap style-" + pillStyle;

    const iconbox = document.createElement("span");
    iconbox.className = "iconbox";

    const icon = document.createElement("span");
    icon.className = "icon";
    icon.innerHTML = ICON_SVG;

    const ring = document.createElement("span");
    ring.className = "ring";

    iconbox.appendChild(icon);
    iconbox.appendChild(ring);

    const dot = document.createElement("span");
    dot.className = "dot";

    const label = document.createElement("span");
    label.className = "label";
    label.textContent = LABEL_IDLE;

    wrap.appendChild(iconbox);
    wrap.appendChild(dot);
    wrap.appendChild(label);
    shadow.appendChild(wrap);
    document.documentElement.appendChild(host);

    wrapEl = wrap;
    labelEl = label;

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
      }, ok ? 2000 : 2600);
    });
  }

  // ---------------------------------------------------------------- 显隐

  function update() {
    const existing = document.getElementById(HOST_ID);
    if (showPill && isSupported(location.href)) {
      if (!existing) {
        buildPill();
      } else if (shapeReady && wrapEl && !wrapEl.classList.contains("style-" + pillStyle)) {
        // 存储读得比首帧慢时补一次形态校正，否则刷新后会停在默认胶囊
        applyShape(pillStyle);
      }
    } else if (existing) {
      existing.remove();
      wrapEl = null;
      labelEl = null;
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

  // 弹窗改了形态或清了位置，所有已打开的页面即时跟上
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes[STYLE_KEY] && changes[STYLE_KEY].newValue) {
      applyShape(changes[STYLE_KEY].newValue);
    }
    const key = posKey();
    if (changes[key] && !changes[key].newValue) resetPosition(wrapEl);
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

  // 读一次已保存的形态，再决定首帧怎么画
  async function loadShape() {
    try {
      const stored = await chrome.storage.local.get(STYLE_KEY);
      if (stored && SHAPES.includes(stored[STYLE_KEY])) pillStyle = stored[STYLE_KEY];
    } catch {
      // 用默认胶囊
    } finally {
      shapeReady = true;
    }
    // 首帧可能已用默认形态建好标记，这里补一次校正
    applyShape(pillStyle);
  }

  loadShape();
  setInterval(refreshSettings, 15000);
  refreshSettings();
  update();
})();
