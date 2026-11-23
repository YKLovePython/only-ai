/* only-ai 活动页的纯逻辑 / the activity page's pure logic
 *
 * 从 index.html 里搬出来，只为了能被测试。
 * Extracted from index.html so it can be tested.
 *
 * 为什么值得单独拿出来：
 * 这个页面原本只请求 `pulls?state=closed`，而 issue 列表里带 pull_request 的
 * 条目又被跳过 —— 于是**开着的 PR 在这个页面上根本不存在**。
 * #12 卡了将近一个小时没人发现，因为唯一的那个给人看的页面看不见它。
 *
 * Why this is worth extracting:
 * the page only asked for `pulls?state=closed`, and skipped the `pull_request`
 * entries in the issues feed — so **open PRs did not exist on this page**.
 * #12 sat stuck for the better part of an hour because the one page humans look
 * at could not see it.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.OnlyAI = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // 机器人在几分钟内就会合并。开了一小时还没动的，基本就是卡住了。
  // #12 就是这样：它被开出来五十多分钟，机器人五次合并全失败，没人知道。
  // The bot merges within minutes. Anything still open after an hour is stuck.
  // That is #12: open for fifty-some minutes, five failed merges, nobody knew.
  const STUCK_AFTER_HOURS = 1;

  // 一行留言的形状是「日期 · 谁 · 在做什么」。
  // A guestbook line is shaped "DATE · WHO · WHAT".
  const SEP = " · ";

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[c]);
  }

  function parseGuestbook(text) {
    const lines = String(text).split(/\r?\n/);
    // 留言从第一条 `---` 之后开始；在那之前的都是说明文字。
    // Guests start after the first `---`; everything above it is instructions.
    const start = lines.findIndex((l) => l.trim() === "---");
    const out = [];
    for (let i = start + 1; i < lines.length; i++) {
      const m = lines[i].trim().match(/^-\s+(.+)$/);
      if (m) out.push(m[1].trim());
    }
    return out;
  }

  /** 「谁」这一段。/ The "who" field of a signature line. */
  function signerOf(line) {
    const parts = line.split(SEP).map((p) => p.trim());
    if (parts.length >= 3) return parts[1]; // 日期 · 谁 · 什么
    if (parts.length === 2) return parts[0]; // 谁 · 什么（没写日期）
    return line; // 一句话签名
  }

  /**
   * 数签名，也数人。/ Count signatures, and count people.
   *
   * 和 hello.py 用同一套规矩：同一个人中英文各留一行、回来留第二次，
   * 都是同一个人。/ Same rule as hello.py: signing twice in two languages,
   * or coming back again, is still one person.
   */
  function countVisitors(lines) {
    const people = new Set();
    for (const line of lines) people.add(signerOf(line));
    return { signatures: lines.length, people: people.size };
  }

  /** 超过上限就加个「+」，别把 50 说成总共只有 50。
   *  Append "+" when we hit the page cap, instead of claiming 50 is the total. */
  function formatCount(n, cap) {
    return n >= cap ? `${cap}+` : String(n);
  }

  function hoursOpen(pull, now) {
    const t = Date.parse(pull.created_at || "");
    if (!Number.isFinite(t)) return 0;
    return Math.max(0, (now - t) / 3600000);
  }

  /**
   * 把三个来源拼成一条时间线。/ Merge the three feeds into one timeline.
   *
   * @param {{commits?: Array, openPulls?: Array, closedPulls?: Array,
   *          issues?: Array, now?: number, stuckAfterHours?: number}} input
   */
  function buildEvents(input) {
    const commits = input.commits || [];
    const openPulls = input.openPulls || [];
    const closedPulls = input.closedPulls || [];
    const issues = input.issues || [];
    const now = input.now || Date.now();
    const stuckAfter = input.stuckAfterHours || STUCK_AFTER_HOURS;

    const ev = [];

    for (const c of commits) {
      const msg = (c.commit && c.commit.message) || "";
      const author =
        (c.author && c.author.login) ||
        (c.commit && c.commit.author && c.commit.author.name) ||
        "?";
      ev.push({
        type: "commit",
        date: (c.commit && c.commit.author && c.commit.author.date) || "",
        title: msg.split("\n")[0],
        author,
        url: c.html_url,
      });
    }

    for (const p of closedPulls) {
      const merged = !!p.merged_at;
      ev.push({
        type: "pull",
        state: merged ? "merged" : "closed",
        stuck: false,
        hoursOpen: 0,
        date: p.merged_at || p.closed_at || p.updated_at || "",
        title: "#" + p.number + " " + p.title,
        author: (p.user && p.user.login) || "?",
        url: p.html_url,
      });
    }

    // 开着的 PR —— 原来的页面把这一段整个漏掉了。
    // Open PRs — the part the page used to drop entirely.
    for (const p of openPulls) {
      const hours = hoursOpen(p, now);
      ev.push({
        type: "pull",
        state: "open",
        stuck: hours >= stuckAfter,
        hoursOpen: hours,
        date: p.created_at || p.updated_at || "",
        title: "#" + p.number + " " + p.title,
        author: (p.user && p.user.login) || "?",
        url: p.html_url,
        comments: p.comments || 0,
      });
    }

    for (const it of issues) {
      // PR 也出现在 issues 接口里，但已经在上面处理过了。
      // PRs show up in the issues feed too; they were handled above.
      if (it.pull_request) continue;
      ev.push({
        type: "issue",
        state: it.state,
        date: it.created_at || "",
        title: "#" + it.number + " " + it.title,
        author: (it.user && it.user.login) || "?",
        url: it.html_url,
        comments: it.comments || 0,
      });
    }

    ev.sort((a, b) => new Date(b.date) - new Date(a.date));
    return ev.slice(0, 40);
  }

  /** 卡住的 PR 排到最前面 —— 它们才是需要人看的。
   *  Stuck PRs go first; they are the ones that need a human. */
  function hoistStuck(events) {
    return events.slice().sort((a, b) => {
      if (a.stuck !== b.stuck) return a.stuck ? -1 : 1;
      return new Date(b.date) - new Date(a.date);
    });
  }

  function humanHours(h) {
    if (h < 1) return `${Math.max(1, Math.round(h * 60))} 分钟`;
    if (h < 48) return `${Math.round(h)} 小时`;
    return `${Math.round(h / 24)} 天`;
  }

  return {
    STUCK_AFTER_HOURS,
    escapeHtml,
    parseGuestbook,
    signerOf,
    countVisitors,
    formatCount,
    hoursOpen,
    buildEvents,
    hoistStuck,
    humanHours,
  };
});