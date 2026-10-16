"""Article insertion preserves uploaded HWPX artwork, prices, and formatting."""

from pathlib import Path
import copy
import re
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

from src.article_hwpx import (
    ARTICLE_SLOT_KEYS, ArticleHwpxError, _discover_slots, _reuse_article_character_styles, apply_article_draft_to_hwpx,
)
from src.article_hwpx_layout import MAX_ARTICLE_TRACKING, article_segments
from src.overseas_article_digest import compact_report_summary, normalize_report_spacing


HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
NS = {"hp": HP, "hh": HH}
ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path("C:/Users/USER/Downloads/주간_해외_수급_및_가격_동향_표현행화_20261002_140603.hwpx")
LATEST_UPLOAD = Path("C:/Users/USER/Downloads/주간_해외_수급_및_가격_동향_기사반영_20261008_dd949aa755be.hwpx")


def _draft():
    result = {"reportDate": "2026-10-08", "sections": {}}
    for index, key in enumerate(ARTICLE_SLOT_KEYS):
        # Different texts reveal wrong country/species assignments.
        summary = (
            f"항목{index + 1}의 공급 감소와 시장 수요 회복으로 가격 상승 압력이 확대되는 가운데 향후 수급 안정 여부에 대한 점검 필요"
            if key in ('us', 'us_chicken') else
            f"항목{index + 1} 공급 5% 감소·가격 4% 상승, 수요 회복에 따른 수급 안정 점검 필요"
        )
        result["sections"][key] = {"status": "completed", "summary": summary,
            "article": {"title": f"항목{index + 1} 해외 시장의 <수급> & 가격 동향", "publisher": "시험매체 & 경제", "publishedDate": "2026-10-06"}}
    return result


def _p(text, *, headline=False):
    if headline:
        runs = '<hp:run charPrIDRef="30"><hp:t>∙</hp:t></hp:run><hp:run charPrIDRef="51"><hp:t>“기존 기사 제목”</hp:t></hp:run><hp:run charPrIDRef="55"><hp:t>(기존매체,9.20.)</hp:t></hp:run>'
    elif text.startswith(" -(현지동향)"):
        runs = '<hp:run charPrIDRef="39"><hp:t> -<hp:fwSpace/></hp:t></hp:run><hp:run charPrIDRef="43"><hp:t>(현지동향) 기존 현지 기사 내용</hp:t></hp:run><hp:run charPrIDRef="42"><hp:t> 원래 문장 유지</hp:t></hp:run>'
    else:
        runs = f'<hp:run charPrIDRef="30"><hp:t>{escape(text)}</hp:t></hp:run>'
    return f'<hp:p id="duplicated" paraPrIDRef="29" pageBreak="0">{runs}<hp:linesegarray><hp:lineseg textpos="0" horzsize="48188"/></hp:linesegarray></hp:p>'


def _fixture_section():
    body = []
    for species, country in (("쇠고기", "호주"), ("돼지고기", "EU(독일)"), ("육계", "브라질"), ("계란", "일본")):
        body.append(_p(f"□ {species} 수급 및 가격 동향"))
        main = []
        for current in ("미국", country):
            main.append('<hp:tc borderFillIDRef="price-border"><hp:subList>' + _p("○ " + current)
                        + _p(" -(현지동향) 원래 현지 내용") + _p("가격 데이터: 123.45")
                        + '<hp:p><hp:run><hp:pic><hp:sz width="5000" height="3000"/></hp:pic></hp:run></hp:p>'
                        + '</hp:subList><hp:cellSz width="48188" height="2000"/></hp:tc>')
        body.append('<hp:p><hp:run><hp:tbl rowCnt="2" colCnt="1"><hp:tr>' + ''.join(main) + '</hp:tr></hp:tbl></hp:run></hp:p>')
        body.append('<hp:p><hp:run><hp:tbl rowCnt="1" colCnt="1"><hp:tr><hp:tc borderFillIDRef="news-border"><hp:subList>'
                    + _p("", headline=True) + _p(" - 기존 국내기사 요약 본문")
                    + '</hp:subList><hp:cellSz width="46604" height="3360"/></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>')
    return ('<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="' + HS + '" xmlns:hp="' + HP + '">' + ''.join(body) + '</hs:sec>').encode()


