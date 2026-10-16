"""Article fonts are semantic, not copied across arbitrary old run positions."""

from pathlib import Path
import builtins
import re
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile

from src.article_hwpx_layout import (
    MAX_ARTICLE_TRACKING, MAX_DOMESTIC_TITLE_TRACKING,
    ArticleLayoutError, ArticleLayoutStyles, article_segments, split_parentheticals,
)


HH = "http://www.hancom.co.kr/hwpml/2011/head"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
NS = {"hh": HH, "hp": HP, "hc": HC}
ROOT = Path(__file__).resolve().parents[1]


def _header():
    attributes = ' textColor="#000000" shadeColor="none" borderFillIDRef="2"'
    def style(identity, height, font, bold=False, spacing=0):
        return (f'<hh:charPr id="{identity}" height="{height}"{attributes}>'
                + '<hh:fontRef ' + ' '.join(f'{language}="{font}"' for language in ['hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user']) + '/>'
                + '<hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>'
                + '<hh:spacing ' + ' '.join(f'{language}="{spacing}"' for language in ['hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user']) + '/>'
                + ('<hh:bold/><hh:underline type="BOTTOM"/>' if bold else '') + '</hh:charPr>')
    return (f'<hh:head xmlns:hh="{HH}" xmlns:hp="{HP}">'
            + '<hh:fontfaces><hh:fontface lang="HANGUL"><hh:font id="0" face="휴먼명조"/><hh:font id="1" face="한양중고딕"/></hh:fontface></hh:fontfaces>'
            + '<hh:charProperties itemCnt="5">' + style(39, 1300, 0) + style(42, 1100, 0)
            + style(30, 1200, 1) + style(51, 1200, 1, True) + style(55, 1000, 1, spacing=-11)
            + '</hh:charProperties><hh:paraProperties itemCnt="2">'
            + '<hh:paraPr id="29" tabPrIDRef="0"><hh:align horizontal="JUSTIFY"/><hh:lineSpacing type="PERCENT" value="140" unit="HWPUNIT"/></hh:paraPr>'
            + '<hh:paraPr id="30" tabPrIDRef="0"><hh:align horizontal="LEFT"/><hh:lineSpacing type="PERCENT" value="110" unit="HWPUNIT"/></hh:paraPr>'
            + '</hh:paraProperties><hh:untouched id="7"/></hh:head>').encode()


def _runs(data):
    return ET.fromstring(f'<root xmlns:hp="{HP}">'.encode() + data + b'</root>')


def _characters(data, header):
    styles = {node.get('id'): node for node in ET.fromstring(header).findall('.//hh:charPr', NS)}
    return [(character, styles[run.get('charPrIDRef')]) for run in _runs(data) for character in (run.find('hp:t', NS).text or '')]


def _margin_header(*, left=400, intent=-2808):
    """Plain native paragraph lengths are doubled URC, not ordinary HWPUNIT."""
    margin = (f'<hh:margin keep="original"><hc:intent value="{intent}" unit="HWPUNIT"/>'
              f'<hc:left value="{left}" unit="HWPUNIT"/><hc:right value="600" unit="HWPUNIT"/>'
              '<hc:prev value="100" unit="HWPUNIT"/><hc:next value="200" unit="HWPUNIT"/></hh:margin>')
    return (_header().replace(f'xmlns:hp="{HP}"'.encode(), f'xmlns:hp="{HP}" xmlns:hc="{HC}"'.encode())
            .replace(b'<hh:paraPr id="29" tabPrIDRef="0">',
                     b'<hh:paraPr id="29" tabPrIDRef="0">' + margin.encode()))


