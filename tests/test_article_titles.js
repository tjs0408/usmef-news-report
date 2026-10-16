// Real display/copy functions must also normalize an already-saved draft.
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
  articleSpecs: [{key:'domestic_egg', label:'계란 - 국내기사', domestic:true}],
  formatArticleDate: value => value, emptyArticleResult() {} };
vm.createContext(context);
vm.runInContext(metadata + display + briefing, context);
const headline = '브라질산 계란 수입가 논란… 정부 “수급 안정 조치” vs 野 “재정 투입 적정성 따져야”';
const displayedHeadline = "브라질산 계란 수입가 논란… 정부 '수급 안정 조치' vs 野 '재정 투입 적정성 따져야'";
const raw = { title: `[인싸잇] ${headline}`, publisher: 'mediawatch.kr', publishedDate: '2026-10-14',
  url: 'https://www.mediawatch.kr/news/article.html?no=261344' };
const normalized = context.normalizeArticleMetadata(raw);
assert.equal(normalized.title, headline);
assert.equal(normalized.publisher, '인싸잇');
assert.equal(normalized.publishedDate, raw.publishedDate);
assert.equal(raw.title, `[인싸잇] ${headline}`, 'saved input must not be mutated');
assert.equal(raw.publisher, 'mediawatch.kr');
assert.equal(context.normalizeArticleMetadata(normalized).title, headline, 'normalization is idempotent');
for (const publisher of ['mediawatch.kr', '인싸잇']) {
  for (const suffix of ['mediawatch.kr', 'www.mediawatch.kr']) {
    const article = context.normalizeArticleMetadata({...raw, publisher, title:`[인싸잇] ${headline} - ${suffix}`});
    assert.equal(article.title, headline, 'a canonicalized publisher still removes its exact-domain suffix');
    assert.equal(article.publisher, '인싸잇');
  }
}
assert.equal(context.normalizeArticleMetadata({...raw, publisher:'인싸잇', title:`[인싸잇] ${headline} - mediawatch.kr`, url:'https://mediawatch.kr.example.com/news'}).title, `${headline} - mediawatch.kr`, 'an unrelated host cannot authorize domain suffix cleanup');

for (const title of ['[특파원 보고] 프랑스 닭고기 소비 동향', '[분석] 해외 계란 수급 동향']) {
  assert.equal(context.normalizeArticleMetadata({ title, publisher:'농민신문' }).title, title);
}
assert.equal(context.normalizeArticleMetadata({title:'[머니투데이][특파원 보고] 해외 육류 동향 - 머니투데이', publisher:'머니투데이'}).title, '[특파원 보고] 해외 육류 동향');
assert.equal(context.normalizeArticleMetadata({title:'[매체+] 해외 육류 동향 - 매체+', publisher:'매체+'}).title, '해외 육류 동향', 'publisher regex metacharacters are literal');
assert.equal(context.normalizeArticleMetadata({title:'[머니투데이]', publisher:'머니투데이'}).title, '[머니투데이]', 'never erase the entire headline');
for (const url of ['https://mediawatch.kr.example.com/news', 'https://notmediawatch.kr/news', 'https://example.com/mediawatch.kr']) {
  const article = context.normalizeArticleMetadata({ ...raw, publisher:'다른매체', url });
  assert.equal(article.title, raw.title);
  assert.equal(article.publisher, '다른매체');
}
assert.equal(context.normalizeArticleMetadata({...raw, title:headline}).publisher, 'mediawatch.kr', 'unbranded archive metadata is not guessed');

const section = { article:raw, summary:'브라질산 계란 개당 수입가격은 1300원으로 미국산 464원 대비 2.8배 수준',
  candidateLinks:[{...raw, url:'https://www.mediawatch.kr/news/article.html?no=2'}] };
section.article.sourceExcerpt = '원문 “수급 안정 조치” 및 "재정 투입" 내용';
const savedSection = JSON.stringify(section);
assert.equal(context.formatDomesticArticleTitle('정부 "수급"과 농가\'s ‘전망’'), "정부 '수급'과 농가's ‘전망’");
assert.equal(context.formatDomesticArticleTitle('독일 „가격‟, 일본 ＂수급＂'), "독일 '가격', 일본 '수급'");
assert.equal(context.formatDomesticArticleTitle(displayedHeadline), displayedHeadline, 'quote presentation is idempotent');
context.renderArticleResult('domestic_egg', section);
assert.equal(result.children[1].textContent, displayedHeadline);
assert.match(result.children[2].textContent, /^인싸잇 · 2026-10-14/);
assert.equal(result.children[4].children[1].textContent, section.article.sourceExcerpt, 'source evidence retains original quotes');
assert.equal(result.children.at(-1).children[1].children[0].children[0].textContent, displayedHeadline);
assert.match(result.children.at(-1).children[1].children[0].children[1].textContent, /^인싸잇 · /);
const copied = context.buildArticleBriefing({sections:{domestic_egg:section}});
assert(copied.includes(`∙ “${displayedHeadline}”(인싸잇,10.14.)`));
assert(!copied.includes('[인싸잇]'));
assert(!copied.includes('mediawatch.kr'));
assert.equal(JSON.stringify(section), savedSection, 'display and copy must not mutate saved headline, URLs or evidence');
for (const key of ['domestic', 'domestic_pork', 'domestic_chicken', 'domestic_egg']) {
  context.articleSpecs = [{key, label:key, domestic:true}];
  context.renderArticleResult(key, section);
  assert.equal(result.children[1].textContent, displayedHeadline, key);
  assert.equal(result.children.at(-1).children[1].children[0].children[0].textContent, displayedHeadline, key);
  assert(context.buildArticleBriefing({sections:{[key]:section}}).includes(`∙ “${displayedHeadline}”`), key);
}
context.articleSpecs = [{key:'us_egg', label:'계란 - 미국', domestic:false}];
context.renderArticleResult('us_egg', section);
assert.equal(result.children[1].textContent, headline, 'foreign source headline retains double quotes');
assert.equal(result.children.at(-1).children[1].children[0].children[0].textContent, headline, 'foreign candidate headline retains double quotes');
assert.equal(JSON.stringify(section), savedSection);
console.log('Article titles: publisher cleanup, safe branding, domestic-only quote presentation, saved-draft display/copy/candidates OK');
