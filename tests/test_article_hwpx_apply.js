// Test actual upload/availability/download code without a browser or Office.
const assert = require("node:assert/strict"), fs = require("node:fs"), vm = require("node:vm");
const html = fs.readFileSync("templates/index.html", "utf8");
const source = html.split("    // Article HWPX integration: uploads a copy, never reruns search or AI.\n")[1].split("    // End article HWPX integration.")[0];
assert(source, "HWPX integration code exists");
const keys = ["us", "australia", "domestic", "us_pork", "eu_pork", "domestic_pork", "us_chicken", "brazil_chicken", "domestic_chicken", "us_egg", "japan_egg", "domestic_egg"];
const specs = keys.map(key => ({ key, domestic: key.startsWith("domestic") }));
const file = (name = "가격현행화.hwpx", size = 2048) => ({ name, size });
const draft = () => ({ reportDate: "2026-10-08", sections: Object.fromEntries(keys.map(key => [key, {
  status: "completed", summary: "해당 국가의 공급 변화에 따른 가격 상승과 수요 증가 전망",
  article: { title: "해외 축산물 시장 변화", publisher: "매체", publishedDate: "2026-10-07" },
}])) });
class Element {
  constructor() {
    this.hidden = false; this.classes = new Set(); this.events = new Map(); this.attrs = new Map(); this.clicks = 0;
    this.classList = {
      add: (...names) => names.forEach(name => this.classes.add(name)),
      remove: (...names) => names.forEach(name => this.classes.delete(name)),
      toggle: (name, value) => value ? this.classes.add(name) : this.classes.delete(name),
    };
  }
  setAttribute(key, value) { this.attrs.set(key, value); }
  removeAttribute(key) { this.attrs.delete(key); delete this[key]; }
  addEventListener(name, fn) { this.events.set(name, fn); }
  contains(target) { return target === this; }
  click() { this.clicks++; }
}
const response = (status = 200, payload = {}, disposition = "", contentType = "application/vnd.hancom.hwpx", blob = { size: 200 }, countHeaders = {}) => ({
  ok: status >= 200 && status < 300, status, payload,
  headers: { get: key => key.toLowerCase() === "content-type" ? contentType : key.toLowerCase() === "content-disposition" ? disposition : countHeaders[key.toLowerCase()] ?? null },
  blob: async () => blob,
});

function page(fetch = async () => response()) {
  const elements = new Map(), calls = [], created = [], revoked = [];
  const context = {
    document: { getElementById: id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); } },
    articleKinds: keys, articleSpecs: specs, currentArticleDraft: null,
    articleReportDate: { value: "2026-10-08" }, articleSummaryButton: { disabled: false },
    articleResetting: false, articlePageLeaving: false, activeArticleRequest: null,
    AbortController,
    URL: { createObjectURL: blob => { created.push(blob); return `blob:report-${created.length}`; }, revokeObjectURL: value => revoked.push(value) },
    FormData: class { constructor() { this.entries = []; } append(...entry) { this.entries.push(entry); } },
    fetch: async (url, options) => { calls.push({ url, options }); return fetch(url, options); },
    readJson: async result => result.payload,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  const get = id => elements.get(`article-hwpx-${id}`);
  const run = code => vm.runInContext(code, context);
  const choose = files => { get("file").files = files; get("file").events.get("change")(); };
  const drop = files => {
    let prevented = false;
    get("dropzone").events.get("drop")({ dataTransfer: { files }, preventDefault() { prevented = true; } });
    assert(prevented);
  };
  const load = payload => { context.currentArticleDraft = payload; run("updateArticleHwpxApplyState()"); };
  run("invalidateArticleHwpxApply(true)");
  return { context, elements, calls, created, revoked, get, run, choose, drop, load, apply: () => run("applyArticleHwpx()") };
}