class ArticleHwpxLayoutTests(unittest.TestCase):
    def test_parenthetical_split_preserves_text_and_nested_delimiters(self):
        for text in [' - (현지동향) 가격(kg당 315엔) 안정 전망', '본문(A(B)C) 후속（예시） 종결', '불완전(내용', '혼합(닫힘） 문자', '', '단일본문']:
            result = split_parentheticals(text)
            self.assertEqual(text, ''.join(segment.text for segment in result))
        self.assertEqual([segment.text for segment in split_parentheticals('본문(A(B)C) 후속') if segment.parenthetical], ['(A(B)C)'])

    def test_normal_body_uniform_and_only_complete_parentheses_are_two_points_smaller(self):
        styles = ArticleLayoutStyles(_header())
        text = ' - (현지동향) 전년비 2.8% 감소한 4억 파운드(181만톤) 생산 기록'
        runs, info = styles.build_runs(text, available_width=100000)
        self.assertEqual(text, ''.join(node.find('hp:t', NS).text or '' for node in _runs(runs)))
        characters = _characters(runs, styles.patched_header())
        offset = 0
        for segment in article_segments(text, 'local'):
            height = '1100' if segment.parenthetical else '1300'
            for character, style in characters[offset:offset + len(segment.text)]:
                self.assertEqual(height, style.get('height'), character)
                self.assertEqual('#000000', style.get('textColor'))
                self.assertIsNone(style.find('hh:bold', NS))
                self.assertEqual('0', style.find('hh:fontRef', NS).get('hangul'))
            offset += len(segment.text)
        self.assertEqual((13, 11), (info['bodySizePt'], info['parentheticalSizePt']))
        self.assertEqual(13, info['localLabelSizePt'])

    def test_local_label_including_both_parentheses_is_13pt_but_factual_parentheses_are_11pt(self):
        styles = ArticleLayoutStyles(_header())
        text = ' - (현지동향) 미국 쇠고기 가격(전년비 5.9%) 상승 압력 확대 전망'
        runs, _ = styles.build_runs(text, available_width=100000)
        characters = _characters(runs, styles.patched_header())
        label_start = text.index('(현지동향)')
        label_end = label_start + len('(현지동향)')
        self.assertEqual({'1300'}, {style.get('height') for _, style in characters[label_start:label_end]})
        fact_start = text.index('(전년비')
        fact_end = text.index(')', fact_start) + 1
        self.assertEqual({'1100'}, {style.get('height') for _, style in characters[fact_start:fact_end]})
        self.assertEqual(text, ''.join(character for character, _ in characters))

    def test_local_label_exception_does_not_change_factual_parentheses(self):
        for text, kind, expected in [
            (' - (현지동향) 공급 변화', 'local', False),
            ('(현지동향) 공급 변화', 'local', False),
            ('본문(현지동향) 관련 설명', 'local', True),
        ]:
            with self.subTest(text=text, kind=kind):
                label = next(segment for segment in article_segments(text, kind) if segment.text == '(현지동향)')
                self.assertEqual(expected, label.parenthetical)

    def test_domestic_title_remains_bold_and_entire_citation_is_12pt(self):
        styles = ArticleLayoutStyles(_header())
        text = '∙“해외 시장 가격 동향”(시험매체,10.8.)'
        runs, info = styles.build_runs(text, kind='title', available_width=100000)
        characters = _characters(runs, styles.patched_header())
        self.assertTrue(all(style.find('hh:bold', NS) is not None for _, style in characters))
        self.assertTrue(all(style.find('hh:underline', NS) is not None for _, style in characters))
        self.assertEqual('1200', characters[0][1].get('height'))
        self.assertEqual({'1200'}, {style.get('height') for _, style in characters})
        self.assertEqual((12, 12), (info['bodySizePt'], info['parentheticalSizePt']))

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_plain_uploaded_headline_baseline_gets_emphasis_without_leaking_into_body(self, _metric):
        header = _header().replace(b'face="' + '한양중고딕'.encode() + b'"',
                                   b'face="' + '한양중고딕'.encode() + b'" type="HFT"')
        styles = ArticleLayoutStyles(header, domestic_style_ids=['30'], title_style_ids=['30'])
        self.assertEqual('30', styles.baseline_styles['title'])
        body, body_info = styles.build_runs('가나다라', kind='domestic', available_width=4800)
        title, title_info = styles.build_runs('가나다라', kind='title', available_width=4800)
        changed = styles.patched_header()
        body_styles = {style.get('id'): style for _, style in _characters(body, changed)}
        title_styles = {style.get('id'): style for _, style in _characters(title, changed)}
        self.assertTrue(set(body_styles).isdisjoint(title_styles))
        for style in body_styles.values():
            self.assertIsNone(style.find('hh:bold', NS))
            self.assertIsNone(style.find('hh:underline', NS))
        for style in title_styles.values():
            self.assertIsNotNone(style.find('hh:bold', NS))
            self.assertEqual({'type': 'BOTTOM', 'shape': 'SOLID', 'color': '#000000'},
                             style.find('hh:underline', NS).attrib)
            self.assertEqual('1200', style.get('height'))
        self.assertEqual(0, body_info['tracking'])
        # Measurement must use the forced headline bold even when its source
        # baseline is plain; native HFT synthetic bold adds .05em per glyph.
        self.assertAlmostEqual(50.4, styles.estimate_width('가나다라', kind='title'))
        self.assertEqual(-7, title_info['tracking'])
        self.assertTrue(title_info['oneLine'])
        self.assertGreater(styles.estimate_width('가나다라', kind='title', tracking=-6), 48)
        self.assertEqual(ET.tostring(ET.fromstring(header).find('.//hh:charPr[@id="30"]', NS)),
                         ET.tostring(ET.fromstring(changed).find('.//hh:charPr[@id="30"]', NS)))

    def test_disabled_or_different_headline_underlines_are_normalized_only_on_the_clone(self):
        for original in (b'<hh:underline type="NONE"/>',
                         b'<hh:underline type="TOP" shape="DASH" color="#FF0000"></hh:underline>'):
            with self.subTest(original=original):
                header = _header().replace(b'<hh:underline type="BOTTOM"/>', original)
                styles = ArticleLayoutStyles(header)
                runs, _ = styles.build_runs('∙“해외 수급 동향”(시험매체,10.15.)', kind='title', available_width=100000)
                changed = styles.patched_header()
                for _, style in _characters(runs, changed):
                    self.assertEqual(1, len(style.findall('hh:bold', NS)))
                    self.assertEqual(1, len(style.findall('hh:underline', NS)))
                    self.assertEqual({'type': 'BOTTOM', 'shape': 'SOLID', 'color': '#000000'},
                                     style.find('hh:underline', NS).attrib)
                self.assertIn(original, changed)

    def test_inherited_negative_headline_tracking_is_reset_then_minimally_recomputed(self):
        header = _header()
        old = re.search(rb'<hh:charPr\b[^>]*\bid="51"[^>]*>.*?</hh:charPr>', header, re.S)[0]
        compressed = old.replace(b'="0"', b'="-20"')
        header = header.replace(old, compressed)
        styles = ArticleLayoutStyles(header, title_style_ids=['51'])
        _, natural = styles.build_runs('∙“짧은 제목”(매체,10.15.)', kind='title', available_width=100000)
        self.assertEqual(0, natural['tracking'])
        self.assertEqual('natural-one-line', natural['fitDecision'])
        width = styles.estimate_width('가나다라마바사', kind='title')
        _, tight = styles.build_runs('가나다라마바사', kind='title', available_width=int(width * .92 * 100))
        self.assertLess(tight['tracking'], 0)
        self.assertGreater(tight['tracking'], MAX_ARTICLE_TRACKING)
        self.assertLessEqual(tight['estimatedWidthPt'], tight['availableWidthPt'])
        self.assertGreater(styles.estimate_width('가나다라마바사', kind='title', tracking=tight['tracking'] + 1),
                           tight['availableWidthPt'])

    def test_full_user_egg_headline_keeps_12pt_and_uses_only_needed_title_tracking(self):
        with zipfile.ZipFile(ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx') as package:
            header = package.read('Contents/header.xml')
        styles = ArticleLayoutStyles(header)
        text = "∙“브라질산 계란 수입가 논란… 정부 '수급 안정 조치' vs 野 '재정 투입 적정성 따져야'”(인싸잇,10.14.)"
        self.assertGreater(styles.estimate_width(text, kind='title', tracking=MAX_ARTICLE_TRACKING), 466.04)
        runs, info = styles.build_runs(text, kind='title', available_width=46604)
        self.assertLess(info['tracking'], MAX_ARTICLE_TRACKING)
        self.assertGreaterEqual(info['tracking'], MAX_DOMESTIC_TITLE_TRACKING)
        self.assertEqual('minimum-tracking-one-line', info['fitDecision'])
        self.assertTrue(info['oneLine'])
        self.assertEqual(1, info['estimatedLines'])
        self.assertLessEqual(styles.estimate_width(text, kind='title', tracking=info['tracking']), 466.04)
        self.assertGreater(styles.estimate_width(text, kind='title', tracking=info['tracking'] + 1), 466.04)
        characters = _characters(runs, styles.patched_header())
        self.assertEqual(text, ''.join(character for character, _ in characters))
        for _, style in characters:
            self.assertEqual('1200', style.get('height'))
            self.assertIsNotNone(style.find('hh:bold', NS))
            self.assertEqual('BOTTOM', style.find('hh:underline', NS).get('type'))
            self.assertTrue(all(value == '100' for value in style.find('hh:ratio', NS).attrib.values()))

        # An explicit, more conservative caller cap still takes precedence.
        _, capped = styles.build_runs(text, kind='title', available_width=46604, max_tracking=-20)
        self.assertEqual(0, capped['tracking'])
        self.assertFalse(capped['oneLine'])
        self.assertEqual('natural-wrap', capped['fitDecision'])

    def test_title_relaxation_does_not_change_body_floor_or_shorten_unfittable_titles(self):
        styles = ArticleLayoutStyles(_header())
        text = '원문을 보존하는 기사 제목과 요약 문장'
        for kind in ('local', 'domestic', 'title'):
            width = styles.estimate_width(text, kind=kind)
            _, layout = styles.build_runs(text, kind=kind, available_width=int(width * .77 * 100))
            if kind == 'title':
                self.assertTrue(layout['oneLine'])
                self.assertLess(layout['tracking'], -20)
                self.assertEqual(MAX_DOMESTIC_TITLE_TRACKING, layout['minimumTracking'])
            else:
                self.assertFalse(layout['oneLine'])
                self.assertEqual(0, layout['tracking'])
                self.assertEqual(MAX_ARTICLE_TRACKING, layout['minimumTracking'])
        runs, layout = styles.build_runs(text, kind='title', available_width=1000, max_tracking=-80)
        self.assertFalse(layout['oneLine'])
        self.assertEqual(0, layout['tracking'])
        self.assertEqual(text, ''.join(character for character, _ in _characters(runs, styles.patched_header())))

    def test_domestic_titles_and_bodies_keep_all_parentheses_numbers_and_dates_at_12pt(self):
        for kind, text in [
            ('title', '∙“수입가격(CPI) 상승… 시장 전망”(인싸잇,10.14.)'),
            ('domestic', ' - 계란 수입가격(개당 1300원)은 전년비 2.8배(미국산 464원) 수준'),
        ]:
            with self.subTest(kind=kind):
                styles = ArticleLayoutStyles(_header())
                self.assertTrue(all(not segment.parenthetical for segment in article_segments(text, kind)))
                runs, info = styles.build_runs(text, kind=kind, available_width=100000)
                characters = _characters(runs, styles.patched_header())
                self.assertEqual(text, ''.join(character for character, _ in characters))
                self.assertEqual({'1200'}, {style.get('height') for _, style in characters})
                self.assertEqual((12, 12), (info['bodySizePt'], info['parentheticalSizePt']))

    def test_real_template_domestic_all_language_fonts_are_jung_gothic_without_changing_shared_styles(self):
        with zipfile.ZipFile(ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx') as package:
            header = package.read('Contents/header.xml')
        original = ET.fromstring(header)
        fonts = {group.get('lang').lower(): {font.get('id'): font.get('face') for font in group}
                 for group in original.findall('.//hh:fontface', NS)}
        for kind in ['title', 'domestic']:
            styles = ArticleLayoutStyles(header)
            runs, _ = styles.build_runs('∙“계란(수입가격 1300원)”(인싸잇,10.14.)', kind=kind)
            changed = styles.patched_header()
            characters = _characters(runs, changed)
            for _, style in characters:
                self.assertEqual('1200', style.get('height'))
                for language, identity in style.find('hh:fontRef', NS).attrib.items():
                    self.assertEqual('한양중고딕', fonts[language][identity], language)
            after = ET.fromstring(changed)
            self.assertEqual(ET.tostring(original.find('hh:refList/hh:fontfaces', NS)),
                             ET.tostring(after.find('hh:refList/hh:fontfaces', NS)))

    def test_local_all_language_faces_are_human_myeongjo_and_shared_font_entries_are_preserved(self):
        with zipfile.ZipFile(ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx') as package:
            header = package.read('Contents/header.xml')
        original = ET.fromstring(header)
        styles = ArticleLayoutStyles(header, local_style_ids=['30'], domestic_style_ids=['39'], title_style_ids=['39'])
        # Wrong-role source run positions cannot swap the semantic roles.
        self.assertEqual(header, styles.patched_header())
        text = ' - (현지동향) 미국 계란 M 규격 kg당 315엔(전년비 5.9%), 공급 보합 유지 전망'
        runs, _ = styles.build_runs(text, kind='local')
        changed = styles.patched_header()
        after = ET.fromstring(changed)
        fonts = {group.get('lang').lower(): {font.get('id'): font.get('face') for font in group}
                 for group in after.findall('.//hh:fontface', NS)}
        for _, style in _characters(runs, changed):
            self.assertIn(style.get('height'), ('1300', '1100'))
            self.assertIsNone(style.find('hh:bold', NS))
            self.assertIsNone(style.find('hh:underline', NS))
            references = style.find('hh:fontRef', NS).attrib
            self.assertEqual({'hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user'}, set(references))
            for language, identity in references.items():
                self.assertEqual('휴먼명조', fonts[language][identity], language)
            for name, expected in [('ratio', '100'), ('relSz', '100'), ('offset', '0')]:
                self.assertEqual({expected}, set(style.find('hh:' + name, NS).attrib.values()))
        for old_group in original.findall('.//hh:fontface', NS):
            new_group = after.find(f'.//hh:fontface[@lang="{old_group.get("lang")}"]', NS)
            self.assertEqual(len(new_group), int(new_group.get('fontCnt')))
            self.assertEqual([ET.tostring(font) for font in old_group],
                             [ET.tostring(font) for font in list(new_group)[:len(old_group)]])
        before_styles = re.findall(rb'<hh:charPr\b[^>]*>.*?</hh:charPr>', header, re.S)
        self.assertEqual(before_styles,
                         re.findall(rb'<hh:charPr\b[^>]*>.*?</hh:charPr>', changed, re.S)[:len(before_styles)])
        # Reusing the same source does not append another identical font entry.
        reapplied = ArticleLayoutStyles(changed)
        reapplied.build_runs(text, kind='local')
        updated = ET.fromstring(reapplied.patched_header())
        self.assertEqual(ET.tostring(after.find('hh:refList/hh:fontfaces', NS)),
                         ET.tostring(updated.find('hh:refList/hh:fontfaces', NS)))

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_short_domestic_chicken_body_discards_inherited_tracking_and_title_emphasis(self, _metric):
        header = _header()
        original = re.search(rb'<hh:charPr\b[^>]*\bid="30"[^>]*>.*?</hh:charPr>', header, re.S)[0]
        altered = original
        altered = re.sub(rb'(<hh:spacing\b[^>]*)(/>)',
                         lambda match: match[1].replace(b'="0"', b'="-20"') + match[2], altered)
        altered = altered.replace(b'</hh:charPr>', b'<hh:bold/><hh:underline type="BOTTOM"/></hh:charPr>')
        header = header.replace(original, altered)
        styles = ArticleLayoutStyles(header, domestic_style_ids=['30'])
        text = ' - 미국 USDA, 수입 재검사 미실시 즉석 닭고기 스튜 약 4596 파운드 리콜'
        runs, info = styles.build_runs(text, kind='domestic', available_width=46604, max_lines=1)
        self.assertEqual(0, info['tracking'])
        self.assertEqual('natural-one-line', info['fitDecision'])
        for _, style in _characters(runs, styles.patched_header()):
            self.assertEqual('1200', style.get('height'))
            self.assertEqual({'0'}, set(style.find('hh:spacing', NS).attrib.values()))
            self.assertIsNone(style.find('hh:bold', NS))
            self.assertIsNone(style.find('hh:underline', NS))
        self.assertIn(altered, styles.patched_header())

    def test_malformed_language_font_count_cannot_publish_appended_font_entries(self):
        with zipfile.ZipFile(ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx') as package:
            header = package.read('Contents/header.xml')
        malformed = re.sub(rb'(<hh:fontface\b[^>]*lang="LATIN"[^>]*fontCnt=")\d+', rb'\g<1>99', header)
        self.assertNotEqual(header, malformed)
        styles = ArticleLayoutStyles(malformed)
        styles.build_runs(' - (현지동향) 해외 축산물 가격 및 수급 안정 전망')
        with self.assertRaises(ArticleLayoutError):
            styles.patched_header()

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_all_article_effective_sizes_and_width_normalized_only_on_article_clones(self, _metric):
        original = _margin_header()
        altered = original.replace(
            b'<hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>',
            b'<hh:ratio hangul="70" latin="80" hanja="90" japanese="70" other="80" symbol="90" user="70"/>')
        geometry = (b'<hh:relSz hangul="140" latin="125"/>'
                    b'<hh:offset hangul="20" latin="10"/>')
        altered = re.sub(rb'(<hh:spacing\b[^>]*/>)', lambda match: match[0] + geometry, altered)
        reference = ArticleLayoutStyles(original)
        styles = ArticleLayoutStyles(altered)
        text = ' - 해외 계란 공급 감소로 소비자가격 상승 압력 확대 전망 ' * 3
        for kind in ('local', 'domestic', 'title'):
            runs, info = styles.build_runs(text, kind=kind, available_width=46604)
            self.assertEqual(reference.measure_layout(text, kind=kind, available_width=46604), info)
            self.assertEqual(reference.marker_prefix_width(text, kind=kind, marker_length=3,
                                                          available_width=46604, paragraph_style_id='29'),
                             styles.marker_prefix_width(text, kind=kind, marker_length=3,
                                                        available_width=46604, paragraph_style_id='29'))
            for _, style in _characters(runs, styles.patched_header()):
                self.assertEqual('1300' if kind == 'local' else '1200', style.get('height'))
                for name, expected in [('ratio', '100'), ('relSz', '100'), ('offset', '0')]:
                    self.assertEqual({language: expected for language in
                                      ('hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user')},
                                     style.find('hh:' + name, NS).attrib)
        local, _ = styles.build_runs(' - (현지동향) 현지동향 글자 모양 통일', available_width=100000)
        local_style = _characters(local, styles.patched_header())[0][1]
        self.assertEqual('100', local_style.find('hh:ratio', NS).get('hangul'))
        self.assertEqual('100', local_style.find('hh:relSz', NS).get('hangul'))
        self.assertEqual('0', local_style.find('hh:offset', NS).get('hangul'))
        old_styles = re.findall(rb'<hh:charPr\b[^>]*>.*?</hh:charPr>', altered, re.S)
        new_styles = re.findall(rb'<hh:charPr\b[^>]*>.*?</hh:charPr>', styles.patched_header(), re.S)
        self.assertEqual(old_styles, new_styles[:len(old_styles)])

    def test_missing_domestic_geometry_defaults_are_added_and_ambiguous_geometry_rejected(self):
        missing = re.sub(rb'<hh:ratio\b[^>]*/>', b'', _header())
        styles = ArticleLayoutStyles(missing)
        runs, _ = styles.build_runs('국내기사 기본 크기', kind='domestic')
        style = _characters(runs, styles.patched_header())[0][1]
        for name, value in [('ratio', '100'), ('relSz', '100'), ('offset', '0')]:
            self.assertEqual({value}, set(style.find('hh:' + name, NS).attrib.values()))
        for addition in (b'<hh:ratio hangul="70"/>', b'<hh:switch/>',
                         b'<hh:relSz><hh:ratio hangul="70"/></hh:relSz>'):
            with self.subTest(addition=addition):
                header = _header().replace(b'<hh:fontRef ', addition + b'<hh:fontRef ')
                with self.assertRaises(ArticleLayoutError):
                    ArticleLayoutStyles(header).build_runs('국내기사', kind='domestic')

    def test_existing_character_styles_and_rest_of_header_unchanged(self):
        original = _header()
        styles = ArticleLayoutStyles(original)
        styles.build_runs(' - (현지동향) 새로운 본문')
        changed = styles.patched_header()
        pattern = br'<hh:charPr\b[^>]*>.*?</hh:charPr>'
        old_styles = re.findall(pattern, original, re.S)
        new_styles = re.findall(pattern, changed, re.S)
        self.assertEqual(old_styles, new_styles[:len(old_styles)])
        self.assertIn(b'<hh:untouched id="7"/>', changed)
        parsed = ET.fromstring(changed)
        container = parsed.find('hh:charProperties', NS)
        self.assertEqual(int(container.get('itemCnt')), len(container))
        self.assertEqual(len(container), len({node.get('id') for node in container}))

    def test_styles_reused_for_identical_size_and_tracking(self):
        styles = ArticleLayoutStyles(_header())
        styles.build_runs(' - (현지동향) 첫번째 본문', available_width=100000)
        first = styles.patched_header()
        styles.build_runs(' - (현지동향) 두번째 본문', available_width=100000)
        self.assertEqual(first, styles.patched_header())

    def test_article_paragraph_spacing_clone_caps_at_120_and_keeps_original(self):
        original = _header()
        styles = ArticleLayoutStyles(original)
        clone_id = styles.paragraph_style('29')
        self.assertNotEqual('29', clone_id)
        changed = styles.patched_header()
        before = ET.fromstring(original)
        after = ET.fromstring(changed)
        prior = {node.get('id'): ET.tostring(node) for node in before.findall('.//hh:paraPr', NS)}
        current = {node.get('id'): node for node in after.findall('.//hh:paraPr', NS)}
        for identity, definition in prior.items():
            self.assertEqual(definition, ET.tostring(current[identity]))
        expected = ET.fromstring(prior['29'])
        expected.set('id', clone_id)
        expected.find('hh:lineSpacing', NS).set('value', '120')
        self.assertEqual(ET.tostring(expected), ET.tostring(current[clone_id]))
        properties = after.find('hh:paraProperties', NS)
        self.assertEqual('3', properties.get('itemCnt'))
        self.assertEqual(3, len(properties))

    def test_already_compact_paragraph_style_is_not_expanded_or_recloned(self):
        styles = ArticleLayoutStyles(_header())
        self.assertEqual('30', styles.paragraph_style('30'))
        self.assertEqual(_header(), styles.patched_header())
        first_clone = styles.paragraph_style('29')
        first = styles.patched_header()
        for _ in range(12):
            self.assertEqual(first_clone, styles.paragraph_style('29'))
        self.assertEqual(first, styles.patched_header())
        # A subsequent application sees the clone at 120%; its own reference
        # remains stable rather than producing another appended paragraph ID.
        reapplied = ArticleLayoutStyles(first)
        self.assertEqual(first_clone, reapplied.paragraph_style(first_clone))
        self.assertEqual(first, reapplied.patched_header())

    def test_missing_nonpercentage_or_invalid_article_spacing_fails_safely(self):
        styles = ArticleLayoutStyles(_header())
        with self.assertRaises(ArticleLayoutError):
            styles.paragraph_style('999')
        for replacement in [b'type="FIXED" value="140"', b'type="PERCENT" value="unknown"']:
            header = _header().replace(b'type="PERCENT" value="140"', replacement)
            with self.assertRaises(ArticleLayoutError):
                ArticleLayoutStyles(header).paragraph_style('29')

    def test_hanging_indent_rounds_hwpunit_before_doubling_so_urc_unit_bit_stays_zero(self):
        for prefix_pt, expected in [(17.316, -3464), (18.216, -3644), (.006, -2)]:
            with self.subTest(prefix_pt=prefix_pt):
                styles = ArticleLayoutStyles(_margin_header())
                clone = styles.hanging_paragraph_style('29', prefix_pt)
                paragraph = ET.fromstring(styles.patched_header()).find(f'.//hh:paraPr[@id="{clone}"]', NS)
                indent = paragraph.find('hh:margin/hc:intent', NS)
                self.assertEqual(expected, int(indent.get('value')))
                self.assertEqual(0, int(indent.get('value')) & 1)
                self.assertEqual('HWPUNIT', indent.get('unit'))

    def test_hanging_indent_clones_only_margin_and_retains_all_shared_styles_and_spacing(self):
        original = _margin_header()
        styles = ArticleLayoutStyles(original)
        clone = styles.hanging_paragraph_style('29', 17.316)
        before, after = ET.fromstring(original), ET.fromstring(styles.patched_header())
        old_paragraphs = {node.get('id'): node for node in before.findall('.//hh:paraPr', NS)}
        current = {node.get('id'): node for node in after.findall('.//hh:paraPr', NS)}
        self.assertNotIn(clone, old_paragraphs)
        self.assertEqual(len(old_paragraphs) + 1, len(current))
        for identity, prior in old_paragraphs.items():
            self.assertEqual(ET.tostring(prior), ET.tostring(current[identity]))
        expected = ET.fromstring(ET.tostring(old_paragraphs['29']))
        expected.set('id', clone)
        expected.find('hh:margin/hc:intent', NS).set('value', '-3464')
        self.assertEqual(ET.tostring(expected), ET.tostring(current[clone]))
        self.assertEqual('140', current[clone].find('hh:lineSpacing', NS).get('value'))
        self.assertEqual('JUSTIFY', current[clone].find('hh:align', NS).get('horizontal'))
        self.assertEqual(ET.tostring(before.find('hh:charProperties', NS)),
                         ET.tostring(after.find('hh:charProperties', NS)))
        self.assertEqual(str(len(current)), after.find('hh:paraProperties', NS).get('itemCnt'))

    def test_hanging_indent_preserves_positive_first_line_offset_and_right_margin(self):
        original = _margin_header(left=400, intent=800)
        styles = ArticleLayoutStyles(original)
        clone = styles.hanging_paragraph_style('29', 17.316)
        paragraph = ET.fromstring(styles.patched_header()).find(f'.//hh:paraPr[@id="{clone}"]', NS)
        new_left = int(paragraph.find('hh:margin/hc:left', NS).get('value'))
        new_indent = int(paragraph.find('hh:margin/hc:intent', NS).get('value'))
        self.assertEqual(1200, new_left)
        self.assertEqual(-3464, new_indent)
        self.assertEqual(400 + max(800, 0), new_left + max(new_indent, 0))
        self.assertEqual('600', paragraph.find('hh:margin/hc:right', NS).get('value'))
        self.assertEqual('100', paragraph.find('hh:margin/hc:prev', NS).get('value'))
        self.assertEqual('200', paragraph.find('hh:margin/hc:next', NS).get('value'))

    def test_hanging_indent_clone_is_reused_and_reapplication_does_not_grow_style_chain(self):
        styles = ArticleLayoutStyles(_margin_header())
        clone = styles.hanging_paragraph_style('29', 17.316)
        first = styles.patched_header()
        for _ in range(12):
            self.assertEqual(clone, styles.hanging_paragraph_style('29', 17.316))
        self.assertEqual(first, styles.patched_header())
        reapplied = ArticleLayoutStyles(first)
        self.assertEqual(clone, reapplied.hanging_paragraph_style(clone, 17.316))
        self.assertEqual(first, reapplied.patched_header())

    def test_already_aligned_hanging_indent_returns_original_style_without_clone(self):
        original = _margin_header(left=400, intent=-3464)
        styles = ArticleLayoutStyles(original)
        self.assertEqual('29', styles.hanging_paragraph_style('29', 17.316))
        self.assertEqual(original, styles.patched_header())

    def test_hanging_indent_rejects_odd_ambiguous_switch_or_missing_unit_styles_safely(self):
        valid = _margin_header()
        variants = [
            _header(),
            _margin_header(left=401),
            _margin_header(intent=-2807),
            valid.replace(b'<hc:intent value="-2808" unit="HWPUNIT"/>', b'<hc:intent value="-2808"/>'),
            valid.replace(b'<hc:left value="400" unit="HWPUNIT"/>', b'<hc:left value="400" unit="CHAR"/>'),
            valid.replace(b'<hc:intent value="-2808"', b'<hc:intent value="unknown"'),
            valid.replace(b'<hc:left value="400" unit="HWPUNIT"/>', b'<hc:left value="400" unit="HWPUNIT"/><hc:left value="400" unit="HWPUNIT"/>'),
            valid.replace(b'</hh:margin>', b'</hh:margin><hh:margin><hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/></hh:margin>', 1),
            valid.replace(b'<hh:margin keep="original">', b'<hp:switch><hp:case><hh:margin keep="original">', 1)
                 .replace(b'</hh:margin>', b'</hh:margin></hp:case></hp:switch>', 1),
        ]
        for header in variants:
            with self.subTest(header=header):
                styles = ArticleLayoutStyles(header)
                with self.assertRaises(ArticleLayoutError):
                    styles.hanging_paragraph_style('29', 17.316)
                self.assertEqual(header, styles.patched_header())
        styles = ArticleLayoutStyles(valid)
        with self.assertRaises(ArticleLayoutError):
            styles.hanging_paragraph_style('999', 17.316)
        for prefix_pt in [0, -1, float('inf'), float('-inf'), float('nan')]:
            with self.subTest(prefix_pt=prefix_pt):
                with self.assertRaises(ArticleLayoutError):
                    styles.hanging_paragraph_style('29', prefix_pt)
        self.assertEqual(valid, styles.patched_header())

    def test_justified_marker_uses_uniform_role_font_for_mixed_size_and_numeric_wrapped_text(self):
        with zipfile.ZipFile(ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx') as package:
            header = package.read('Contents/header.xml')
        styles = ArticleLayoutStyles(header)
        examples = [
            (' - (현지동향) 호주 9개월 누적 쇠고기 수출 120만 9000톤(전년 동기비 7%↑), 역대 최고치 기록', '32'),
            (' - (현지동향) 미국 육계 병아리 입식수 전주보다 363만 2000마리 줄어 1억 8968만 9000마리 기록', '29'),
        ]
        # Prior native snapshots used Poppy/Myeongjo mixed references and are
        # not ground truth for the newly uniform Human Myeongjo face. This
        # estimate still includes first-line justification and quantized space
        # distribution without embedding country/week-specific caret offsets.
        for text, paragraph_id in examples:
            with self.subTest(paragraph_id=paragraph_id):
                actual = styles.marker_prefix_width(text, kind='local', marker_length=3,
                                                    available_width=46320, paragraph_style_id=paragraph_id)
                self.assertEqual(round(actual, 2), actual)
                self.assertLess(actual, 463.2)
                self.assertGreater(actual, styles.estimate_width(text[:3], kind='local'))
        self.assertEqual(header, styles.patched_header())

    def test_marker_effective_first_line_width_includes_plain_margin_and_positive_indent(self):
        with zipfile.ZipFile(ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx') as package:
            header = package.read('Contents/header.xml')
        parsed = ET.fromstring(header)
        paragraph = parsed.find('.//hh:paraPr[@id="29"]', NS)
        margin = paragraph.find('hh:margin', NS)
        margin.find('hc:left', NS).set('value', '200')
        margin.find('hc:right', NS).set('value', '400')
        margin.find('hc:intent', NS).set('value', '600')
        styles = ArticleLayoutStyles(ET.tostring(parsed))
        text = ' - (현지동향) 미국 육계 병아리 입식수 전주보다 363만 2000마리 줄어 1억 8968만 9000마리 기록'
        # Six hundred ordinary HWPUNIT of additional cell room compensate
        # exactly for the doubled left/right/positive first-line margins.
        actual = styles.marker_prefix_width(text, kind='local', marker_length=3,
                                            available_width=46920, paragraph_style_id='29')
        reference = ArticleLayoutStyles(header).marker_prefix_width(
            text, kind='local', marker_length=3, available_width=46320, paragraph_style_id='29')
        self.assertEqual(reference, actual)

    def test_nonjustified_and_unwrapped_markers_keep_nominal_width_without_style_changes(self):
        for horizontal in ['LEFT', 'RIGHT', 'CENTER', 'DISTRIBUTE', 'DISTRIBUTE_SPACE']:
            header = _margin_header().replace(b'horizontal="JUSTIFY"', f'horizontal="{horizontal}"'.encode())
            styles = ArticleLayoutStyles(header)
            text = ' - (현지동향) 원문 사실과 조건을 보존하는 긴 요약 ' * 3
            expected = styles.estimate_width(text[:3], kind='local', tracking=-2)
            self.assertEqual(expected, styles.marker_prefix_width(text, kind='local', marker_length=3,
                                                                 available_width=10000, paragraph_style_id='29', tracking=-2))
            self.assertEqual(header, styles.patched_header())
        header = _margin_header()
        styles = ArticleLayoutStyles(header)
        text = ' - (현지동향) 짧은 문구'
        self.assertEqual(styles.estimate_width(text[:3], kind='local'),
                         styles.marker_prefix_width(text, kind='local', marker_length=3,
                                                    available_width=100000, paragraph_style_id='29'))
        self.assertEqual(header, styles.patched_header())

    def test_marker_optional_linebreak_import_falls_back_only_for_import_errors(self):
        header = _margin_header()
        styles = ArticleLayoutStyles(header)
        text = ' - (현지동향) 원문 사실과 조건을 보존하는 긴 요약 ' * 3
        expected = styles.estimate_width(text[:3], kind='local')
        original_import = builtins.__import__

        def missing_engine(name, *args, **kwargs):
            if name == 'hwpx.form_fit.measure':
                raise ImportError('optional old deployment')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=missing_engine):
            self.assertEqual(expected, styles.marker_prefix_width(text, kind='local', marker_length=3,
                                                                 available_width=10000, paragraph_style_id='29'))
            # Missing measurement dependencies must not hide malformed source
            # units, or authorize an unsafe paragraph clone.
            with self.assertRaises(ArticleLayoutError):
                ArticleLayoutStyles(_margin_header(left=401)).marker_prefix_width(
                    text, kind='local', marker_length=3, available_width=10000, paragraph_style_id='29')
            invalid_condense = header.replace(b'tabPrIDRef="0">', b'tabPrIDRef="0" condense="invalid">', 1)
            with self.assertRaises(ArticleLayoutError):
                ArticleLayoutStyles(invalid_condense).marker_prefix_width(
                    text, kind='local', marker_length=3, available_width=10000, paragraph_style_id='29')
        self.assertEqual(header, styles.patched_header())

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_marker_quantization_honors_native_hft_title_bold_guard(self, _metric):
        header = _margin_header(left=0, intent=0).replace(b'<hc:right value="600"', b'<hc:right value="0"')
        header = header.replace(b'face="' + '한양중고딕'.encode() + b'"',
                                b'face="' + '한양중고딕'.encode() + b'" type="HFT"')
        styles = ArticleLayoutStyles(header)
        text = '가' * 30
        normal = styles.marker_prefix_width(text, kind='domestic', marker_length=1,
                                            available_width=10000, paragraph_style_id='29')
        bold = styles.marker_prefix_width(text, kind='title', marker_length=1,
                                          available_width=10000, paragraph_style_id='29')
        self.assertEqual(12, normal)
        self.assertAlmostEqual(12.6, bold)
        ttf = ArticleLayoutStyles(header.replace(b'type="HFT"', b'type="TTF"'))
        self.assertEqual(12, ttf.marker_prefix_width(text, kind='title', marker_length=1,
                                                   available_width=10000, paragraph_style_id='29'))

    def test_marker_rejects_invalid_inputs_unknown_alignment_and_malformed_margin(self):
        text = ' - (현지동향) 원문 사실과 조건을 보존하는 긴 요약 ' * 3
        defaults = dict(kind='local', marker_length=3, available_width=10000, paragraph_style_id='29')
        variants = [
            dict(kind='unknown'), dict(marker_length=0), dict(marker_length=len(text) + 1),
            dict(marker_length=3.5), dict(available_width=0), dict(paragraph_style_id='999'),
        ]
        for changed in variants:
            with self.subTest(changed=changed):
                with self.assertRaises(ArticleLayoutError):
                    ArticleLayoutStyles(_margin_header()).marker_prefix_width(text, **(defaults | changed))
        header = _margin_header()
        malformed = [
            header.replace(b'horizontal="JUSTIFY"', b'horizontal="unknown"'),
            header.replace(b'<hc:right value="600" unit="HWPUNIT"/>', b'<hc:right value="600"/>'),
            header.replace(b'<hc:right value="600"', b'<hc:right value="601"'),
            header.replace(b'<hc:right value="600"', b'<hc:right value="unknown"'),
            header.replace(b'<hc:left value="400" unit="HWPUNIT"/>', b'<hc:left value="400" unit="HWPUNIT"/><hc:left value="400" unit="HWPUNIT"/>'),
            header.replace(b'<hh:margin keep="original">', b'<hp:switch><hp:case><hh:margin keep="original">', 1)
                  .replace(b'</hh:margin>', b'</hh:margin></hp:case></hp:switch>', 1),
            header.replace(b'value="-2808"', b'value="200000"'),
            header.replace(b'tabPrIDRef="0">', b'tabPrIDRef="0" condense="76">', 1),
        ]
        for source in malformed:
            with self.subTest(source=source):
                with self.assertRaises(ArticleLayoutError):
                    ArticleLayoutStyles(source).marker_prefix_width(text, **defaults)

    def test_marker_compressed_space_paragraph_keeps_safe_nominal_estimate(self):
        header = _margin_header().replace(b'tabPrIDRef="0">', b'tabPrIDRef="0" condense="20">', 1)
        styles = ArticleLayoutStyles(header)
        text = ' - (현지동향) 원문 사실과 조건을 보존하는 긴 요약 ' * 3
        self.assertEqual(styles.estimate_width(text[:3], kind='local'),
                         styles.marker_prefix_width(text, kind='local', marker_length=3,
                                                    available_width=10000, paragraph_style_id='29'))
        self.assertEqual(header, styles.patched_header())

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_tracking_bounded_without_clipping_or_reducing_body_font(self, _metric):
        styles = ArticleLayoutStyles(_header())
        text = ' - (현지동향) ' + '가나다라마바사아자차' * 12
        runs, info = styles.build_runs(text, max_tracking=-80)
        self.assertEqual(-20, MAX_ARTICLE_TRACKING)
        self.assertEqual(0, info['tracking'])
        self.assertEqual('natural-wrap', info['fitDecision'])
        self.assertGreater(info['estimatedLines'], 1)
        self.assertFalse(info['oneLine'])
        self.assertEqual(text, ''.join(node.find('hp:t', NS).text or '' for node in _runs(runs)))
        self.assertEqual('em-estimate', info['measurement'])
        self.assertEqual({1300}, {int(style.get('height')) for _, style in _characters(runs, styles.patched_header())})

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_tracking_is_only_as_negative_as_needed(self, _metric):
        styles = ArticleLayoutStyles(_header())
        _, easy = styles.build_runs('가나다라', available_width=100000)
        _, tight = styles.build_runs('가나다라', available_width=5100)
        self.assertEqual(0, easy['tracking'])
        self.assertTrue(tight['oneLine'])
        self.assertGreater(tight['tracking'], MAX_ARTICLE_TRACKING)
        self.assertLess(tight['tracking'], 0)

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_all_roles_respect_own_floor_and_title_uses_exact_minimum(self, _metric):
        for kind in ['local', 'title', 'domestic']:
            styles = ArticleLayoutStyles(_header())
            text = '가나다라마바사'
            natural = styles.estimate_width(text, kind=kind)
            available = int(natural * .9 * 100)
            _, info = styles.build_runs(text, kind=kind, available_width=available, max_tracking=-80)
            self.assertTrue(info['oneLine'])
            floor = MAX_DOMESTIC_TITLE_TRACKING if kind == 'title' else MAX_ARTICLE_TRACKING
            self.assertGreaterEqual(info['tracking'], floor)
            self.assertLessEqual(styles.estimate_width(text, kind=kind, tracking=info['tracking']), available / 100)
            self.assertGreater(styles.estimate_width(text, kind=kind, tracking=info['tracking'] + 1), available / 100)
            _, wrap = styles.build_runs(text, kind=kind, available_width=int(natural * .8 * 100), max_tracking=-80)
            if kind == 'title':
                self.assertLess(wrap['tracking'], MAX_ARTICLE_TRACKING)
                self.assertGreaterEqual(wrap['tracking'], floor)
                self.assertTrue(wrap['oneLine'])
            else:
                self.assertEqual(wrap['tracking'], 0)
                self.assertFalse(wrap['oneLine'])

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_native_hft_synthetic_bold_advance_is_counted_not_assumed_normal(self, _metric):
        header = _header().replace(b'face="' + '한양중고딕'.encode() + b'"', b'face="' + '한양중고딕'.encode() + b'" type="HFT"')
        styles = ArticleLayoutStyles(header)
        self.assertAlmostEqual(styles.estimate_width('가나다라', kind='domestic'), 48)
        self.assertAlmostEqual(styles.estimate_width('가나다라', kind='title'), 50.4)
        self.assertAlmostEqual(styles.estimate_width('가나다라', kind='title', tracking=-10), 46.62)
        _, info = styles.build_runs('가나다라', kind='title', available_width=4800)
        self.assertEqual(info['tracking'], -7)
        self.assertTrue(info['oneLine'])
        ttf = header.replace(b'type="HFT"', b'type="TTF"')
        self.assertAlmostEqual(ArticleLayoutStyles(ttf).estimate_width('가나다라', kind='title'), 48)

    def test_all_article_roles_use_complete_available_width_without_arbitrary_padding(self):
        styles = ArticleLayoutStyles(_header())
        for kind in ['local', 'title', 'domestic']:
            _, info = styles.build_runs('원문 내용(예시)', kind=kind, available_width=46604)
            self.assertEqual(466.04, info['availableWidthPt'])

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_short_text_keeps_zero_tracking_and_small_overflow_uses_only_minimum_needed(self, _metric):
        styles = ArticleLayoutStyles(_header())
        text = '가나다라'  # 4 x 13pt = 52pt, without font-metric variance.
        _, natural = styles.build_runs(text, available_width=5200)
        self.assertEqual(0, natural['tracking'])
        self.assertEqual('natural-one-line', natural['fitDecision'])
        self.assertTrue(natural['oneLine'])
        _, tight = styles.build_runs(text, available_width=5000)
        self.assertEqual(-6, tight['tracking'])
        self.assertEqual('minimum-tracking-one-line', tight['fitDecision'])
        self.assertEqual(1, tight['estimatedLines'])
        self.assertLessEqual(styles.estimate_width(text, tracking=-6), 50)
        self.assertGreater(styles.estimate_width(text, tracking=-5), 50)

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_unfittable_text_returns_to_natural_tracking_instead_of_cramped_two_lines(self, _metric):
        styles = ArticleLayoutStyles(_header())
        text = '가나다라'  # Minimum permitted spacing still cannot fit 40pt.
        self.assertGreater(styles.estimate_width(text, tracking=MAX_ARTICLE_TRACKING), 40)
        runs, info = styles.build_runs(text, available_width=4000, max_tracking=-80)
        self.assertEqual(0, info['tracking'])
        self.assertEqual('natural-wrap', info['fitDecision'])
        self.assertEqual(2, info['estimatedLines'])
        self.assertFalse(info['oneLine'])
        self.assertEqual(text, ''.join(character for character, _ in _characters(runs, styles.patched_header())))

    def test_at_least_one_and_half_natural_lines_is_not_tightened_even_if_metrics_allow_it(self):
        styles = ArticleLayoutStyles(_header())
        # Mock advances so the explicit long-text guard is tested independently
        # from the default font's glyph-width percentage implementation.
        with patch.object(styles, 'estimate_width', side_effect=lambda text, **options: 150 + options.get('tracking', 0) * 4):
            _, info = styles.build_runs('본문', available_width=10000)
        self.assertEqual(1.5, info['naturalLineRatio'])
        self.assertEqual(0, info['tracking'])
        self.assertEqual('natural-wrap', info['fitDecision'])
        self.assertEqual(2, info['estimatedLines'])

    def test_xml_escaped_and_section_namespace_alias_supported(self):
        styles = ArticleLayoutStyles(_header())
        runs, _ = styles.build_runs('원문 <검사> & 수급(예시)', paragraph_prefix='p')
        parsed = ET.fromstring(f'<root xmlns:p="{HP}">'.encode() + runs + b'</root>')
        self.assertEqual('원문 <검사> & 수급(예시)', ''.join(node.find('hp:t', NS).text or '' for node in parsed))

    def test_unsafe_or_unknown_header_fails_safely(self):
        for header in [b'<!DOCTYPE head [<!ENTITY x SYSTEM "file:///foo">]><head/>', b'<header/>', _header().replace(b'itemCnt="5"', b'itemCnt="4"')]:
            if b'itemCnt="4"' in header:
                styles = ArticleLayoutStyles(header)
                styles.build_runs('본문')
                with self.assertRaises(ArticleLayoutError):
                    styles.patched_header()
            else:
                with self.assertRaises(ArticleLayoutError):
                    ArticleLayoutStyles(header)

    def test_real_template_baseline_fonts_and_original_header_styles_preserved(self):
        with zipfile.ZipFile(ROOT / 'report_template' / 'weekly_overseas_market_report_table_template.hwpx') as package:
            original = package.read('Contents/header.xml')
        styles = ArticleLayoutStyles(original)
        self.assertEqual({'local': '39', 'domestic': '30', 'title': '51'}, styles.baseline_styles)
        runs, _ = styles.build_runs(' - (현지동향) 공급 감소로 가격 상승(전년비 5.9%) 압력 확대 전망')
        changed = styles.patched_header()
        before = ET.fromstring(original)
        after = ET.fromstring(changed)
        prior = {node.get('id'): ET.tostring(node) for node in before.findall('.//hh:charPr', NS)}
        for node in after.findall('.//hh:charPr', NS):
            if node.get('id') in prior:
                self.assertEqual(prior[node.get('id')], ET.tostring(node))
        self.assertEqual({1300, 1100}, {int(style.get('height')) for _, style in _characters(runs, changed)})

    @patch('src.article_hwpx_layout._metric_font', return_value=None)
    def test_real_domestic_pork_hft_advances_match_native_font_probe_and_need_only_minus_two(self, _metric):
        with zipfile.ZipFile(ROOT / 'report_template' / 'weekly_overseas_market_report_table_template.hwpx') as package:
            header = package.read('Contents/header.xml')
        styles = ArticleLayoutStyles(header)
        text = ' - 폭염 이후 가축 성장률 회복으로 유럽산 돼지고기 공급 증가, 육류 가격지수 하락'
        # Derived from the uploaded report's native HWP PDF Type3 metrics,
        # including HFT's .5em spaces rather than the TTF font's .33em spaces.
        self.assertAlmostEqual(471.168, styles.estimate_width(text, kind='domestic'), places=3)
        _, info = styles.build_runs(text, kind='domestic', available_width=46604)
        self.assertEqual(466.04, info['availableWidthPt'])
        self.assertEqual(-2, info['tracking'])
        self.assertEqual('minimum-tracking-one-line', info['fitDecision'])
        self.assertTrue(info['oneLine'])
        self.assertGreater(styles.estimate_width(text, kind='domestic', tracking=-1), 466.04)
        self.assertLessEqual(styles.estimate_width(text, kind='domestic', tracking=-2), 466.04)

    def test_hft_ascii_override_is_gated_by_referenced_language_face_and_font_type(self):
        class FixedMetricFont:
            def getlength(self, character):
                return 40  # .4em makes the override/fallback difference clear.

        def header_with_latin(face, font_type):
            header = _header().replace(b'<hh:font id="1" face="' + '한양중고딕'.encode() + b'"/>',
                                       b'<hh:font id="1" face="' + '한양중고딕'.encode() + b'" type="HFT"/>')
            latin = (f'<hh:fontface lang="LATIN"><hh:font id="0" face="휴먼명조" type="TTF"/>'
                     f'<hh:font id="1" face="{face}" type="{font_type}"/></hh:fontface>').encode()
            return header.replace(b'</hh:fontfaces>', latin + b'</hh:fontfaces>')

        with patch('src.article_hwpx_layout._metric_font', return_value=FixedMetricFont()):
            hft = ArticleLayoutStyles(header_with_latin('한양중고딕', 'HFT'))
            self.assertAlmostEqual(12, hft.estimate_width('1 ', kind='domestic'))
            # Same named face is not enough: Latin fontRef points to TTF even
            # though the Hangul fontRef still points to the known HFT face.
            ttf = ArticleLayoutStyles(header_with_latin('한양중고딕', 'TTF'))
            self.assertAlmostEqual(9.6, ttf.estimate_width('1 ', kind='domestic'))
            repaired = ArticleLayoutStyles(header_with_latin('다른HFT서체', 'HFT'))
            # A missing language face is explicitly planned from the same
            # named Hangul definition, not substituted by an unrelated face.
            self.assertAlmostEqual(12, repaired.estimate_width('1 ', kind='domestic'))
            # A known HFT face with an unknown character must still fall back
            # to the configured metric font rather than invent an advance.
            self.assertAlmostEqual(4.8, hft.estimate_width('☃', kind='domestic'))


if __name__ == '__main__':
    unittest.main()
