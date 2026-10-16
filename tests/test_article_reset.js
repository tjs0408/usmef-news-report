// Exercise the real reload handlers; no network, browser storage access or AI.
const assert = require("node:assert/strict"), fs = require("node:fs"), vm = require("node:vm");
const html = fs.readFileSync("templates/index.html", "utf8");
const lifecycle = html.slice(html.indexOf("    let currentArticleDraft = null;"), html.indexOf("    function defaultArticleReportDate()"));
const handler = html.match(/articleSummaryForm\.addEventListener\("submit", async \(event\) => \{([\s\S]*?)\n    \}\);\n    articleReportDate/)[1];
const stored = new Map();
const response = (payload, status = 200) => ({ payload, status, ok: status < 400 });

function page(fetch) {
  const events = new Map(), timers = new Map(), updates = [], rendered = [], beacons = [];
  const sandbox = {
    AbortController, Blob, crypto: { randomUUID: () => "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" },
    sessionStorage: {
      getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value), removeItem: key => stored.delete(key),
    },
    window: {
      addEventListener: (name, listener) => events.set(name, listener),
      setInterval: (fn, delay) => { const id = Symbol(); timers.set(id, { fn, delay }); return id; },
      clearInterval: id => timers.delete(id), setTimeout: fn => { fn(); },
    },
    navigator: { sendBeacon: (url, blob) => { beacons.push({ url, blob }); return true; } },
    articleActiveRequestKey: "active", articleKinds: ["us", "us_pork"],
    articleSummaryButton: { disabled: false }, articleCopyButton: { classList: { remove() {} }, removeAttribute() {} },
    articleCopyFeedback: {}, articleReportDate: { value: "2026-10-01" },
    articleElapsedTime: {}, articleProgress: {}, performance: { now: () => 0 },
    updateArticleProgress: (...values) => updates.push(values), setArticleDraftStatus: () => {}, emptyArticleResult: () => {},
    fetch, readJson: async res => res.payload,
    buildArticleBriefing: payload => payload?.sections?.us?.summary || "",
    renderArticleSummary: payload => rendered.push(payload), saveArticleDraft: () => assert.fail("cancelled/old result must not be saved"),
  };
  vm.createContext(sandbox);
  vm.runInContext(lifecycle, sandbox);
  const run = vm.runInContext(`async event => {${handler}\n}`, sandbox);
  const initialize = () => vm.runInContext("resetArticleDraftScreen(); activeArticleRequest = readActiveArticleRequest(); resetPreviousArticleRequest();", sandbox);
  return { sandbox, events, timers, updates, rendered, beacons, run, initialize, context: sandbox };
}

async function flush() { for (let i = 0; i < 20; i++) await Promise.resolve(); }

async function main() {
  // Reload before the start response: still send cancel, retain ownership and
  // never poll/save the late start response (even when restored from bfcache).
  let finishStart;
  const calls = [];
  const first = page((url, options) => {
    calls.push({ url, options });
    assert.equal(url, "/start-article-draft");
    return new Promise(resolve => { finishStart = resolve; });
  });
  const pending = first.run({ preventDefault() {} });
  assert.equal(stored.size, 1);
  first.events.get("pagehide")();
  assert.equal(first.beacons[0].url, "/cancel-article-draft");
  assert.equal(JSON.parse(await first.beacons[0].blob.text()).requestId, "a".repeat(32));
  assert(calls[0].options.signal.aborted);
  finishStart(response({ jobId: "old" }, 202));
  await pending;
  assert.equal(calls.length, 1);
  assert.equal(first.rendered.length, 0);
  assert.equal(first.timers.size, 0);
  assert.equal(stored.size, 1, "reload recovery still owns request");

  // New page retries the beacon, waits for all workers to drain, shows 0 sec,
  // empty cards, disabled copy and enables a fresh start ONLY after cancelled.
  let resolveCancel;
  const secondCalls = [];
  const second = page((url, options) => {
    secondCalls.push({ url, options });
    if (url === "/cancel-article-draft") return new Promise(resolve => { resolveCancel = resolve; });
    return Promise.resolve(response({ status: "cancelled" }));
  });
  second.initialize();
  assert(second.sandbox.articleSummaryButton.disabled);
  assert.equal(second.sandbox.articleElapsedTime.textContent, "경과 시간 0초");
  resolveCancel(response({ jobId: "old", status: "cancelling" }));
  await flush();
  assert.equal(secondCalls[1].url, "/article-draft-status/old");
  assert.equal(stored.size, 0);
  assert.equal(second.sandbox.articleSummaryButton.disabled, false);
  assert.equal(second.sandbox.articleSummaryButton.textContent, "기사 찾아 초안 만들기");
  assert.equal(second.sandbox.articleCopyButton.disabled, true);
  assert.equal(second.sandbox.articleProgress.hidden, true);
  assert.equal(second.rendered.length, 0);

  // If cancellation delivery fails, never lose the token or launch another
  // worker. The next click retries cancellation, not the start endpoint.
  stored.set("active", JSON.stringify({ requestId: "b".repeat(32) }));
  let recovered = false;
  const thirdCalls = [];
  const third = page(url => {
    thirdCalls.push(url);
    return Promise.resolve(recovered ? response({ status: "cancelled" }) : response({ error: "network" }, 503));
  });
  third.initialize();
  await flush();
  assert.equal(stored.size, 1);
  assert.equal(third.sandbox.articleSummaryButton.textContent, "이전 작업 중지 다시 확인");
  recovered = true;
  await third.run({ preventDefault() {} });
  assert.deepEqual(thirdCalls, ["/cancel-article-draft", "/cancel-article-draft"]);
  assert.equal(stored.size, 0);
  assert.equal(third.sandbox.articleElapsedTime.textContent, "경과 시간 0초");

  // Beacon refusal falls back to keepalive; hidden/backgrounding never cancels.
  stored.set("active", JSON.stringify({ requestId: "c".repeat(32) }));
  const fourthCalls = [];
  const fourth = page((url, options) => { fourthCalls.push({ url, options }); return Promise.resolve(response({ status: "cancelled" })); });
  vm.runInContext("activeArticleRequest = readActiveArticleRequest();", fourth.context);
  fourth.sandbox.navigator.sendBeacon = () => false;
  fourth.events.get("pagehide")();
  assert.equal(fourthCalls[0].options.keepalive, true);
  assert.equal(fourth.events.has("visibilitychange"), false);
  stored.clear();
  console.log("Article reset: unload beacon, late start, draining, reset and network recovery OK");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
