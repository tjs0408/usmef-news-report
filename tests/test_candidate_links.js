const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const html = fs.readFileSync('templates/index.html', 'utf8');
const fn = html.slice(html.indexOf('    function renderArticleResult('), html.indexOf('    function renderArticleSummary('));
function element() {
  return { children: [], append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; } };
}
const result = element();
const context = {URL, document: {createElement: element}, articleResult: () => result,
  articleSpecs: [{key:'us'}], formatArticleDate: value => value, emptyArticleResult() {}};
vm.createContext(context); vm.runInContext(fn, context);
vm.runInContext(html.slice(html.indexOf('    function normalizeArticleMetadata('), html.indexOf('    function emptyArticleResult(')), context);
context.renderArticleResult('us', {article: {url:'https://example.com/main',title:'Main'}, summary:'Summary',
  candidateLinks: [
    {url:'https://example.com/main',title:'Duplicate'},
    {url:'javascript:alert(1)',title:'Unsafe'},
    {url:'https://example.com/one',title:'<script>plain title</script>',publishedDate:'2026-10-01'},
    {url:'https://example.com/two',title:'Two'}, {url:'https://example.com/three',title:'Three'}]});
const box = result.children.at(-1), rows = box.children[1].children;
assert.equal(box.className, 'article-candidate-links');
assert.equal(rows.length, 2);
assert.equal(rows[0].children[0].textContent, '<script>plain title</script>');
assert.equal(rows[0].children[0].target, '_blank');
assert.equal(rows[0].children[0].rel, 'noopener noreferrer');
context.renderArticleResult('us', {article:{url:'https://example.com/main',title:'Main'},candidateLinks:[]});
assert.match(result.children.at(-1).children[1].textContent, /추가 후보를 확보하지 못/);
console.log('Candidate links: safe URLs, plain titles, deduplication, two-link cap and empty state OK');
