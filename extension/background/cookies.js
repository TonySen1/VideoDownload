/**
 * 把浏览器里的登录 cookie 转交给本地 VideoDownload 程序。
 *
 * 为什么需要这一步：Chrome / Edge 127+ 对 cookie 启用了 App-Bound Encryption
 * （`v20` 前缀），yt-dlp 从磁盘读取会失败（Failed to decrypt with DPAPI）。
 * 扩展通过 chrome.cookies 拿到的是解密后的值，是当前唯一稳定的取法。
 *
 * 责任边界：
 *   - 只取白名单视频站点及其登录依赖域；
 *   - 只发往 127.0.0.1 / localhost（manifest 的 host_permissions 限定）；
 *   - 不落盘、不打印、不写日志，取到即发。
 */

// 与 app/cookies.py 的 ALLOWED_DOMAINS 必须保持一致
export const ALLOWED_DOMAINS = [
  "youtube.com",
  "youtu.be",
  "google.com",
  "vimeo.com",
  "instagram.com",
  "facebook.com",
  "twitter.com",
  "x.com",
  "bilibili.com",
  "stashmedia.tv",
  "tiktok.com",
];

/**
 * 各站点需要额外采集的子域。
 * 例如 YouTube 的登录态依赖 accounts.google.com 下的 __Host-* 系列。
 */
const EXTRA_HOSTS = ["accounts.google.com"];

const PORTS = [6811, 6822, 6833, 6844, 6855];

function isAllowed(domain) {
  const host = String(domain || "").replace(/^\./, "").toLowerCase();
  if (!host) return false;
  return ALLOWED_DOMAINS.some((d) => host === d || host.endsWith("." + d));
}

/**
 * 收集所有白名单域下的 cookie。
 *
 * 三种查询取并集，缺一不可：
 *   1. getAll({domain})        —— 整个域树，包括 hostOnly=false 的父域 cookie
 *   2. getAll({url: 裸域})      —— 覆盖 .domain 形式
 *   3. getAll({url: www.域})    —— 覆盖 hostOnly 的子域 cookie
 *
 * 只做 1 会漏掉 hostOnly 条目，只做 2/3 会漏掉非 www 子域。
 * SID / HSID / APISID 这类核心认证 cookie 正好落在两者交界处。
 */
export async function collectCookies() {
  const seen = new Set();
  const out = [];

  const add = (c) => {
    if (!isAllowed(c.domain)) return;

    const key = `${c.domain}\t${c.path}\t${c.name}`;
    const prev = seen.has(key) ? out.find((x) => x.key === key) : null;
    if (prev) {
      // 同名同路径重复时保留 secure 的那条，它才真正参与登录态
      if (!prev.secure && c.secure) {
        prev.value = c.value;
        prev.secure = true;
        prev.hostOnly = c.hostOnly;
        prev.expirationDate = c.expirationDate;
      }
      return;
    }

    seen.add(key);
    out.push({
      key,
      domain: c.domain,
      name: c.name,
      value: c.value,
      path: c.path,
      secure: c.secure,
      hostOnly: c.hostOnly,
      expirationDate: c.expirationDate,
    });
  };

  const queries = [];
  for (const domain of ALLOWED_DOMAINS) {
    queries.push({ domain });
    queries.push({ url: `https://${domain}/` });
    queries.push({ url: `https://www.${domain}/` });
  }
  for (const host of EXTRA_HOSTS) {
    queries.push({ url: `https://${host}/` });
  }

  for (const query of queries) {
    let list = [];
    try {
      list = await chrome.cookies.getAll(query);
    } catch {
      continue;
    }
    for (const c of list) add(c);
  }

  // 内部去重用的 key 不往外发
  return out.map(({ key, ...rest }) => rest);
}

/** 把 cookies 投递给桌面程序。返回 {ok, msg, count}。 */
export async function sendCookies(cookies) {
  const body = JSON.stringify({ cookies, source: "extension" });

  for (const port of PORTS) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const resp = await fetch(`http://127.0.0.1:${port}/cookies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        signal: controller.signal,
      });
      const data = await resp.json().catch(() => null);
      if (data && data.app && data.app !== "videosdown") continue;
      if (resp.ok && data && data.ok) {
        return { ok: true, msg: data.msg || "已同步", count: cookies.length };
      }
      return {
        ok: false,
        msg: (data && data.msg) || "程序拒绝",
        count: cookies.length,
      };
    } catch {
      // 端口没监听，试下一个
    } finally {
      clearTimeout(timer);
    }
  }
  return { ok: false, msg: "未连接到 VideoDownload，请先启动程序", count: cookies.length };
}

/** 采集 + 发送，供弹窗与后台复用。 */
export async function exportCookies() {
  const cookies = await collectCookies();
  if (!cookies.length) {
    return { ok: false, msg: "没有找到可导出的登录 cookie", count: 0 };
  }
  return sendCookies(cookies);
}
