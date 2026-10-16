// Exercise real clipboard feedback code; no browser clipboard or upstream calls.
const assert = require("node:assert/strict"), fs = require("node:fs"), vm = require("node:vm");
const html = fs.readFileSync("templates/index.html", "utf8");
const lifecycle = html.slice(html.indexOf("    let currentArticleDraft = null;"), html.indexOf("    function readActiveArticleRequest()"));
const copyBody = html.match(/async function copyArticleBriefing\(\) \{([\s\S]*?)\n    \}\n\n    articleReportDate\.value/)[1];

function page(writeText) {
  const classes = new Set(), attributes = new Map(), timers = new Map(), statuses = [];
  let id = 0;
  const button = {
    disabled: false, textContent: "보고서 문구 복사",
    classList: { add: (...names) => names.forEach(name => classes.add(name)), remove: (...names) => names.forEach(name => classes.delete(name)) },
    setAttribute: (key, value) => attributes.set(key, value), removeAttribute: key => attributes.delete(key),
  };
  const notice = { hidden: true, textContent: "", className: "article-copy-feedback" };
  const context = {
    articleCopyButton: button, articleCopyFeedback: notice,
    window: { setTimeout: (fn, delay) => { timers.set(++id, { fn, delay }); return id; }, clearTimeout: id => timers.delete(id) },
    navigator: { clipboard: { writeText } },
    buildArticleBriefing: draft => draft?.text || "",
    setArticleDraftStatus: (...args) => statuses.push(args),
  };
  vm.createContext(context);
  vm.runInContext(lifecycle, context);
  vm.runInContext("currentArticleDraft = { text: '보고서 문구 테스트' };", context);
  const copy = vm.runInContext(`async () => {${copyBody}\n}`, context);
  const clear = () => vm.runInContext("clearArticleCopyFeedback()", context);
  const expire = () => { const pending = [...timers.values()]; timers.clear(); pending.forEach(timer => timer.fn()); };
  return { button, notice, classes, attributes, timers, statuses, copy, clear, expire, context };
}

async function main() {
  let finish, writes = 0;
  const pendingPage = page(text => { writes++; assert.equal(text, "보고서 문구 테스트"); return new Promise(resolve => { finish = resolve; }); });
  const pending = pendingPage.copy();
  assert.equal(pendingPage.button.textContent, "복사 중…");
  assert.equal(pendingPage.attributes.get("aria-busy"), "true");
  assert.equal(pendingPage.notice.hidden, false);
  assert.equal(pendingPage.timers.size, 0, "pending copy must not show success or expire");
  await pendingPage.copy();
  assert.equal(writes, 1, "double click does not start a second clipboard write");
  finish();
  await pending;
  assert.equal(pendingPage.button.textContent, "✓ 복사 완료");
  assert(pendingPage.classes.has("is-copied"));
  assert.equal(pendingPage.attributes.has("aria-busy"), false);
  assert.match(pendingPage.notice.textContent, /복사했습니다/);
  assert.equal(pendingPage.notice.hidden, false);
  assert.equal([...pendingPage.timers.values()][0].delay, 4000);
  pendingPage.button.disabled = true;
  pendingPage.expire();
  assert.equal(pendingPage.button.textContent, "보고서 문구 복사");
  assert.equal(pendingPage.button.disabled, true, "feedback timeout must not re-enable a disabled control");
  assert.equal(pendingPage.notice.hidden, true);
  assert.equal(pendingPage.classes.size, 0);

  const repeated = page(async () => {});
  await repeated.copy();
  const firstTimer = [...repeated.timers.values()][0];
  await repeated.copy();
  assert.equal(repeated.timers.size, 1);
  firstTimer.fn();
  assert.equal(repeated.notice.hidden, false, "an older timeout cannot erase the new success");
  repeated.expire();
  assert.equal(repeated.notice.hidden, true);

  for (const clipboard of [{ writeText: async () => { throw new Error("permission denied"); } }, undefined]) {
    const failed = page(async () => {});
    failed.context.navigator.clipboard = clipboard;
    await failed.copy();
    assert.equal(failed.button.textContent, "복사 실패");
    assert(failed.classes.has("is-copy-error"));
    assert.match(failed.notice.textContent, /클립보드 권한/);
    assert.equal([...failed.timers.values()][0].delay, 6000);
    assert.equal(failed.classes.has("is-copied"), false);
    failed.expire();
    assert.equal(failed.notice.hidden, true);
  }

  const empty = page(() => assert.fail("nothing should be written"));
  vm.runInContext("currentArticleDraft = null", empty.context);
  await empty.copy();
  assert.match(empty.notice.textContent, /복사할 초안이 없습니다/);
  assert(empty.classes.has("is-copy-error"));

  for (const rejected of [false, true]) {
    let finishOld;
    const stale = page(() => new Promise((resolve, reject) => { finishOld = () => rejected ? reject(new Error("old request")) : resolve(); }));
    const pendingOld = stale.copy();
    stale.clear();
    vm.runInContext("currentArticleDraft = null", stale.context);
    finishOld();
    await pendingOld;
    assert.equal(stale.notice.hidden, true, "date/reset must discard late success AND failure");
    assert.equal(stale.button.textContent, "보고서 문구 복사");
    assert.equal(stale.statuses.length, 0);
    assert.equal(stale.timers.size, 0);
  }

  const css = fs.readFileSync("static/style.css", "utf8");
  assert.match(css, /\.article-copy-feedback\s*\{[^}]*position:\s*fixed;[^}]*pointer-events:\s*none;/);
  assert.match(html, /id="article-copy-feedback"[^>]*role="status"[^>]*aria-live="polite"/);
  assert(!/scrollIntoView|window\.scroll|alert\(/.test(copyBody), "feedback must not move the user or open a blocking dialog");
  console.log("Article copy: visible pending/success/failure, repeat/reset races and accessible viewport feedback OK");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
