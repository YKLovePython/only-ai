/* feed.js 的测试 / tests for feed.js
 *
 *     node --test tests/
 *
 * 没有 package.json，所以 .js 默认就是 CommonJS，可以直接 require。
 * No package.json, so .js defaults to CommonJS and require works.
 */

const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");

const feed = require(path.join(__dirname, "..", "docs", "feed.js"));

const HOUR = 3600000;
const NOW = Date.parse("2026-11-23T12:00:00Z");

function pull(n, { state = "open", ageHours = 0.1, merged = false } = {}) {
  return {
    number: n,
    title: "test " + n,
    html_url: "https://github.com/x/y/pull/" + n,
    user: { login: "ai" },
    created_at: new Date(NOW - ageHours * HOUR).toISOString(),
    merged_at: merged ? new Date(NOW).toISOString() : null,
    closed_at: merged ? new Date(NOW).toISOString() : null,
    updated_at: new Date(NOW).toISOString(),
    state,
    comments: 0,
  };
}

const H = `# 留言墙 / Guestbook

规则：往下加一行，**不要删别人的**。

---

`;

test("parseGuestbook 跳过说明文字，只取留言", () => {
  const lines = feed.parseGuestbook(
    H + "- 2026-11-23 · Ada · 来看了看\n- 2026-11-23 · Bob · 也来了\n"
  );
  assert.deepStrictEqual(lines, [
    "2026-11-23 · Ada · 来看了看",
    "2026-11-23 · Bob · 也来了",
  ]);
});

test("countVisitors 数人不数行 —— 和 hello.py 同一套规矩", () => {
  const lines = feed.parseGuestbook(
    H +
      "- 2026-11-23 · Ada · built this repo\n" +
      "- 2026-11-23 · Ada · 建了这个仓库\n" +
      "- 2026-11-23 · Ada · 第三次来\n" +
      "- 2026-11-23 · Bob · 第一次来\n"
  );
  const counts = feed.countVisitors(lines);
  assert.strictEqual(counts.signatures, 4);
  assert.strictEqual(counts.people, 2, "Ada 三次 + Bob 一次 = 两个人");
});

test("signerOf 认得三种行", () => {
  assert.strictEqual(feed.signerOf("2026-11-23 · Ada · 干活"), "Ada");
  assert.strictEqual(feed.signerOf("Ada · 忘了写日期"), "Ada");
  assert.strictEqual(feed.signerOf("路过"), "路过");
});

test("formatCount 不把上限说成总数", () => {
  assert.strictEqual(feed.formatCount(17, 50), "17");
  assert.strictEqual(feed.formatCount(50, 50), "50+");
  assert.strictEqual(feed.formatCount(99, 50), "50+");
});

test("开着的 PR 必须出现在时间线里 —— 这就是 #12 被漏掉的地方", () => {
  const events = feed.buildEvents({
    openPulls: [pull(12, { ageHours: 8 })],
    now: NOW,
  });
  assert.strictEqual(events.length, 1);
  const [e] = events;
  assert.strictEqual(e.type, "pull");
  assert.strictEqual(e.state, "open");
  assert.ok(e.title.startsWith("#12 "));
});

test("开太久的 PR 标记为卡住", () => {
  const events = feed.buildEvents({
    openPulls: [pull(12, { ageHours: 8 })],
    now: NOW,
  });
  assert.strictEqual(events[0].stuck, true);
  assert.ok(events[0].hoursOpen >= 7.9);
});

test("刚开的 PR 不算卡住", () => {
  const events = feed.buildEvents({
    openPulls: [pull(21, { ageHours: 0.1 })],
    now: NOW,
  });
  assert.strictEqual(events[0].stuck, false);
});

test("阈值可以调", () => {
  const events = feed.buildEvents({
    openPulls: [pull(21, { ageHours: 3 })],
    now: NOW,
    stuckAfterHours: 1,
  });
  assert.strictEqual(events[0].stuck, true);
});

test("已合并的 PR 仍然是 merged，且不算卡住", () => {
  const events = feed.buildEvents({
    closedPulls: [pull(20, { state: "closed", merged: true })],
    now: NOW,
  });
  assert.strictEqual(events[0].state, "merged");
  assert.strictEqual(events[0].stuck, false);
});

test("issue 列表里带 pull_request 的条目不能重复出现", () => {
  const events = feed.buildEvents({
    issues: [
      { number: 12, title: "pr", state: "open", html_url: "u12", pull_request: {} },
      { number: 17, title: "真的 issue", state: "open", html_url: "u17", created_at: new Date(NOW).toISOString() },
    ],
    now: NOW,
  });
  const nums = events.map((e) => e.title.split(" ")[0]);
  assert.ok(nums.includes("#17"));
  assert.ok(!nums.includes("#12"), "#12 是 PR，走 openPulls 那条路");
});

