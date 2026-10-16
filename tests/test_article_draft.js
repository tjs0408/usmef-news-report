// Exercise the actual async submit/clipboard functions without upstream calls.
const assert = require("node:assert/strict"), fs = require("node:fs"), vm = require("node:vm");
const html = fs.readFileSync("templates/index.html", "utf8");
const handler = html.match(/articleSummaryForm\.addEventListener\("submit", async \(event\) => \{([\s\S]*?)\n    \}\);\n    articleReportDate/)[1];
const specs = [
  ["us", "소 - 미국"], ["australia", "소 - 호주"], ["domestic", "소 - 국내기사"],
  ["us_pork", "돼지 - 미국"], ["eu_pork", "돼지 - EU(독일)"], ["domestic_pork", "돼지 - 국내기사"],
  ["us_chicken", "닭 - 미국"], ["brazil_chicken", "닭 - 브라질"], ["domestic_chicken", "닭 - 국내기사"],
  ["us_egg", "계란 - 미국"], ["japan_egg", "계란 - 일본"], ["domestic_egg", "계란 - 국내기사"],
].map(([key, label]) => ({ key, label, domestic: key.startsWith("domestic") }));

async function checkRun(failure, allReady = false) {
  let now = 1000, finishRequest, id = 0, polls = 0;
  const calls = [], timers = new Map(), renders = [], statuses = [], progress = [];
  const elapsed = { textContent: "previous run" }, button = {};
  const result = { sections: { us: { summary: "소고기 공급 감소로 가격 상승" } }, message: "done" };
  if (allReady) result.sections = Object.fromEntries(specs.map(spec => [spec.key, {summary: "원문 기반 유효한 초안"}]));
  const stored = new Map();
  const sandbox = {
    articleResetting: false, activeArticleRequest: null, articlePageLeaving: false, articlePageVersion: 0,
    articleActiveRequestKey: "active", articleRunController: null, AbortController,
    crypto: { randomUUID: () => "11111111-1111-1111-1111-111111111111" },
    sessionStorage: { setItem: (key, value) => stored.set(key, value), removeItem: key => stored.delete(key) },
    forgetActiveArticleRequest: () => { sandbox.activeArticleRequest = null; stored.clear(); },
    articleElapsedTime: elapsed, articleSummaryButton: button, articleCopyButton: {},
    articleReportDate: { value: "2026-10-01" }, performance: { now: () => now },
    window: {
      setInterval: (callback, delay) => { timers.set(++id, { callback, delay }); return id; },
      clearInterval: id => timers.delete(id),
      setTimeout: callback => { now += 1000; callback(); return ++id; },
    },
    fetch: (url, options) => {
      calls.push({ url, options });
      if (url === "/start-article-draft") return new Promise(resolve => { finishRequest = resolve; });
      polls++;
      if (failure === "poll") return Promise.resolve({ ok: false, payload: { error: "poll failed" } });
      if (failure === "worker") return Promise.resolve({ ok: true, payload: { status: "failed", message: "worker failed", progress: 30, sections: result.sections } });
      if (polls % 2 === 1) return Promise.resolve({ ok: true, payload: { status: "running", progress: 40, stage: 3, message: "요약 중", sections: result.sections } });
      return Promise.resolve({ ok: true, payload: { status: "completed", progress: 100, stage: 3, sections: result.sections, result } });
    },
    readJson: async response => response.payload,
    emptyArticleResult: () => {}, saveArticleDraft: () => {}, clearArticleCopyFeedback: () => {},
    renderArticleSummary: payload => { renders.push(payload); sandbox.currentArticleDraft = payload; },
    updateArticleProgress: (...values) => progress.push(values),
    setArticleDraftStatus: (...values) => statuses.push(values),
    buildArticleBriefing: payload => payload?.sections?.us?.summary || "",
    currentArticleDraft: { sections: { us: { summary: "old date" } } },
    articleKinds: specs.map(spec => spec.key),
  };
  vm.createContext(sandbox);
  const run = vm.runInContext(`(async (event) => {${handler}\n})`, sandbox);
  const pending = run({ preventDefault() {} });
  assert.equal(elapsed.textContent, "경과 시간 0초");
  assert.equal(sandbox.currentArticleDraft, null, "stale previous-date summary is cleared");
  now += 3700;
  for (const timer of timers.values()) if (timer.delay === 1000) timer.callback();
  assert.equal(elapsed.textContent, "경과 시간 3초");
  assert.equal(stored.size, 1, "ownership is persisted before start response");
  finishRequest({ ok: failure !== "start", status: failure === "start" ? 409 : 202, payload: failure === "start" ? { error: "start failed" } : { jobId: "test-job" } });
  await pending;
  assert.match(elapsed.textContent, /^총 소요 \d+초$/);
  assert.equal(timers.size, 0);
  assert.equal(button.disabled, false);
  assert.equal(sandbox.articleReportDate.disabled, false);
  assert.equal(calls[0].url, "/start-article-draft");
  assert.equal(JSON.parse(calls[0].options.body).requestId.length, 32);
  assert.equal(stored.size, failure === "poll" ? 1 : 0, "ambiguous network failures retain ownership for cancellation");
  if (!failure) {
    assert.equal(renders.length, 2, "partial results then final results");
    assert.equal(progress.at(-1)[3], allReady ? "completed" : "partial", "one draft is not a fully successful run");
    assert.equal(statuses.at(-1)[1], allReady ? "is-complete" : "is-partial");
    assert.equal(progress.at(-1)[0], 100);
    assert.equal(sandbox.articleCopyButton.disabled, false);
  } else {
    assert.equal(statuses.at(-1)[1], "is-error");
    assert.equal(sandbox.articleCopyButton.disabled, failure !== "worker", "partial output remains copyable on worker failure");
  }
}

function checkBriefing() {
  const code = html.match(/function buildArticleBriefing\(payload\) \{([\s\S]*?)\n    \}\n\n    async function copyArticleBriefing/)[1];
  const sandbox = { articleSpecs: specs };
  vm.createContext(sandbox);
  sandbox.URL = URL;
  vm.runInContext(html.slice(html.indexOf("    function normalizeArticleMetadata("), html.indexOf("    function emptyArticleResult(")), sandbox);
  const build = vm.runInContext(`(payload => {${code}\n})`, sandbox);
  const sections = Object.fromEntries(specs.map(spec => [spec.key, {
    summary: `${spec.label} 공급 감소로 가격 상승`,
    article: { title: `${spec.label} 기사`, publisher: "매체", publishedDate: "2026-10-01" },
  }]));
  const text = build({ sections });
  assert.equal((text.match(/○ /g) || []).length, 12);
  assert.equal((text.match(/- \(현지동향\)/g) || []).length, 8);
  assert.equal((text.match(/∙ “/g) || []).length, 4);
  assert.match(text, /\(매체,10\.1\.\)/);
  assert(text.indexOf("○ 소 - 미국") < text.indexOf("○ 돼지 - 미국"));
  assert.equal(build({ sections: { domestic_egg: { summaryError: "failed" } } }), "");
}

(async () => {
  for (const failure of [null, "start", "poll", "worker"]) await checkRun(failure);
  await checkRun(null, true);
  checkBriefing();
  console.log("Article draft: async partial results, failures, timing and 12-section copying OK");
})().catch(error => { console.error(error); process.exitCode = 1; });
