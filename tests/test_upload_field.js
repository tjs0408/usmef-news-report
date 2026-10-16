const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(path.join(__dirname, "../templates/index.html"), "utf8");
const source = html.match(/    (function updateSelectedFile[\s\S]*?)    function stageForProgress/)[1];

class Element {
  constructor() {
    this.events = new Map();
    this.classes = new Set();
    this.classList = {
      add: (name) => this.classes.add(name),
      remove: (name) => this.classes.delete(name),
      toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
    };
  }
  addEventListener(name, handler) { this.events.set(name, handler); }
  dispatchEvent(event) { this.events.get(event.type)?.(event); }
  contains(target) { return target === this; }
}

class FileInput extends Element {
  constructor() { super(); this.files = []; }
  set value(value) { if (value === "") this.files = []; }
}

const input = new FileInput();
const caption = new Element();
const card = new Element();
const title = new Element();
const filename = new Element();
const hint = new Element();
const statuses = [];
new Function("templateFile", "selectedFile", "uploadField", "uploadTitle", "uploadFileName", "uploadHint", "setStatus", "Event", source)(
  input, caption, card, title, filename, hint, (...args) => statuses.push(args),
  class { constructor(type) { this.type = type; } },
);

const file = (name, size = 1024) => ({ name, size });
const choose = (files) => { input.files = files; input.dispatchEvent({ type: "change" }); };
const drop = (files) => {
  const event = { type: "drop", dataTransfer: { files }, prevented: false,
    preventDefault() { this.prevented = true; } };
  card.dispatchEvent(event);
  assert.equal(event.prevented, true);
};

choose([file("weekly.xlsx")]);
assert.equal(caption.textContent, "선택됨 · weekly.xlsx");
assert.equal(caption.title, "weekly.xlsx");
assert.equal(card.classes.has("has-file"), true);
assert.equal(title.textContent, "Excel 파일 선택 완료");
assert.equal(filename.textContent, "weekly.xlsx");
assert.equal(filename.hidden, false);
assert.equal(hint.textContent, "1 KB · 클릭 또는 드래그로 파일 변경");

const drag = { type: "dragover", dataTransfer: { types: ["Files"] }, preventDefault() {} };
card.dispatchEvent(drag);
assert.equal(card.classes.has("is-dragover"), true);
assert.equal(drag.dataTransfer.dropEffect, "copy");
drop([file("dropped.XLSX")]);
assert.equal(input.files[0].name, "dropped.XLSX");
assert.equal(caption.textContent, "선택됨 · dropped.XLSX");
assert.equal(card.classes.has("is-dragover"), false);
assert.equal(filename.textContent, "dropped.XLSX");

for (const invalid of [file("invalid.pdf"), file("large.xlsx", 20 * 1024 * 1024 + 1)]) {
  drop([invalid]);
  assert.equal(input.files.length, 0);
  assert.equal(card.classes.has("has-file"), false);
  assert.equal(caption.classes.has("has-file"), false);
  assert.equal(caption.title, "");
  assert.equal(statuses.at(-1)[1], "is-error");
  assert.equal(card.classes.has("is-invalid"), true);
  assert.equal(title.textContent, "파일을 다시 선택해 주세요");
  assert.equal(filename.hidden, true);
}

drop([file("one.xlsx"), file("two.xlsx")]);
assert.equal(input.files.length, 0);
assert.equal(statuses.at(-1)[0], "기준 Excel 파일은 한 개만 올려 주세요.");
choose([]);
assert.equal(caption.textContent, "선택된 파일이 없습니다.");
assert.equal(card.classes.has("has-file"), false);
assert.equal(card.classes.has("is-invalid"), false);
assert.equal(title.textContent, "기준 Excel 파일 선택 또는 드래그");
assert.equal(filename.hidden, true);
assert.equal(hint.textContent, ".xlsx 형식 · 지난주 완성본 · 최대 20MB");

choose([file("해외시장_" + "주간보고서".repeat(25) + ".xlsx", 1.5 * 1024 * 1024)]);
assert.equal(hint.textContent, "1.5 MB · 클릭 또는 드래그로 파일 변경");
assert.equal(filename.title, input.files[0].name);
choose([file("limit.xlsx", 20 * 1024 * 1024)]);
assert.equal(card.classes.has("has-file"), true);
assert.equal(hint.textContent, "20 MB · 클릭 또는 드래그로 파일 변경");

card.dispatchEvent(drag);
card.dispatchEvent({ type: "dragleave", relatedTarget: null });
assert.equal(card.classes.has("is-dragover"), false);
card.dispatchEvent({ type: "dragover", dataTransfer: { types: ["text/plain"] }, preventDefault() {
  throw new Error("Non-file drag must not select a file");
} });
assert.equal(card.classes.has("is-dragover"), false);
console.log("Upload card: selection, drag/drop, validation, and reset OK");