def _package(path, section=None, extra=None):
    with zipfile.ZipFile(ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx') as template:
        header = template.read('Contents/header.xml')
    parts = {"mimetype": b"application/hwp+zip", "Contents/header.xml": header,
             "Contents/section0.xml": section or _fixture_section(), "BinData/chart.png": b"unchanged chart bytes",
             "Preview/PrvText.txt": "미리보기 보존".encode(), "Preview/PrvImage.png": b"original thumbnail"}
    parts.update(extra or {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.comment = b"original package comment"
        for name, payload in parts.items():
            archive.writestr(name, payload)
    # Windows ZipInfo normalizes separators when writing. Preserve a genuinely
    # hostile raw name in this fixture's local and central directory records.
    for name in parts:
        if "\\" in name:
            path.write_bytes(path.read_bytes().replace(name.replace("\\", "/").encode(), name.encode()))


class ArticleHwpxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "input.hwpx"
        self.output = self.directory / "output.hwpx"
        _package(self.source)

    def tearDown(self):
        self.temporary.cleanup()

    def assert_preserved(self, source, output):
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as edited:
            self.assertEqual(original.namelist(), edited.namelist())
            self.assertEqual(original.comment, edited.comment)
            for name in original.namelist():
                if not name.startswith("Contents/section") and name != "Contents/header.xml":
                    self.assertEqual(original.read(name), edited.read(name), name)
            old_header_bytes = original.read('Contents/header.xml')
            new_header_bytes = edited.read('Contents/header.xml')
            old_header = ET.fromstring(old_header_bytes)
            new_header = ET.fromstring(new_header_bytes)
            complete_new_styles = {node.get('id'): node for node in new_header.findall('.//hh:charPr', NS)}
            complete_new_fonts = {
                group.get('lang').lower(): {node.get('id'): node.get('face') for node in group}
                for group in new_header.findall('.//hh:fontface', NS)
            }
            original_style_ids = {node.get('id') for node in old_header.findall('.//hh:charPr', NS)}
            # A fresh Gulim character style is exclusively a middle-dot run,
            # not a replacement for neighboring local prose or domestic text.
            dot_styles = set()
            for identity, style in complete_new_styles.items():
                if identity in original_style_ids:
                    continue
                references = style.find('hh:fontRef', NS)
                faces = {complete_new_fonts[language][font_id]
                         for language, font_id in references.attrib.items()}
                if '굴림' in faces:
                    self.assertEqual({'굴림'}, faces)
                    dot_styles.add(identity)
            if dot_styles:
                article_parts = {name: edited.read(name) for name in edited.namelist()
                                 if name.startswith('Contents/section') and name.endswith('.xml')}
                all_uses = {identity: 0 for identity in dot_styles}
                local_uses = dict(all_uses)
                for data in article_parts.values():
                    for run in ET.fromstring(data).findall('.//hp:run', NS):
                        if run.get('charPrIDRef') in dot_styles:
                            self.assertEqual('·', ''.join(run.itertext()))
                            all_uses[run.get('charPrIDRef')] += 1
                for slot in _discover_slots(article_parts).values():
                    if slot.title is not None:
                        continue
                    paragraph = slot.paragraph
                    wrapper = ET.fromstring(f'<root xmlns:hp="{HP}">'.encode()
                                            + article_parts[slot.section][paragraph.start:paragraph.end]
                                            + b'</root>')
                    for run in wrapper.findall('.//hp:run', NS):
                        if run.get('charPrIDRef') in dot_styles:
                            local_uses[run.get('charPrIDRef')] += 1
                self.assertTrue(all(all_uses.values()))
                self.assertEqual(all_uses, local_uses)
            # The editor may append article-only character and paragraph style
            # clones, but must never modify shared styles used by market data.
            for style_tag, container_tag in [('charPr', 'charProperties'), ('paraPr', 'paraProperties')]:
                old_styles = {node.get('id'): ET.tostring(node) for node in old_header.findall('.//hh:' + style_tag, NS)}
                new_styles = {node.get('id'): ET.tostring(node) for node in new_header.findall('.//hh:' + style_tag, NS)}
                self.assertTrue(set(old_styles).issubset(new_styles), style_tag)
                for identity, style in old_styles.items():
                    self.assertEqual(style, new_styles[identity], (style_tag, identity))
                properties = new_header.find('.//hh:' + container_tag, NS)
                self.assertEqual(len(properties), int(properties.get('itemCnt')), container_tag)
                self.assertEqual(len(properties), len(new_styles), container_tag)
                # Removing only appended styles and restoring itemCnt must
                # reconstruct the entire original header exactly.
                for node in list(properties):
                    if node.get('id') not in old_styles:
                        properties.remove(node)
                properties.set('itemCnt', str(len(old_styles)))
            # Uniform article faces may be missing from a language's font
            # table (the original local style mixed Poppy and Myeongjo).
            # Exact same-face Hangul definitions may be appended. An absent
            # standard Gulim face alone may use a minimal real TTF declaration;
            # every pre-existing font entry remains byte-identical.
            hangul = old_header.find('.//hh:fontface[@lang="HANGUL"]', NS)
            originals_by_face = {node.get('face'): node for node in hangul}
            old_groups = {group.get('lang'): group for group in old_header.findall('.//hh:fontface', NS)}
            new_groups = {group.get('lang'): group for group in new_header.findall('.//hh:fontface', NS)}
            self.assertEqual(set(old_groups), set(new_groups))
            for language, old_group in old_groups.items():
                new_group = new_groups[language]
                old_fonts = {node.get('id'): node for node in old_group}
                self.assertEqual(len(new_group), int(new_group.get('fontCnt')))
                self.assertEqual(len(new_group), len({node.get('id') for node in new_group}))
                for node in list(new_group):
                    identity = node.get('id')
                    if identity in old_fonts:
                        self.assertEqual(ET.tostring(old_fonts[identity]), ET.tostring(node))
                    else:
                        self.assertIn(node.get('face'), ('휴먼명조', '한양중고딕', '굴림'))
                        if node.get('face') == '굴림' and '굴림' not in originals_by_face:
                            self.assertEqual({'id': identity, 'face': '굴림', 'type': 'TTF', 'isEmbedded': '0'}, node.attrib)
                            self.assertEqual(0, len(node))
                            self.assertFalse(node.text)
                        else:
                            expected = ET.fromstring(ET.tostring(originals_by_face[node.get('face')]))
                            expected.set('id', identity)
                            self.assertEqual(ET.tostring(expected), ET.tostring(node))
                        new_group.remove(node)
                new_group.set('fontCnt', old_group.get('fontCnt'))
            self.assertEqual(ET.tostring(old_header), ET.tostring(new_header))
            for tag in ('charPr', 'paraPr', 'font'):
                pattern = (rb'<(?P<prefix>[A-Za-z_][\w.-]*):' + tag.encode()
                           + rb'\b[^>]*(?:/\s*>|>.*?</(?P=prefix):' + tag.encode() + rb'\s*>)')
                for match in re.finditer(pattern, old_header_bytes, re.S):
                    self.assertIn(match[0], new_header_bytes, tag)
            old = ET.fromstring(original.read("Contents/section0.xml"))
            new = ET.fromstring(edited.read("Contents/section0.xml"))
            for tag in ("tbl", "tc", "cellSz", "cellMargin", "pic", "sz", "imgRect", "pos"):
                self.assertEqual([node.attrib for node in old.findall('.//hp:' + tag, NS)],
                                 [node.attrib for node in new.findall('.//hp:' + tag, NS)], tag)
            # Text-only article runs now intentionally receive fresh style IDs.
            # All other leaf paragraphs, including picture/price paragraphs,
            # retain their full XML. Only the root page-boundary flag may change.
            def other_paragraphs(package, parsed):
                parts = {name: package.read(name) for name in package.namelist() if name.startswith('Contents/section')}
                article_texts = {''.join(paragraph.own_text.split()) for slot in _discover_slots(parts).values()
                                 for paragraph in [slot.paragraph, *slot.continuations, *([slot.title] if slot.title else [])]}
                result = []
                for paragraph in parsed.findall('.//hp:p', NS):
                    if paragraph.find('.//hp:p', NS) is not None:
                        continue
                    text = ''.join(''.join(node.itertext()) for node in paragraph.findall('hp:run/hp:t', NS))
                    if ''.join(text.split()) in article_texts:
                        continue
                    paragraph.attrib.pop('pageBreak', None)
                    result.append(ET.tostring(paragraph))
                return result
            self.assertEqual(other_paragraphs(original, old), other_paragraphs(edited, new))

    def assert_mapping(self, output, draft):
        with zipfile.ZipFile(output) as archive:
            parts = {name: archive.read(name) for name in archive.namelist() if name.startswith("Contents/section")}
        slots = _discover_slots(parts)
        self.assertEqual(set(slots), set(ARTICLE_SLOT_KEYS))
        for key, slot in slots.items():
            section = draft['sections'][key]
            source = section.get('article', {}).get('sourceExcerpt')
            summary = compact_report_summary(section['summary'], key, source=source if isinstance(source, str) else None)
            expected = " - (현지동향) " + summary if slot.title is None else " - " + summary
            self.assertEqual(slot.paragraph.own_text, expected, key)
            self.assertNotIn(HP + "}linesegarray", [node.name for node in slot.paragraph.children])
            if slot.title is not None:
                article = draft["sections"][key]["article"]
                self.assertEqual(slot.title.own_text, f'∙“{article["title"]}”({article["publisher"]},10.6.)')

    def test_twelve_slots_escape_xml_and_preserve_upload(self):
        original_bytes = self.source.read_bytes()
        draft = _draft()
        result = apply_article_draft_to_hwpx(self.source, self.output, draft)
        self.assertEqual(result["appliedCount"], 12)
        self.assertEqual(result["localCount"], 8)
        self.assertEqual(result["domesticCount"], 4)
        self.assertEqual(self.source.read_bytes(), original_bytes)
        self.assert_mapping(self.output, draft)
        self.assert_preserved(self.source, self.output)
        with zipfile.ZipFile(self.output) as archive:
            section = archive.read("Contents/section0.xml")
            self.assertIn(b"&lt;", section)
            self.assertIn(b"&amp;", section)
            self.assertNotIn(b"ns0:", section)
            self.assertEqual(section.count("가격 데이터: 123.45".encode()), 8)

    def test_all_four_domestic_titles_remove_only_duplicate_publisher_suffix(self):
        draft = _draft()
        for key in ['domestic', 'domestic_pork', 'domestic_chicken', 'domestic_egg']:
            draft['sections'][key]['article'].update(title='해외 육류 공급 동향 - 머니투데이', publisher='머니투데이')
        result = apply_article_draft_to_hwpx(self.source, self.output, draft)
        with zipfile.ZipFile(self.output) as package:
            slots = _discover_slots({'Contents/section0.xml': package.read('Contents/section0.xml')})
        for key in ['domestic', 'domestic_pork', 'domestic_chicken', 'domestic_egg']:
            self.assertEqual(slots[key].title.own_text, '∙“해외 육류 공급 동향”(머니투데이,10.6.)')
            self.assertTrue(result['layout'][key]['title']['oneLine'])
            self.assertEqual(result['layout'][key]['title']['tracking'], 0)
        self.assert_preserved(self.source, self.output)

    def test_all_domestic_citations_use_single_inner_quotes_and_keep_source_draft_unchanged(self):
        draft = _draft()
        raw_title = '정부 “수급 안정 조치” vs 野 "재정 투입 적정성 따져야", 농가\'s ‘전망’'
        displayed = "정부 '수급 안정 조치' vs 野 '재정 투입 적정성 따져야', 농가's ‘전망’"
        for key, section in draft['sections'].items():
            section['article'].update(title=f'{key} {raw_title}', sourceExcerpt='원문 “수급 안정 조치” 및 "재정 투입" 내용',
                                      url=f'https://example.com/news/{key}?quote=%22value%22')
        before = copy.deepcopy(draft)
        apply_article_draft_to_hwpx(self.source, self.output, draft)
        with zipfile.ZipFile(self.output) as package:
            slots = _discover_slots({'Contents/section0.xml': package.read('Contents/section0.xml')})
        for key in ('domestic', 'domestic_pork', 'domestic_chicken', 'domestic_egg'):
            self.assertEqual(slots[key].title.own_text, f'∙“{key} {displayed}”(시험매체 & 경제,10.6.)', key)
        self.assertEqual(draft, before)
        self.assert_preserved(self.source, self.output)

    def test_uploaded_plain_domestic_titles_are_bold_underlined_without_changing_summary_emphasis(self):
        # A manually edited upload may have lost every headline's separate
        # style, including the second-page chicken and egg titles. Recover the
        # same semantic first-page emphasis rather than copying the plain run.
        section = (_fixture_section().replace(b'charPrIDRef="51"', b'charPrIDRef="30"')
                   .replace(b'charPrIDRef="55"', b'charPrIDRef="30"'))
        _package(self.source, section)
        result = apply_article_draft_to_hwpx(self.source, self.output, _draft())
        with zipfile.ZipFile(self.output) as package:
            header = ET.fromstring(package.read('Contents/header.xml'))
            data = package.read('Contents/section0.xml')
        styles = {node.get('id'): node for node in header.findall('.//hh:charPr', NS)}
        slots = _discover_slots({'Contents/section0.xml': data})
        for key in ('domestic', 'domestic_pork', 'domestic_chicken', 'domestic_egg'):
            slot = slots[key]
            for paragraph, headline in ((slot.title, True), (slot.paragraph, False)):
                for run in paragraph.children:
                    if run.name != HP + '}run':
                        continue
                    style = styles[run.attributes['charPrIDRef']]
                    self.assertEqual('1200', style.get('height'), key)
                    self.assertEqual(headline, style.find('hh:bold', NS) is not None, key)
                    underline = style.find('hh:underline', NS)
                    if headline:
                        self.assertEqual({'type': 'BOTTOM', 'shape': 'SOLID', 'color': '#000000'}, underline.attrib, key)
                    else:
                        self.assertIsNone(underline, key)
            self.assertEqual(0, result['layout'][key]['title']['tracking'], key)
            self.assertTrue(result['layout'][key]['title']['oneLine'], key)
        self.assert_preserved(self.source, self.output)

    def test_semantic_fonts_keep_local_parentheses_smaller_and_domestic_uniform(self):
        draft = _draft()
        for key, section in draft['sections'].items():
            section['summary'] = '축산물 공급 5.9% 감소(전년비), 수요 회복에 따른 수급 안정 점검 필요'
            section['article']['title'] = f'{key} 미국 축산물(소·돼지)의 해외 시장의 <수급> & 가격 동향'
        apply_article_draft_to_hwpx(self.source, self.output, draft)
        with zipfile.ZipFile(self.output) as archive:
            header = ET.fromstring(archive.read('Contents/header.xml'))
            styles = {node.get('id'): node for node in header.findall('.//hh:charPr', NS)}
            slots = _discover_slots({'Contents/section0.xml': archive.read('Contents/section0.xml')})
        for key, slot in slots.items():
            for paragraph, title in [(slot.paragraph, False), *([(slot.title, True)] if slot.title else [])]:
                is_domestic = slot.title is not None
                normal_height = 1200 if is_domestic else 1300
                kind = 'title' if title else ('domestic' if is_domestic else 'local')
                expected = [str(normal_height - (200 if segment.parenthetical else 0))
                            for segment in article_segments(paragraph.own_text, kind) for _ in segment.text]
                actual = []
                for run in paragraph.children:
                    if run.name != HP + '}run':
                        continue
                    style = styles[run.attributes['charPrIDRef']]
                    actual.extend([style.get('height')] * len(run.text))
                    self.assertEqual('#000000', style.get('textColor'), key)
                    self.assertEqual(title, style.find('hh:bold', NS) is not None, key)
                    self.assertEqual('6' if is_domestic else '3', style.find('hh:fontRef', NS).get('hangul'), key)
                self.assertEqual(expected, actual, key)
                if title:
                    self.assertTrue('해외 시장의 <수급> & 가격 동향' in paragraph.own_text)
                    self.assertTrue(paragraph.own_text.endswith('(시험매체 & 경제,10.6.)'))

    def test_page_boundary_starts_chicken_and_eggs_without_an_extra_break(self):
        # The small fixture does not have a separate second-page report-title
        # table, so the chicken heading itself must own the single break.
        section = _fixture_section().replace(
            _p('□ 돼지고기 수급 및 가격 동향').encode(),
            _p('□ 돼지고기 수급 및 가격 동향').replace('pageBreak="0"', 'pageBreak="1"').encode(), 1)
        _package(self.source, section)
        result = apply_article_draft_to_hwpx(self.source, self.output, _draft())
        with zipfile.ZipFile(self.output) as archive:
            root = ET.fromstring(archive.read('Contents/section0.xml'))
        paragraphs = root.findall('hp:p', NS)
        breaks = [paragraph for paragraph in paragraphs if paragraph.get('pageBreak') == '1']
        self.assertEqual(1, len(breaks))
        self.assertEqual('□ 육계 수급 및 가격 동향', ''.join(breaks[0].find('hp:run/hp:t', NS).itertext()))
        self.assert_mapping(self.output, _draft())

    def test_real_template_preserves_second_page_title_break(self):
        template = ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx'
        apply_article_draft_to_hwpx(template, self.output, _draft())
        with zipfile.ZipFile(template) as before, zipfile.ZipFile(self.output) as after:
            old = ET.fromstring(before.read('Contents/section0.xml')).findall('hp:p', NS)
            new = ET.fromstring(after.read('Contents/section0.xml')).findall('hp:p', NS)
        old_breaks = [index for index, paragraph in enumerate(old) if paragraph.get('pageBreak') == '1']
        new_breaks = [index for index, paragraph in enumerate(new) if paragraph.get('pageBreak') == '1']
        self.assertEqual([10], old_breaks)
        self.assertEqual(old_breaks, new_breaks)
        self.assertIn('주간 해외 축산물 수급 및 가격 동향', ''.join(new[10].itertext()))
        self.assertIn('육계', ''.join(new[11].itertext()))

    def test_reapplication_replaces_previous_article_not_prices(self):
        apply_article_draft_to_hwpx(self.source, self.output, _draft())
        updated = _draft()
        updated['sections']['us_chicken']['summary'] = '미국 닭고기 시장은 수출 수요 회복과 공급 감소로 가격 상승 압력이 확대되는 가운데 향후 생산 기반 회복 여부에 대한 점검 필요'
        destination = self.directory / 'again.hwpx'
        apply_article_draft_to_hwpx(self.output, destination, updated)
        self.assert_mapping(destination, updated)
        self.assert_preserved(self.output, destination)
        with zipfile.ZipFile(self.output) as first, zipfile.ZipFile(destination) as second:
            first_header = ET.fromstring(first.read('Contents/header.xml'))
            second_header = ET.fromstring(second.read('Contents/header.xml'))
        # A changed JUSTIFY first line needs a newly measured marker anchor.
        # Only that wrapped article may add a paragraph style; existing shared
        # definitions remain intact. Reapplying identical text is idempotent.
        self.assertEqual(len(first_header.findall('.//hh:paraPr', NS)) + 1,
                         len(second_header.findall('.//hh:paraPr', NS)))
        unchanged = self.directory / 'same-reviewed-draft.hwpx'
        apply_article_draft_to_hwpx(destination, unchanged, updated)
        self.assert_mapping(unchanged, updated)
        self.assert_preserved(destination, unchanged)
        with zipfile.ZipFile(unchanged) as third:
            third_header = ET.fromstring(third.read('Contents/header.xml'))
        self.assertEqual(len(second_header.findall('.//hh:paraPr', NS)),
                         len(third_header.findall('.//hh:paraPr', NS)))

    def test_naturally_fitting_summary_is_not_needlessly_compacted(self):
        draft = _draft()
        summary = '미국 CPI 3.0%, PPI 2.1%, FOB 1.2달러·kg당 1.0달러 기록'
        self.assertGreaterEqual(len(summary), 40)
        draft['sections']['us']['summary'] = summary
        with patch('src.overseas_article_digest.compact_report_summary', wraps=compact_report_summary) as compactor:
            result = apply_article_draft_to_hwpx(self.source, self.output, draft)
        us_calls = [call for call in compactor.call_args_list if call.args[1] == 'us']
        self.assertEqual([], us_calls)
        self.assertFalse(result['layout']['us']['summaryAdjusted'])
        self.assertEqual(0, result['layout']['us']['tracking'])
        with zipfile.ZipFile(self.output) as archive:
            slots = _discover_slots({'Contents/section0.xml': archive.read('Contents/section0.xml')})
        self.assertEqual(' - (현지동향) ' + normalize_report_spacing(summary), slots['us'].paragraph.own_text)

    def test_overflowing_known_summary_is_compacted_before_tracking_without_losing_numbers(self):
        draft = _draft()
        summary = '지난주 소고기 생산량은 전주비 13.2% 큰 폭으로 증가했으나 전년비 2.8% 감소한 4억 8,700만 파운드를 기록'
        draft['sections']['us']['summary'] = summary
        with patch('src.overseas_article_digest.compact_report_summary', wraps=compact_report_summary) as compactor:
            result = apply_article_draft_to_hwpx(self.source, self.output, draft)
        us_calls = [call for call in compactor.call_args_list if call.args[1] == 'us']
        self.assertEqual(1, len(us_calls))
        self.assertEqual(40, us_calls[0].kwargs['target'])
        rendered = result['layout']['us']['renderedSummary']
        self.assertTrue(result['layout']['us']['summaryAdjusted'])
        self.assertGreaterEqual(len(rendered), 40)
        for fact in ['13.2%', '2.8%', '4억', '8,700만', '파운드', '생산']:
            self.assertIn(fact, rendered)
        self.assertRegex(rendered, r'전주비\s*13\.2%\s*(↑|증가)')
        self.assertRegex(rendered, r'전년비\s*2\.8%\s*(↓|감소)')

    def test_default_article_application_preserves_uploaded_paragraph_styles_and_spacing(self):
        result = apply_article_draft_to_hwpx(self.source, self.output, _draft())
        with zipfile.ZipFile(self.source) as before, zipfile.ZipFile(self.output) as after:
            old_header = ET.fromstring(before.read('Contents/header.xml'))
            new_header = ET.fromstring(after.read('Contents/header.xml'))
            old_styles = {node.get('id'): node for node in old_header.findall('.//hh:paraPr', NS)}
            new_styles = {node.get('id'): node for node in new_header.findall('.//hh:paraPr', NS)}
            old_slots = _discover_slots({'Contents/section0.xml': before.read('Contents/section0.xml')})
            new_slots = _discover_slots({'Contents/section0.xml': after.read('Contents/section0.xml')})
            section = ET.fromstring(after.read('Contents/section0.xml'))
        for key, slot in new_slots.items():
            old_slot = old_slots[key]
            pairs = [(slot.paragraph, old_slot.paragraph)]
            if slot.title is not None:
                pairs.append((slot.title, old_slot.title))
            for paragraph, original in pairs:
                previous_id = original.attributes['paraPrIDRef']
                current_id = paragraph.attributes['paraPrIDRef']
                layout = result['layout'][key]
                if paragraph is slot.paragraph and not layout['oneLine']:
                    self.assertNotEqual(previous_id, current_id)
                    expected = ET.fromstring(ET.tostring(old_styles[previous_id]))
                    expected.set('id', current_id)
                    core = '{http://www.hancom.co.kr/hwpml/2011/core}'
                    margin = expected.find('hh:margin', NS)
                    left, intent = margin.find(core + 'left'), margin.find(core + 'intent')
                    left.set('value', str(int(left.get('value')) + max(int(intent.get('value')), 0)))
                    intent.set('value', str(-2 * round(layout['hangingIndentPt'] * 100)))
                    if slot.title is None:
                        # Hancom's enum name is inverted for Korean: this
                        # article-only clone prevents mid-syllable word splits.
                        expected.find('hh:breakSetting', NS).set('breakNonLatinWord', 'BREAK_WORD')
                    self.assertEqual(ET.tostring(expected), ET.tostring(new_styles[current_id]))
                    self.assertEqual(layout['wrappedLineAnchor'], 'summary-start' if slot.title else 'local-label-start')
                else:
                    self.assertEqual(previous_id, current_id)
                self.assertEqual(old_styles[previous_id].find('hh:lineSpacing', NS).attrib,
                                 new_styles[current_id].find('hh:lineSpacing', NS).attrib)
                self.assertEqual(ET.tostring(old_styles[previous_id]), ET.tostring(new_styles[previous_id]))
        price_paragraphs = [paragraph for paragraph in section.findall('.//hp:p', NS)
                            if ''.join(paragraph.itertext()) == '가격 데이터: 123.45']
        self.assertEqual(8, len(price_paragraphs))
        self.assertTrue(all(paragraph.get('paraPrIDRef') == '29' for paragraph in price_paragraphs))
        self.assertEqual('140', new_styles['29'].find('hh:lineSpacing', NS).get('value'))

    def test_domestic_summary_continuation_is_not_left_as_old_text(self):
        original = _fixture_section()
        section = original.replace(_p(" - 기존 국내기사 요약 본문").encode(),
                                   (_p(" - 기존 국내기사 요약 본문") + _p(" 이어진 이전 기사 문장")).encode(), 1)
        _package(self.source, section)
        draft = _draft()
        apply_article_draft_to_hwpx(self.source, self.output, draft)
        with zipfile.ZipFile(self.output) as archive:
            data = archive.read('Contents/section0.xml')
            slots = _discover_slots({'Contents/section0.xml': data})
        slot = slots['domestic']
        first = slot.paragraph.own_text.removeprefix(' - ')
        self.assertEqual(first + ''.join(node.own_text for node in slot.continuations), compact_report_summary(draft['sections']['domestic']['summary'], 'domestic'))
        self.assertEqual((), slot.continuations)
        self.assertNotIn('이전 기사 문장'.encode(), data)
        self.assert_preserved(self.source, self.output)

    def test_multi_section_report_maps_country_headings_across_sections(self):
        from src.article_hwpx import _parse_section
        data = _fixture_section()
        root, _ = _parse_section(data)
        group_size = len(root.children) // 4
        parts = []
        for index in range(4):
            nodes = root.children[index * group_size:(index + 1) * group_size]
            part = data[:root.open_end] + b''.join(data[node.start:node.end] for node in nodes) + data[root.close_start:root.end]
            parts.append(part)
        _package(self.source, parts[0], {f'Contents/section{index}.xml': part for index, part in enumerate(parts[1:], 1)})
        apply_article_draft_to_hwpx(self.source, self.output, _draft())
        self.assert_mapping(self.output, _draft())

    def test_generated_namespace_aliases_are_postprocessed(self):
        section = _fixture_section().replace(b'hs:', b'ns0:').replace(b'xmlns:hs=', b'xmlns:ns0=').replace(b'hp:', b'ns1:').replace(b'xmlns:hp=', b'xmlns:ns1=')
        _package(self.source, section)
        apply_article_draft_to_hwpx(self.source, self.output, _draft())
        self.assert_mapping(self.output, _draft())
        with zipfile.ZipFile(self.output) as archive:
            xml = archive.read('Contents/section0.xml')
            self.assertIn(b'<hs:sec', xml)
            self.assertIn(b'xmlns:hp=', xml)
            self.assertNotIn(b'ns0:', xml)
            self.assertNotIn(b'ns1:', xml)

    def test_empty_completed_brief_is_cleared_and_other_briefs_apply(self):
        draft = _draft()
        draft['sections']['japan_egg']['summary'] = ''
        result = apply_article_draft_to_hwpx(self.source, self.output, draft)
        self.assertEqual(11, result['appliedCount'])
        self.assertEqual(7, result['localCount'])
        self.assertEqual(4, result['domesticCount'])
        self.assertEqual(1, result['blankCount'])
        self.assertEqual(['japan_egg'], result['blankSlots'])
        with zipfile.ZipFile(self.output) as archive:
            slots = _discover_slots({'Contents/section0.xml': archive.read('Contents/section0.xml')})
        self.assertEqual(' - (현지동향) ', slots['japan_egg'].paragraph.own_text)
        self.assertTrue(result['layout']['japan_egg']['blank'])
        self.assert_preserved(self.source, self.output)

    def test_partial_draft_clears_missing_and_failed_local_and_domestic_content(self):
        draft = _draft()
        del draft['sections']['us']
        draft['sections']['eu_pork']['status'] = 'summary_error'
        draft['sections']['domestic_chicken']['status'] = 'summary_error'
        draft['sections']['domestic_egg']['summary'] = ''
        result = apply_article_draft_to_hwpx(self.source, self.output, draft)
        self.assertEqual(8, result['appliedCount'])
        self.assertEqual(6, result['localCount'])
        self.assertEqual(2, result['domesticCount'])
        self.assertEqual(4, result['blankCount'])
        self.assertEqual(['us', 'eu_pork', 'domestic_chicken', 'domestic_egg'], result['blankSlots'])
        with zipfile.ZipFile(self.output) as archive:
            slots = _discover_slots({'Contents/section0.xml': archive.read('Contents/section0.xml')})
        for key in result['blankSlots']:
            slot = slots[key]
            self.assertEqual(' - ' if slot.title else ' - (현지동향) ', slot.paragraph.own_text)
            if slot.title:
                self.assertEqual('∙', slot.title.own_text)
            self.assertEqual((), slot.continuations)
            self.assertTrue(result['layout'][key]['blank'])
        self.assert_preserved(self.source, self.output)

    def test_one_valid_brief_applies_and_all_other_slots_are_blank(self):
        draft = _draft()
        draft['sections'] = {'domestic': draft['sections']['domestic']}
        result = apply_article_draft_to_hwpx(self.source, self.output, draft)
        self.assertEqual((1, 0, 1, 11), (result['appliedCount'], result['localCount'], result['domesticCount'], result['blankCount']))
        self.assert_preserved(self.source, self.output)

    def test_blank_slots_remain_discoverable_and_reapplication_is_idempotent(self):
        draft = _draft()
        draft['sections']['eu_pork']['status'] = 'summary_error'
        draft['sections']['domestic_pork']['status'] = 'no_article'
        apply_article_draft_to_hwpx(self.source, self.output, draft)
        again = self.directory / 'partial-again.hwpx'
        result = apply_article_draft_to_hwpx(self.output, again, draft)
        self.assertEqual(['eu_pork', 'domestic_pork'], result['blankSlots'])
        self.assert_preserved(self.output, again)
        with zipfile.ZipFile(self.output) as first, zipfile.ZipFile(again) as second:
            self.assertEqual(first.read('Contents/header.xml'), second.read('Contents/header.xml'))
            self.assertEqual(first.read('Contents/section0.xml'), second.read('Contents/section0.xml'))
        complete = self.directory / 'all-complete-again.hwpx'
        apply_article_draft_to_hwpx(again, complete, _draft())
        self.assert_mapping(complete, _draft())
        self.assert_preserved(again, complete)

    def test_reusing_style_aliases_changes_only_real_run_opening_attributes(self):
        def style(identity, height):
            return f'<hh:charPr id="{identity}" height="{height}"><hh:spacing hangul="0"/></hh:charPr>'
        def header(styles):
            return (f'<hh:head xmlns:hh="{HH}"><hh:charProperties itemCnt="{len(styles)}">'
                    + ''.join(styles) + '</hh:charProperties></hh:head>').encode()
        original = header([style(1, 1300)])
        appended = header([style(1, 1300), style(2, 1300), style(3, 1100), style(4, 1100)])
        literal = 'literal charPrIDRef="2" and <hp:run charPrIDRef="4"> text'
        comment = '<!-- literal <hp:run charPrIDRef="2"/> must remain unchanged -->'
        section = (f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{comment}'
                   f'<hp:p><hp:run note=\'literal charPrIDRef="2"\' charPrIDRef="2"><hp:t>{escape(literal)}</hp:t></hp:run>'
                   '<hp:run charPrIDRef="4"><hp:t>Metadata charPrIDRef="4"</hp:t></hp:run></hp:p></hs:sec>').encode()
        parts, result = _reuse_article_character_styles({'Contents/section0.xml': section}, appended, original)
        edited = parts['Contents/section0.xml']
        root = ET.fromstring(edited)
        self.assertEqual(['1', '3'], [run.get('charPrIDRef') for run in root.findall('.//hp:run', NS)])
        self.assertEqual(literal, root.find('.//hp:t', NS).text)
        self.assertEqual('literal charPrIDRef="2"', root.find('.//hp:run', NS).get('note'))
        self.assertIn(comment.encode(), edited)
        self.assertIn(b'Metadata charPrIDRef="4"', edited)
        header_root = ET.fromstring(result)
        self.assertEqual(['1', '3'], [node.get('id') for node in header_root.findall('.//hh:charPr', NS)])
        self.assertEqual('2', header_root.find('hh:charProperties', NS).get('itemCnt'))
        # Applying the deduplicated package again cannot change it further.
        again, again_header = _reuse_article_character_styles(parts, result, result)
        self.assertEqual(parts, again)
        self.assertEqual(result, again_header)

    def test_blank_domestic_removes_previous_manual_continuation(self):
        section = _fixture_section().replace(_p(' - 기존 국내기사 요약 본문').encode(),
                    (_p(' - 기존 국내기사 요약 본문') + _p(' 이전 주의 이어진 기사 문장')).encode(), 1)
        _package(self.source, section)
        draft = _draft()
        draft['sections']['domestic']['status'] = 'summary_error'
        apply_article_draft_to_hwpx(self.source, self.output, draft)
        with zipfile.ZipFile(self.output) as archive:
            data = archive.read('Contents/section0.xml')
            slot = _discover_slots({'Contents/section0.xml': data})['domestic']
        self.assertEqual('∙', slot.title.own_text)
        self.assertEqual(' - ', slot.paragraph.own_text)
        self.assertEqual((), slot.continuations)
        self.assertNotIn('이전 주의 이어진 기사 문장'.encode(), data)
        self.assert_preserved(self.source, self.output)

    def test_all_blank_or_failed_draft_is_rejected_without_output(self):
        for mode in ('absent', 'empty', 'summary_error', 'no_article', 'source_error', 'model_unavailable', 'missing'):
            with self.subTest(mode=mode):
                draft = _draft()
                if mode == 'absent':
                    draft['sections'] = {}
                else:
                    for section in draft['sections'].values():
                        if mode == 'empty':
                            section['summary'] = ''
                        else:
                            section['status'] = mode
                with self.assertRaises(ArticleHwpxError):
                    apply_article_draft_to_hwpx(self.source, self.output, draft)
                self.assertFalse(self.output.exists())

    def test_unknown_running_and_malformed_sections_are_rejected_without_output(self):
        for mode in ('unknown-key', 'non-dict', 'finding', 'found', 'summarizing', 'unknown-status', 'list-status', 'dict-status', 'null-status', 'non-string-summary', 'short-completed'):
            with self.subTest(mode=mode):
                draft = _draft()
                if mode == 'unknown-key':
                    draft['sections']['unexpected'] = {'status': 'summary_error'}
                elif mode == 'non-dict':
                    draft['sections']['eu_pork'] = None
                elif mode in ('list-status', 'dict-status', 'null-status'):
                    draft['sections']['eu_pork']['status'] = {'list-status': [], 'dict-status': {}, 'null-status': None}[mode]
                elif mode == 'non-string-summary':
                    draft['sections']['eu_pork']['summary'] = []
                elif mode == 'short-completed':
                    draft['sections']['eu_pork']['summary'] = '너무 짧은 요약'
                else:
                    draft['sections']['eu_pork']['status'] = mode
                with self.assertRaises(ArticleHwpxError):
                    apply_article_draft_to_hwpx(self.source, self.output, draft)
                self.assertFalse(self.output.exists())

    def test_real_template_partial_preserves_assets_and_can_be_completed_later(self):
        template = ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx'
        draft = _draft()
        draft['sections']['eu_pork']['status'] = 'summary_error'
        draft['sections']['domestic_pork']['status'] = 'summary_error'
        result = apply_article_draft_to_hwpx(template, self.output, draft)
        self.assertEqual(10, result['appliedCount'])
        self.assert_preserved(template, self.output)
        complete = self.directory / 'real-template-completed.hwpx'
        apply_article_draft_to_hwpx(self.output, complete, _draft())
        self.assert_mapping(complete, _draft())
        self.assert_preserved(self.output, complete)

    def test_original_and_existing_output_are_never_overwritten(self):
        original = self.source.read_bytes()
        with self.assertRaises(ArticleHwpxError):
            apply_article_draft_to_hwpx(self.source, self.source, _draft())
        self.output.write_bytes(b'existing user file')
        with self.assertRaises(ArticleHwpxError):
            apply_article_draft_to_hwpx(self.source, self.output, _draft())
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.output.read_bytes(), b'existing user file')

    def test_missing_or_ambiguous_anchor_fails_safely(self):
        variants = [
            _fixture_section().replace('○ 호주'.encode(), '○ 프랑스'.encode()),
            _fixture_section().replace('□ 육계 수급 및 가격 동향'.encode(), '제목 변경'.encode()),
            _fixture_section().replace('○ 호주'.encode(), '○ 미국'.encode()),
        ]
        for section in variants:
            with self.subTest(section=section[:80]):
                _package(self.source, section)
                with self.assertRaises(ArticleHwpxError):
                    apply_article_draft_to_hwpx(self.source, self.output, _draft())
                self.assertFalse(self.output.exists())

    def test_invalid_zip_dtd_and_paths_are_rejected(self):
        variants = [
            {'section': b'<!DOCTYPE x [<!ENTITY exploit SYSTEM "file:///private">]>' + _fixture_section()},
            {'extra': {'../outside.xml': b'evil'}},
            {'extra': {'Contents/evil.xml': b'<!DOCTYPE x><x/>'}},
            {'extra': {'Contents\\evil.xml': b'evil'}},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                _package(self.source, **variant)
                with self.assertRaises(ArticleHwpxError):
                    apply_article_draft_to_hwpx(self.source, self.output, _draft())
                self.assertFalse(self.output.exists())
        self.source.write_bytes(b'not a zip')
        with self.assertRaises(ArticleHwpxError):
            apply_article_draft_to_hwpx(self.source, self.output, _draft())

    def test_duplicate_members_are_rejected(self):
        with zipfile.ZipFile(self.source, 'a') as archive:
            with self.assertWarns(UserWarning):
                archive.writestr('Contents/section0.xml', _fixture_section())
        with self.assertRaises(ArticleHwpxError):
            apply_article_draft_to_hwpx(self.source, self.output, _draft())

    def test_limits_control_characters_and_bad_metadata_fail(self):
        for value in ('너무 짧음', '가' * 96, '가' * 45 + '\x00'):
            draft = _draft()
            draft['sections']['us']['summary'] = value
            with self.subTest(value=value), self.assertRaises(ArticleHwpxError):
                apply_article_draft_to_hwpx(self.source, self.output, draft)
        draft = _draft()
        draft['sections']['domestic']['article']['publishedDate'] = 'invalid'
        with self.assertRaises(ArticleHwpxError):
            apply_article_draft_to_hwpx(self.source, self.output, draft)

    def test_invalid_style_header_is_safe_and_does_not_publish_output(self):
        _package(self.source, extra={'Contents/header.xml': b'<header>invalid styles</header>'})
        with self.assertRaises(ArticleHwpxError):
            apply_article_draft_to_hwpx(self.source, self.output, _draft())
        self.assertFalse(self.output.exists())

    def test_layout_metrics_are_advisory_not_a_rendered_page_guarantee(self):
        result = apply_article_draft_to_hwpx(self.source, self.output, _draft())
        self.assertEqual('estimate-not-rendered', result['layoutMeasurement'])
        self.assertEqual(set(ARTICLE_SLOT_KEYS), set(result['layout']))
        for key, info in result['layout'].items():
            domestic = key.startswith('domestic')
            self.assertEqual(12 if domestic else 13, info['bodySizePt'])
            self.assertEqual(12 if domestic else 11, info['parentheticalSizePt'])
            self.assertGreaterEqual(info['tracking'], MAX_ARTICLE_TRACKING)
            self.assertLessEqual(info['tracking'], 0)
            self.assertIn(info['measurement'], ('font-metric-estimate', 'em-estimate'))

    def test_all_four_domestic_slots_keep_titles_citations_and_summaries_at_12pt_jung_gothic(self):
        draft = _draft()
        draft['sections']['domestic_egg']['article'].update(
            title='[인싸잇] 브라질산 계란 수입가 논란… 정부 “수급 안정 조치” vs 野 “재정 투입 적정성 따져야”',
            publisher='mediawatch.kr', publishedDate='2026-10-14',
            url='https://www.mediawatch.kr/news/article.html?no=261344',
        )
        apply_article_draft_to_hwpx(self.source, self.output, draft)
        with zipfile.ZipFile(self.output) as package:
            data = package.read('Contents/section0.xml')
            header = ET.fromstring(package.read('Contents/header.xml'))
        fonts = {group.get('lang').lower(): {font.get('id'): font.get('face') for font in group}
                 for group in header.findall('.//hh:fontface', NS)}
        styles = {style.get('id'): style for style in header.findall('.//hh:charPr', NS)}
        slots = _discover_slots({'Contents/section0.xml': data})
        for key, slot in slots.items():
            if not key.startswith('domestic'):
                continue
            for paragraph in (slot.title, slot.paragraph):
                xml = ET.fromstring(f'<root xmlns:hp="{HP}">'.encode() + data[paragraph.start:paragraph.end] + b'</root>')
                for run in xml.findall('.//hp:run', NS):
                    style = styles[run.get('charPrIDRef')]
                    self.assertEqual('1200', style.get('height'), (key, run.find('hp:t', NS).text))
                    self.assertEqual(paragraph is slot.title, style.find('hh:bold', NS) is not None, key)
                    underline = style.find('hh:underline', NS)
                    if paragraph is slot.title:
                        self.assertEqual({'type': 'BOTTOM', 'shape': 'SOLID', 'color': '#000000'}, underline.attrib, key)
                    else:
                        self.assertIsNone(underline, key)
                    for language, identity in style.find('hh:fontRef', NS).attrib.items():
                        self.assertEqual('한양중고딕', fonts[language][identity], (key, language))
        self.assertEqual("∙“브라질산 계란 수입가 논란… 정부 '수급 안정 조치' vs 野 '재정 투입 적정성 따져야'”(인싸잇,10.14.)",
                         slots['domestic_egg'].title.own_text)
        self.assert_preserved(self.source, self.output)

    def test_default_price_report_template_integration(self):
        template = ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx'
        self.assertTrue(template.is_file())
        apply_article_draft_to_hwpx(template, self.output, _draft())
        self.assert_mapping(self.output, _draft())
        self.assert_preserved(template, self.output)

    @unittest.skipUnless(REFERENCE.is_file(), 'User reference is local, not committed to the repository')
    def test_user_reference_integration(self):
        apply_article_draft_to_hwpx(REFERENCE, self.output, _draft())
        self.assert_mapping(self.output, _draft())
        self.assert_preserved(REFERENCE, self.output)

    @unittest.skipUnless(LATEST_UPLOAD.is_file(), 'Latest user upload is local, not committed to the repository')
    def test_latest_article_upload_retains_prices_graphs_and_all_article_slots(self):
        original = LATEST_UPLOAD.read_bytes()
        apply_article_draft_to_hwpx(LATEST_UPLOAD, self.output, _draft())
        self.assertEqual(original, LATEST_UPLOAD.read_bytes())
        self.assert_mapping(self.output, _draft())
        self.assert_preserved(LATEST_UPLOAD, self.output)


if __name__ == '__main__':
    unittest.main()
