// Actual UI week arithmetic and stale-period guards, without network or AI.
const assert = require("node:assert/strict"), fs = require("node:fs"), vm = require("node:vm");
const html = fs.readFileSync("templates/index.html", "utf8");
const functions = html.slice(html.indexOf("    function articleSearchWindow("), html.indexOf("    function setArticleDraftStatus("));
const sandbox = { articleReportDate: { value: "2026-10-01" }, articleSearchWindowLabel: {} };
vm.createContext(sandbox);
vm.runInContext(functions, sandbox);
for (const selected of ["2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03"]) {
  assert.equal(JSON.stringify(sandbox.articleSearchWindow(selected)), JSON.stringify({ start: "2026-09-27", end: "2026-10-03" }));
}
for (const [selected, start, end] of [
  ["2026-12-31", "2026-12-27", "2027-01-02"],
  ["2028-02-29", "2028-02-27", "2028-03-04"],
  ["2026-03-08", "2026-03-08", "2026-03-14"], // US DST transition
]) {
  assert.equal(JSON.stringify(sandbox.articleSearchWindow(selected)), JSON.stringify({ start, end }));
}
sandbox.updateArticleSearchWindow();
assert.match(sandbox.articleSearchWindowLabel.textContent, /2026\.09\.27~2026\.10\.03 \(일~토\)/);
assert.match(sandbox.articleSearchWindowLabel.textContent, /지정 매체·공개 뉴스 비교/);
sandbox.articleReportDate.value = "2026-10-04";
sandbox.updateArticleSearchWindow();
assert.match(sandbox.articleSearchWindowLabel.textContent, /2026\.10\.04~2026\.10\.10/);
sandbox.articleReportDate.value = "";
sandbox.updateArticleSearchWindow();
assert.equal(sandbox.articleSearchWindow(""), null);
assert.match(sandbox.articleSearchWindowLabel.textContent, /일요일~토요일/);
assert.match(sandbox.articleSearchWindowLabel.textContent, /지정 매체·공개 뉴스 비교/);

const loader = html.match(/function loadArticleDraft\(\) \{([\s\S]*?)\n    \}\n\n    function saveArticleDraft/)[1];
let rendered = 0;
let stored = { "2026-10-01": { weekStart: "2026-09-25", weekEnd: "2026-10-01" } };
Object.assign(sandbox, {
  articleKinds: ["us"], currentArticleDraft: null, articleCopyButton: {},
  readArticleDrafts: () => stored, renderArticleSummary: () => { rendered++; },
  emptyArticleResult: () => {}, setArticleDraftStatus: () => {}, clearArticleCopyFeedback: () => {},
});
sandbox.articleReportDate.value = "2026-10-01";
const load = vm.runInContext(`() => {${loader}\n}`, sandbox);
load();
assert.equal(rendered, 0, "old Friday-through-report-day draft is not reused");
stored["2026-10-01"] = { weekStart: "2026-09-27", weekEnd: "2026-10-03" };
load();
assert.equal(rendered, 1, "saved draft from the matching week can be loaded");
assert.match(html, /weekly-overseas-report-\{\{ article_style_version \}\}-sunday-week-v1/);
assert.doesNotMatch(html, /weekly-overseas-report-livestock-brief-v25-sunday-week-v1/);
assert.doesNotMatch(html, /weekly-overseas-report-livestock-brief-v23-sunday-week-v1/);
assert.match(html, /\{\{ spec\.publisher \}\}·공개 뉴스 비교 · 해당 주간 원문을 한국어로 요약/);
assert.match(html, /지정 매체와 공개 뉴스의 해당 주간 기사를 비교합니다/);
console.log("Article window: Sunday/Saturday, boundaries, UI dates and stale drafts OK");