async function main() {
  const upload = page();
  assert(upload.get("apply-button").disabled);
  upload.choose([file()]);
  assert(upload.get("dropzone").classes.has("has-file"));
  assert.equal(upload.get("file-name").textContent, "가격현행화.hwpx");
  assert.equal(upload.get("file-hint").textContent, "2 KB · 클릭 또는 드래그로 파일 변경");
  assert(upload.get("apply-button").disabled, "a selected file is not sufficient");
  upload.load(draft());
  assert.equal(upload.get("apply-button").disabled, false);
  const incomplete = draft(); incomplete.sections.domestic_egg.status = "summary_error";
  upload.load(incomplete);
  assert.equal(upload.get("apply-button").disabled, false, "11 accepted drafts can be applied independently");
  assert.equal(upload.run("articleHwpxReadyCount(currentArticleDraft)"), 11, "a rejected summary string must not count as accepted");
  assert.match(upload.get("availability").textContent, /기사 11개 반영 · 미완료 1개 빈칸/);
  const noTitle = draft(); delete noTitle.sections.domestic.article.title;
  upload.load(noTitle);
  assert.equal(upload.run("articleHwpxReadyCount(currentArticleDraft)"), 11, "missing domestic metadata must not count as valid");
  assert(upload.get("apply-button").disabled, "a malformed completed entry is not a terminal missing item");
  const empty = draft(); keys.forEach(key => { empty.sections[key].status = "summary_error"; });
  upload.load(empty);
  assert(upload.get("apply-button").disabled, "zero accepted drafts cannot be applied");
  assert.match(upload.get("availability").textContent, /최소 1개 완료/);
  await upload.apply(); assert.equal(upload.calls.length, 0);
  const one = draft(); keys.slice(1).forEach(key => { one.sections[key].status = "summary_error"; });
  upload.load(one);
  assert.equal(upload.get("apply-button").disabled, false, "a single accepted draft is sufficient");
  assert.match(upload.get("availability").textContent, /기사 1개 반영 · 미완료 11개 빈칸/);
  for (const status of ["finding", "summarizing", "running", "cancelling", "cancelled", "draining"]) {
    const unfinished = draft(); unfinished.sections.eu_pork.status = status;
    upload.load(unfinished);
    assert(upload.get("apply-button").disabled, `${status} payload must not become an uploadable partial draft`);
    const jobState = draft(); jobState.status = status; upload.load(jobState);
    assert(upload.get("apply-button").disabled, `${status} job cannot be applied`);
  }
  const blankCompleted = draft(); blankCompleted.sections.domestic.summary = "";
  upload.load(blankCompleted);
  assert.equal(upload.get("apply-button").disabled, false, "completed with an empty summary is a terminal blank item");
  assert.match(upload.get("availability").textContent, /기사 11개 반영 · 미완료 1개 빈칸/);
  const old = draft(); old.reportDate = "2026-10-01"; upload.load(old);
  assert(upload.get("apply-button").disabled, "previous date cannot be applied");
  upload.load(draft()); upload.context.activeArticleRequest = { requestId: "pending" };
  upload.run("updateArticleHwpxApplyState()");
  assert(upload.get("apply-button").disabled, "partial snapshots are unavailable until workers end");
  upload.context.activeArticleRequest = null;
  upload.context.articleResetting = true; upload.run("updateArticleHwpxApplyState()");
  assert(upload.get("apply-button").disabled);
  upload.context.articleResetting = false; upload.run("updateArticleHwpxApplyState()");
  assert.equal(upload.get("apply-button").disabled, false);
  for (const [flag, blocked] of [["articlePageLeaving", true], ["articleSummaryButton", { disabled: true }]]) {
    const previous = upload.context[flag]; upload.context[flag] = blocked;
    upload.run("updateArticleHwpxApplyState()"); assert(upload.get("apply-button").disabled);
    upload.context[flag] = previous;
  }
  upload.run("updateArticleHwpxApplyState()");

  upload.drop([file("old.hwp")]);
  assert(upload.get("dropzone").classes.has("is-invalid"));
  assert.match(upload.get("status").textContent, /다른 이름으로 저장/);
  assert.equal(upload.get("file").value, "");
  assert(upload.get("file-name").hidden);
  for (const invalid of [file("report.pdf"), file("empty.hwpx", 0), file("large.hwpx", 20 * 1024 * 1024 + 1)]) {
    upload.choose([invalid]); assert(upload.get("apply-button").disabled); assert(upload.get("dropzone").classes.has("is-invalid"));
  }
  upload.drop([file("a.hwpx"), file("b.hwpx")]);
  assert.match(upload.get("status").textContent, /한 개만/);
  const drag = { dataTransfer: { types: ["Files"] }, preventDefault() {} };
  upload.get("dropzone").events.get("dragover")(drag);
  assert(upload.get("dropzone").classes.has("is-dragover"));
  assert.equal(drag.dataTransfer.dropEffect, "copy");
  upload.drop([file("한글.HWPX", 20 * 1024 * 1024)]);
  assert.equal(upload.get("apply-button").disabled, false);
  assert.equal(upload.get("file-hint").textContent, "20 MB · 클릭 또는 드래그로 파일 변경");
  assert.equal(upload.get("dropzone").classes.has("is-dragover"), false);
  upload.get("clear-button").events.get("click")();
  assert.equal(upload.get("dropzone").classes.has("has-file"), false);
  assert.equal(upload.get("dropzone").classes.has("is-invalid"), false);
  assert(upload.get("apply-button").disabled);

  let finish;
  const success = page(() => new Promise(resolve => { finish = resolve; }));
  const fullDraft = draft(); success.load(fullDraft); success.choose([file()]);
  const applying = success.apply();
  assert(success.get("apply-button").disabled);
  assert(success.get("file").disabled);
  assert.equal(success.get("apply-button").attrs.get("aria-busy"), "true");
  assert.match(success.get("status").textContent, /반영하고/);
  await success.apply();
  assert.equal(success.calls.length, 1, "double click must not send another request");
  assert.equal(success.calls[0].url, "/apply-article-draft");
  const entries = success.calls[0].options.body.entries;
  assert.equal(entries[0][0], "report_file"); assert.equal(entries[0][2], "가격현행화.hwpx");
  assert.equal(entries[1][0], "draft"); assert.deepEqual(JSON.parse(entries[1][1]), fullDraft);
  const filename = "주간_완성본.hwpx";
  finish(response(200, {}, `attachment; filename*=UTF-8''${encodeURIComponent(filename)}`));
  await applying;
  assert.equal(success.get("download").hidden, false);
  assert.equal(success.get("download").download, filename);
  assert.equal(success.get("download").clicks, 1);
  assert.equal(success.get("apply-button").disabled, false);
  assert.match(success.get("status").textContent, /기사 12개 반영 · 미완료 0개 빈칸/);
  assert.equal(success.created.length, 1);
  assert.equal(success.revoked.length, 0, "URL survives for explicit repeat download");
  success.run("invalidateArticleHwpxApply(true)");
  assert.equal(success.revoked[0], "blob:report-1");
  assert(success.get("download").hidden); assert(success.get("status").hidden);

  for (const missing of ["eu_pork", "domestic_chicken"]) {
    let finishPartial;
    const partial = page(() => new Promise(resolve => { finishPartial = resolve; }));
    const partialDraft = draft();
    partialDraft.sections[missing].status = "summary_error";
    partial.load(partialDraft); partial.choose([file()]);
    const pending = partial.apply();
    assert.match(partial.get("status").textContent, /기사 11개 반영 · 미완료 1개 빈칸/);
    assert.match(partial.get("status").textContent, /기존 기사 문구는 지우며/);
    assert.match(partial.get("availability").textContent, /기사 11개 반영 · 미완료 1개 빈칸/);
    const sent = JSON.parse(partial.calls[0].options.body.entries[1][1]);
    assert.equal(sent.sections[missing].status, "summary_error", "server receives rejection status, even with leftover summary text");
    assert.equal(Object.keys(sent.sections).length, 12);
    finishPartial(response()); await pending;
    assert.equal(partial.get("download").clicks, 1);
    assert.match(partial.get("status").textContent, /기사 11개 반영 · 미완료 1개 빈칸/);
  }
  for (const countHeaders of [
    { "x-article-applied-count": "10", "x-article-blank-count": "2" },
    { "x-article-applied-count": "bad", "x-article-blank-count": "2" },
    { "x-article-applied-count": "12", "x-article-blank-count": "3" },
  ]) {
    const counted = page(async () => response(200, {}, "", undefined, { size: 200 }, countHeaders));
    const partialDraft = draft(); partialDraft.sections.domestic_egg.status = "summary_error";
    counted.load(partialDraft); counted.choose([file()]); await counted.apply();
    assert.match(counted.get("status").textContent, countHeaders["x-article-applied-count"] === "10"
      ? /기사 10개 반영 · 미완료 2개 빈칸/ : /기사 11개 반영 · 미완료 1개 빈칸/,
    "authoritative valid response counts take priority; absent or malformed headers use requested ready count");
  }
  const malformed = page(async () => response(400, { error: "완료된 국내기사의 제목·출처가 필요합니다." }, "", "application/json"));
  const badContent = draft(); badContent.sections.domestic.summary = "검증 실패 문구";
  malformed.load(badContent); malformed.choose([file()]); await malformed.apply();
  assert.match(malformed.get("status").textContent, /기사 반영 실패/);
  assert.equal(malformed.created.length, 0, "server retains final validation of malformed completed entries");

  for (const result of [response(400, { error: "보고서 날짜가 일치하지 않습니다." }, "", "application/json"), response(200, { error: "잘못된 파일입니다." }, "", "application/json"), response(200, {}, "", undefined, { size: 0 })]) {
    const failed = page(async () => result); failed.load(draft()); failed.choose([file()]); await failed.apply();
    assert.match(failed.get("status").textContent, /기사 반영 실패/);
    assert.equal(failed.created.length, 0); assert(failed.get("download").hidden);
    assert.equal(failed.get("apply-button").disabled, false, "user can correct file and retry");
  }

  for (const lateStage of ["fetch", "blob"]) {
    let resolveLate;
    const late = page(async () => lateStage === "fetch" ? new Promise(resolve => { resolveLate = resolve; }) : {
      ...response(), blob: () => new Promise(resolve => { resolveLate = resolve; }),
    });
    late.load(draft()); late.choose([file()]); const pending = late.apply();
    for (let i = 0; i < 10; i++) await Promise.resolve();
    assert(resolveLate);
    late.context.articleReportDate.value = "2026-10-15";
    late.run("invalidateArticleHwpxApply(true)");
    assert(late.calls[0].options.signal.aborted);
    late.context.currentArticleDraft = null;
    resolveLate(lateStage === "fetch" ? response() : { size: 100 });
    await pending;
    assert.equal(late.created.length, 0, "late old-date response must not download");
    assert.equal(late.get("download").clicks, 0); assert(late.get("status").hidden);
    assert(late.get("apply-button").disabled);
  }
  assert.match(html, /id="article-hwpx-status"[^>]*role="status"[^>]*aria-live="polite"/);
  assert.match(html, /필요한 최소한으로 -20까지/);
  assert(!/12개 모두 완료해야|기사 초안 12개 완료와 HWPX/.test(html));
  assert(!/\/start-article-draft|\/article-draft-status|navigator\.clipboard|scrollIntoView|alert\(/.test(source));
  console.log("Article HWPX: partial and full drafts, accurate counts, pick/drop, validation, multipart download, errors and late-reset safety OK");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
