// Exercise the real submit handler without network calls or local AI inference.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("templates/index.html", "utf8");
const handler = html.match(/articleSummaryForm\.addEventListener\("submit", async \(event\) => \{([\s\S]*?)\n    \}\);\n    articleReportDate/)[1];

async function checkRun(fail) {
  let now = 1000;
  let finishRequest;
  const timers = new Map();
  const elapsed = { textContent: "previous run" };
  const button = {};
  const sandbox = {
    articleResetting: false, activeArticleRequest: null, articlePageLeaving: false, articlePageVersion: 0,
    articleActiveRequestKey: "active", articleRunController: null, AbortController,
    crypto: { randomUUID: () => "11111111-1111-1111-1111-111111111111" },
    sessionStorage: { setItem: () => {}, removeItem: () => {} },
    forgetActiveArticleRequest: () => { sandbox.activeArticleRequest = null; },
    articleElapsedTime: elapsed,
    articleSummaryButton: button,
    articleCopyButton: {},
    articleReportDate: { value: "2026-09-24" },
    performance: { now: () => now },
    window: {
      setInterval: (callback, delay) => {
        const id = timers.size + 1;
        timers.set(id, { callback, delay });
        return id;
      },
      clearInterval: id => timers.delete(id),
    },
    fetch: url => url.startsWith("/article-draft-status/") ? Promise.resolve({ ok: true }) : new Promise(resolve => { finishRequest = resolve; }),
    readJson: async () => ({ jobId: "test", status: "completed", sections: {}, result: { sections: {} } }),
    emptyArticleResult: () => {}, clearArticleCopyFeedback: () => {},
    saveArticleDraft: () => {},
    renderArticleSummary: () => {},
    updateArticleProgress: () => {},
    setArticleDraftStatus: () => {},
    buildArticleBriefing: () => "",
    currentArticleDraft: null,
    articleKinds: ["us", "australia", "domestic"],
  };
  vm.createContext(sandbox);
  const run = vm.runInContext(`(async (event) => {${handler}\n})`, sandbox);
  const pending = run({ preventDefault() {} });
  assert.equal(elapsed.textContent, "경과 시간 0초");
  now += 3700;
  for (const timer of timers.values()) {
    if (timer.delay === 1000) timer.callback();
  }
  assert.equal(elapsed.textContent, "경과 시간 3초");
  finishRequest({ ok: !fail, status: fail ? 400 : 202 });
  await pending;
  assert.equal(elapsed.textContent, "총 소요 3초");
  assert.equal(timers.size, 0, "both timers stop on success and failure");
  assert.equal(button.disabled, false);
  // A second submission starts from zero, rather than retaining the old duration.
  const second = run({ preventDefault() {} });
  assert.equal(elapsed.textContent, "경과 시간 0초");
  finishRequest({ ok: true });
  await second;
  assert.equal(timers.size, 0);
}

(async () => {
  await checkRun(false);
  await checkRun(true);
  console.log("Article elapsed timer: success, failure, and reset OK");
})().catch(error => { console.error(error); process.exitCode = 1; });