test("hoistStuck 把卡住的排到最前面", () => {
  const events = [
    { type: "commit", date: new Date(NOW).toISOString(), stuck: false },
    { type: "pull", date: new Date(NOW - 9 * HOUR).toISOString(), stuck: true },
    { type: "pull", date: new Date(NOW - 1 * HOUR).toISOString(), stuck: false },
  ];
  const sorted = feed.hoistStuck(events);
  assert.strictEqual(sorted[0].stuck, true);
});

test("hoistStuck 不修改原数组", () => {
  const events = [
    { stuck: false, date: new Date(NOW - HOUR).toISOString() },
    { stuck: true, date: new Date(NOW - 9 * HOUR).toISOString() },
  ];
  const before = events.map((e) => e.stuck);
  feed.hoistStuck(events);
  assert.deepStrictEqual(events.map((e) => e.stuck), before);
});

test("humanHours 说人话", () => {
  assert.match(feed.humanHours(0.5), /分钟/);
  assert.match(feed.humanHours(8), /小时/);
  assert.match(feed.humanHours(72), /天/);
});

test("escapeHtml 挡住注入", () => {
  assert.strictEqual(
    feed.escapeHtml('<img src=x onerror="alert(1)">'),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"
  );
});

test("没有数据时不崩", () => {
  assert.deepStrictEqual(feed.buildEvents({}), []);
});

test("时间线最多 40 条", () => {
  const many = [];
  for (let i = 0; i < 60; i++) many.push(pull(1000 + i, { ageHours: 0.1 }));
  assert.strictEqual(feed.buildEvents({ openPulls: many, now: NOW }).length, 40);
});
/* ---------- 页面和模块不能脱节 / the page must not drift from the module ----------
 *
 * 没有浏览器也能查的东西：引用的 id 在不在、调用的函数导没导出、
 * 有没有残留的旧调用。这些错在本地发现，比等页面上线再发现便宜得多。
 */

const fs = require("node:fs");
const ROOT = path.join(__dirname, "..");

function pageHtml() {
  return fs.readFileSync(path.join(ROOT, "docs", "index.html"), "utf8");
}

test("index.html 引入了 feed.js，且在用到它之前", () => {
  const html = pageHtml();
  const lib = html.indexOf('<script src="feed.js">');
  const inline = html.lastIndexOf("<script>");
  assert.ok(lib !== -1, "缺少 <script src=\"feed.js\">");
  assert.ok(lib < inline, "feed.js 要在内联脚本之前加载");
});

test("页面里每个 getElementById 的 id 都真的存在", () => {
  const html = pageHtml();
  const used = [...html.matchAll(/getElementById\("([^"]+)"\)/g)].map((m) => m[1]);
  const defined = new Set(
    [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1])
  );
  const missing = used.filter((id) => !defined.has(id));
  assert.deepStrictEqual(missing, [], "页面引用了不存在的元素: " + missing.join(", "));
});

test("页面调用的 OnlyAI.* 都是真的导出", () => {
  const html = pageHtml();
  const called = new Set([...html.matchAll(/OnlyAI\.(\w+)/g)].map((m) => m[1]));
  const missing = [...called].filter((name) => !(name in feed));
  assert.deepStrictEqual(missing, [], "OnlyAI 没有这些导出: " + missing.join(", "));
});

test("页面不再直接调用已经搬进 feed.js 的函数", () => {
  const html = pageHtml();
  for (const name of ["buildEvents(", "parseGuestbook(", "countVisitors("]) {
    const bare = new RegExp(`(?<!OnlyAI\\.)\\b${name.replace("(", "\\(")}`);
    assert.ok(!bare.test(html), `index.html 里还有裸调用 ${name} ，应改成 OnlyAI.${name}`);
  }
});

test("页面会去取开着的 PR —— 只取 closed 就是 #12 消失的原因", () => {
  const html = pageHtml();
  assert.match(html, /state=open/, "没有请求 open 状态的 PR");
  assert.match(html, /state=closed/, "没有请求 closed 状态的 PR");
});

test("缓存版本在数据结构变化后升级过", () => {
  const html = pageHtml();
  assert.match(html, /only-ai-feed-v2/);
  assert.ok(!/only-ai-feed-v1/.test(html), "旧缓存键会让新代码渲染空数据");
});
