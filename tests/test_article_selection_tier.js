const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const html = fs.readFileSync('templates/index.html', 'utf8');
const metadata = html.slice(html.indexOf('    function normalizeArticleMetadata('), html.indexOf('    function emptyArticleResult('));
const display = html.slice(html.indexOf('    function renderArticleResult('), html.indexOf('    function renderArticleSummary('));
const briefing = html.slice(html.indexOf('    function buildArticleBriefing('), html.indexOf('    async function copyArticleBriefing('));
function element() {
  return { children: [], append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; } };
}
const result = element();
const context = { URL, document: { createElement: element }, articleResult: () => result,
  articleSpecs: [{key:'domestic_pork', label:'돼지 - 국내기사', domestic:true}],
  formatArticleDate: value => value, emptyArticleResult() {} };
vm.createContext(context);
vm.runInContext(metadata + display + briefing, context);
const original = { article: { title:'중국 돼지고기 가격 하락', publisher:'시장뉴스',
  url:'https://example.com/pork', publishedDate:'2026-10-14' },
  summary:'중국 돼지고기는 충분한 공급과 소비 부진으로 전년 동월비 가격 하락',
  candidateLinks: [{ title:'중국 축산 수급 동향', publisher:'다른뉴스',
    url:'https://example.com/other', publishedDate:'2026-10-15', selectionTier:2,
    selectionReason:'후보의 자세한 선정 사유' }] };
context.renderArticleResult('domestic_pork', original);
const normalMeta = result.children[2].textContent;
const normalCopy = context.buildArticleBriefing({sections:{domestic_pork:original}});
assert.equal(normalMeta, '시장뉴스 · 2026-10-14', 'old saved drafts keep their original metadata display');
assert.equal(result.children.at(-1).children[1].children[0].children[1].textContent,
  '다른뉴스 · 2026-10-15 · 유사시장 보완', 'candidate displays only the short selection label');

for (const [selectionTier, label] of [[1,'수급·물가 설명'], [2,'유사시장 보완'], ['1','수급·물가 설명'], ['2','유사시장 보완']]) {
  const section = {...original, article:{...original.article, selectionTier,
    selectionReason:' 돼지고기 공급과  소비의 가격 영향 설명 '}};
  const saved = JSON.stringify(section);
  context.renderArticleResult('domestic_pork', section);
  assert.equal(result.children[2].textContent,
    `시장뉴스 · 2026-10-14 · ${label} · 돼지고기 공급과 소비의 가격 영향 설명`);
  assert.equal(context.buildArticleBriefing({sections:{domestic_pork:section}}), normalCopy,
    'selection metadata never appears in copied report wording');
  assert.equal(JSON.stringify(section), saved, 'saved metadata is not mutated');
}
for (const selectionTier of [undefined, null, 0, '0', '', 3, -1, true, {}, '<script>']) {
  context.renderArticleResult('domestic_pork', {...original,
    article:{...original.article, selectionTier, selectionReason:'not displayed'}});
  assert.equal(result.children[2].textContent, normalMeta, 'unknown or direct tiers keep the original display');
}
assert.equal(context.articleSelectionNote({selectionTier:2}), ' · 유사시장 보완');
assert.equal(context.articleSelectionNote({selectionTier:1, selectionReason:{unexpected:true}}), ' · 수급·물가 설명');
const hostileReason = '<img src=x onerror=alert(1)>';
context.renderArticleResult('domestic_pork', {...original,
  article:{...original.article, selectionTier:2, selectionReason:hostileReason}});
assert.equal(result.children[2].textContent, `시장뉴스 · 2026-10-14 · 유사시장 보완 · ${hostileReason}`,
  'selection descriptions are inserted as plain text, not HTML');
console.log('Article selection tiers: visible labels/reasons, old draft compatibility, safe text and unchanged report copy OK');
