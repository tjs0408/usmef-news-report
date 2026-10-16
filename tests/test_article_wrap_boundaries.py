"""Regressions for native Hancom end-of-line and Korean word boundaries."""

from pathlib import Path
import re
import unittest
from xml.etree import ElementTree as ET
import zipfile

from src.article_hwpx_layout import (
    ArticleLayoutStyles, MAX_ARTICLE_TRACKING, _metric_font,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'report_template/weekly_overseas_market_report_table_template.hwpx'
HH = 'http://www.hancom.co.kr/hwpml/2011/head'
HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
NS = {'hh': HH, 'hp': HP}
LOCAL_WIDTH = 46321
PREFIX = ' - (현지동향) '

EU_PORK = PREFIX + '독일 돼지 공급 계절적 확대, 육류 수요 부진 속 이번 주 가격 보합 전망'
US_EGG = PREFIX + '미국 계란의 전국 FOB 가중평균 가격은 보합~하락, 공급은 대체로 보통 수준'
US_CHICKEN = PREFIX + (
    '미국 육계 종란 입란수는 산란계 수 증가로 전년비 3% 늘었으나 '
    '전주비 21만 5000개 감소, 2억 4530만 4000개 기록'
)


def _header():
    with zipfile.ZipFile(TEMPLATE) as package:
        return package.read('Contents/header.xml')


class ArticleWrapBoundaryTests(unittest.TestCase):
    def test_only_the_local_middle_dot_gets_gulim_not_neighboring_text(self):
        styles = ArticleLayoutStyles(_header())
        text = PREFIX + '미국 거세우·미경산우 도축 둔화로 소고기 생산 전망 하향'
        runs, _ = styles.build_runs(text, kind='local', available_width=100000)
        header = ET.fromstring(styles.patched_header())
        fonts = {
            group.get('lang').lower(): {font.get('id'): font.get('face') for font in group}
            for group in header.findall('.//hh:fontface', NS)
        }
        properties = {node.get('id'): node for node in header.findall('.//hh:charPr', NS)}
        wrapper = ET.fromstring(f'<root xmlns:hp="{HP}">'.encode() + runs + b'</root>')
        observed = []
        for run in wrapper:
            value = ''.join(run.itertext())
            style = properties[run.get('charPrIDRef')]
            references = style.find('hh:fontRef', NS).attrib
            faces = {fonts[language][identity] for language, identity in references.items()}
            self.assertEqual({'굴림'} if value == '·' else {'휴먼명조'}, faces, value)
            self.assertEqual('1300', style.get('height'))
            observed.append(value)
        self.assertEqual(text, ''.join(observed))
        self.assertEqual(1, observed.count('·'))

    @unittest.skipUnless(_metric_font('휴먼명조') is not None, 'Native report font is not installed')
    def test_terminal_glyph_does_not_take_negative_tracking_at_right_edge(self):
        styles = ArticleLayoutStyles(_header())
        for text, expected in ((EU_PORK, -13), (US_EGG, -17)):
            with self.subTest(text=text):
                info = styles.measure_layout(text, available_width=LOCAL_WIDTH, max_lines=1)
                self.assertEqual(expected, info['tracking'])
                self.assertEqual(1, info['estimatedLines'])
                self.assertTrue(info['withinLineLimit'])
                self.assertLessEqual(info['estimatedWidthPt'], LOCAL_WIDTH / 100)
                self.assertGreater(styles.estimate_width(text, tracking=expected + 1),
                                   LOCAL_WIDTH / 100)

    @unittest.skipUnless(_metric_font('휴먼명조') is not None, 'Native report font is not installed')
    def test_two_line_chicken_completes_crossing_word_with_minimum_tracking(self):
        styles = ArticleLayoutStyles(_header())
        info = styles.measure_layout(US_CHICKEN, available_width=LOCAL_WIDTH, max_lines=2)
        self.assertEqual(-2, info['tracking'])
        self.assertEqual(2, info['estimatedLines'])
        self.assertTrue(info['withinLineLimit'])
        first, second = info['estimatedLineTexts']
        self.assertTrue(first.rstrip().endswith('늘었으나'), first)
        self.assertTrue(second.lstrip().startswith('전주비'), second)
        self.assertEqual(US_CHICKEN.replace(' ', ''), (first + second).replace(' ', ''))

    def test_one_line_slots_stay_within_floor_and_short_domestic_bodies_stay_zero(self):
        styles = ArticleLayoutStyles(_header())
        locals_ = [
            '호주 쇠고기 대중 수출량 전년비 70~80% 감소, 할당량 초과 시 관세 55% 부과',
            '돼지고기 생산량 전주비 3.3%·전년비 1.1% 증가, 5억 6240만 파운드 기록',
            '중국 2026년 상반기 닭고기 생산 9% 초과 증가, 브라질 경쟁국 부상 가능성',
            '일본 도쿄 계란 M 규격 기준가격 kg당 315엔, 입하량 760톤·시장 보합세 유지',
        ]
        domestic = [
            '브라질산 쇠고기의 한국 시장 접근 약속을 양국 정상의 공동성명에서 재확인',
            '중국 9월 CPI 전년 동월비 0.9% 상승, 돼지고기 가격은 10.0% 하락',
            '미국 USDA, 수입 재검사 미실시 즉석 닭고기 스튜 약 4596 파운드 리콜',
            '브라질 계란 개당 구입가 178원, 항공운임·관세 포함 총수입단가 1464원 수준',
        ]
        for text in locals_:
            with self.subTest(text=text):
                info = styles.measure_layout(PREFIX + text, available_width=LOCAL_WIDTH, max_lines=1)
                self.assertTrue(info['withinLineLimit'])
                self.assertEqual(1, info['estimatedLines'])
                self.assertGreaterEqual(info['tracking'], MAX_ARTICLE_TRACKING)
        for text in domestic:
            with self.subTest(text=text):
                info = styles.measure_layout(' - ' + text, kind='domestic', available_width=46604, max_lines=1)
                self.assertTrue(info['withinLineLimit'])
                self.assertEqual(0, info['tracking'])

    def test_word_safe_paragraph_is_appended_without_changing_original(self):
        original = _header()
        source = ET.fromstring(original)
        paragraph = next(node for node in source.findall('.//hh:paraPr', NS)
                         if node.find('hh:breakSetting', NS) is not None
                         and node.find('hh:breakSetting', NS).get('breakNonLatinWord') == 'KEEP_WORD')
        identity = paragraph.get('id')
        exact = re.search(rb'<hh:paraPr\b[^>]*\bid="' + identity.encode()
                          + rb'"[^>]*>.*?</hh:paraPr>', original, re.S)[0]
        styles = ArticleLayoutStyles(original)
        clone_id = styles.word_safe_paragraph_style(identity)
        self.assertNotEqual(identity, clone_id)
        changed = styles.patched_header()
        self.assertIn(exact, changed)
        root = ET.fromstring(changed)
        old = root.find(f'.//hh:paraPr[@id="{identity}"]', NS)
        clone = root.find(f'.//hh:paraPr[@id="{clone_id}"]', NS)
        self.assertEqual('KEEP_WORD', old.find('hh:breakSetting', NS).get('breakNonLatinWord'))
        self.assertEqual('BREAK_WORD', clone.find('hh:breakSetting', NS).get('breakNonLatinWord'))
        self.assertEqual(old.find('hh:breakSetting', NS).get('breakLatinWord'),
                         clone.find('hh:breakSetting', NS).get('breakLatinWord'))


if __name__ == '__main__':
    unittest.main()
