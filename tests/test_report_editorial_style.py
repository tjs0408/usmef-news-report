"""Source-backed editorial rules derived from the six user-supplied reports."""
from datetime import date
from unittest.mock import patch
import unittest

from bs4 import BeautifulSoup

from src import livestock_article_draft as d
from src import overseas_article_digest as s
from src.report_brief_style import STYLE_EXAMPLES, reference_examples, style_prompt


class EditorialStyleTests(unittest.TestCase):
    def test_every_section_retains_six_actual_examples_and_adds_reviewed_archive_references(self):
        self.assertEqual(set(STYLE_EXAMPLES), set(d.SPECS_BY_KEY))
        self.assertGreater(sum(map(len, STYLE_EXAMPLES.values())), 72)
        self.assertTrue(all(len(examples) >= 6 for examples in STYLE_EXAMPLES.values()))

    def test_topic_retrieval_does_not_insert_all_past_facts(self):
        examples = reference_examples('us_pork', 'Mexico pork exports fall as foodservice demand weakens')
        self.assertEqual(len(examples), 2)
        self.assertTrue(any('멕시코' in example for example in examples))
        self.assertIn('이번 기사 근거가 아니므로 복사하지', style_prompt('us_pork', 'pork export demand'))
        fact = '미국 계란 가격 5% 상승'
        with patch.object(s, '_ollama_generate', return_value={'response': fact}) as generate:
            self.assertEqual(s._extract_report_facts(kind='us_egg', audience='미국 계란', title='Egg prices',
                body='US egg prices rose 5%', headline_only=False, search_result=False), [fact])
        # Small CPU models copied unrelated past-week facts from examples.
        # Keep the reference library for editorial retrieval, not in the
        # bounded translation prompt; output syntax is schema-constrained.
        self.assertNotIn('문체 예시:', generate.call_args.args[0])
        self.assertIn('명사형 종결', generate.call_args.args[0])
        self.assertEqual(generate.call_args.kwargs['response_format']['required'], ['summary'])

    def test_global_trade_logistics_and_late_body_passages_are_eligible(self):
        cases = (
            ('domestic_pork', '北 돼지고기 가격 상승, 공급 확대', '북한에서 돼지고기 가격이 오르면서 공급 부담이 커졌다.'),
            ('domestic_chicken', '세계 식탁의 변화', '이란에서 닭고기 공급이 줄면서 소비자가격이 상승했다.'),
            ('domestic_egg', 'LX판토스 국제 운송 확대', '태국산 계란의 항공 운송을 확대해 수입 물량을 늘렸다.'),
            ('domestic_egg', '추가 계란 수입 추진', '계란 수입을 추가로 추진하되 수입 종료 기준은 아직 정하지 않았다.'),
        )
        for key, title, passage in cases:
            body = '관련 배경을 설명하는 보도 문장이다. ' * 60 + passage
            self.assertGreater(d._relevance({'title': title, 'body': body}, d.SPECS_BY_KEY[key]), 0)

    def test_foreign_keyword_does_not_make_local_promotion_relevant(self):
        for key, title, body in (
            ('domestic', '군 급식부터 야구장까지 육우 만나는 곳 확대', '육우를 홍보했다. 미국 소고기 공급은 감소했다.'),
            ('domestic_chicken', '노랑통닭, 日 투자은행 선임해 매각', '일본 투자은행을 선임했다. 육계 가격 하락으로 조달 비용이 감소했다.'),
            ('domestic_egg', '이마트 미국산 계란 할인', '미국 계란을 수입해 국내 마트에서 할인 판매했다.'),
        ):
            self.assertLess(d._relevance({'title': title, 'body': body}, d.SPECS_BY_KEY[key]), 0)

    def test_british_pig_report_is_not_eu_report(self):
        body = 'British pig producers face low prices. Defra is asked to fund support until pigs can be exported to a non-EU market.'
        self.assertLess(d._relevance({'title': 'NPA proposes pig support package', 'body': body}, d.SPECS_BY_KEY['eu_pork']), 0)

    def test_publication_utc_day_is_converted_for_korean_and_japanese_sources(self):
        for key in ('domestic_pork', 'japan_egg'):
            self.assertEqual(d._publication_date('2026-09-23T15:15:00Z', d.SPECS_BY_KEY[key]), date(2026, 9, 24))
            self.assertEqual(d._publication_date('2026-09-24T00:15:00+09:00', d.SPECS_BY_KEY[key]), date(2026, 9, 24))

    def test_korean_trade_and_foreign_price_compaction_is_source_only(self):
        body = '정부가 CPTPP 가입을 검토한다. 회원국으로부터 쇠고기, 돼지고기, 닭고기 등의 수입이 증가할 것으로 전망되며 국내 생산 감소로 이어질 수 있다.'
        summary = s._native_report_sentence('domestic_chicken', body)
        self.assertIn('닭고기 수입 증가 전망', summary)
        self.assertNotIn('돼지고기', summary)
        self.assertIn('가능성', summary)
        self.assertIsNone(s._grounded_market_statistic('domestic_chicken', body.replace('닭고기', '치즈')))
        body = '북한 군관에 돼지고기 1kg을 공급했다. 현지 가격으로 돼지고기는 북한 돈으로 16만~20만원 수준이다.'
        summary = s._native_report_sentence('domestic_pork', body)
        self.assertIn('북한 돈 16만~20만원', summary)
        self.assertIn('1kg', summary)
        self.assertIsNone(s._grounded_market_statistic('domestic_pork', body.replace('1kg', '알 수 없는 양')))

    def test_denmark_statistic_is_never_assigned_to_eu(self):
        body = ('More pigs were slaughtered in the European Union in the first half of 2026. '
                'Denmark recorded the strongest increase. From January to June, 8.3% more pigs were slaughtered there than in the first half of 2025.')
        self.assertIsNone(s._grounded_market_statistic('eu_pork', body))

    def test_import_review_is_not_an_invented_price_rise(self):
        body = ('미국 도널드 트럼프 행정부가 물가 부담을 완화하기 위해 실시해 온 소고기 수입 확대 조치를 '
                '일부 축소하는 방안을 검토 중이다. 농업주 의원들은 선거에 우려를 표했다. '
                '소고기 가격을 낮추려는 정책에 농가가 반발했다.')
        self.assertEqual(s._native_report_sentence('domestic', body), '미국 정부가 물가 부담 완화를 위해 시행한 소고기 수입 확대 조치의 일부 축소를 검토')
        self.assertFalse(s._brief_content_supported('미국 소고기 수입 축소 검토로 소고기 가격 상승 우려', 'domestic', body))
        denied = body.replace('검토 중이다', '검토하지 않는다고 부인했다')
        self.assertIsNone(s._grounded_market_statistic('domestic', denied))

    def test_mixed_species_and_untranslated_places_are_not_completed(self):
        body = 'Frango e suíno ampliam exportações, mas mercado interno impõe desafios diferentes ao Paraná.'
        self.assertFalse(s._brief_content_supported('Paraná의 닭고기 수출 증가로 내수 시장 부담', 'brazil_chicken', body))
        self.assertFalse(s._brief_content_supported('브라질 닭고기 수출이 늘었지만 돼지 공급 증가로 가격 하락', 'brazil_chicken', body))
        body = ('Frango e suíno ampliam exportações, mas mercado interno impõe desafios diferentes ao Paraná. '
                'No mercado brasileiro de frango, a demanda interna e as exportações ajudaram os preços a reagir. '
                'Na suinocultura, a oferta aumentou e pressionou as cotações.')
        excerpt = d._editorial_excerpt(body, 'Frango e suíno ampliam exportações ao Paraná', d.SPECS_BY_KEY['brazil_chicken'])
        self.assertIn('mercado brasileiro de frango', excerpt)
        self.assertNotIn('Na suinocultura', excerpt)

    def test_portuguese_national_export_stat_is_not_a_state_or_pork_stat(self):
        body = ('O Paraná exportou 200,6 mil toneladas de carne de frango em agosto. '
                'O Brasil exportou 492,6 mil toneladas de carne de frango em agosto, alta de 24,8% em um ano. '
                'O Brasil exportou 131,1 mil toneladas de carne suína em agosto, alta de 8% em um ano.')
        summary = s._native_report_sentence('brazil_chicken', body)
        self.assertIn('브라질의 8월 닭고기 수출량', summary)
        self.assertIn('24.8% 증가한 49만 2600톤', summary)
        self.assertNotIn('131', summary)
        self.assertIsNone(s._grounded_market_statistic('brazil_chicken', body.replace('O Brasil exportou 492,6', 'O Paraná exportou 492,6')))
        decreased = s._native_report_sentence('brazil_chicken', body.replace('alta de 24,8%', 'queda de 24,8%'))
        self.assertIn('24.8% 감소', decreased)

    def test_evidence_matches_native_statistic_not_editorial_background(self):
        body = ('The USDA says 247.786 million broiler-type eggs went into incubation, an increase of 2.564 million on the week. '
                '194.595 million broiler-type chicks were placed into meat production, falling 327000 from the previous week.')
        summary = s._native_report_sentence('us_chicken', body)
        evidence = s._native_source_excerpt(body, summary)
        self.assertIn('247.786', evidence)
        self.assertNotIn('194.595', evidence)

    def test_article_headline_focus_beats_background_numeric_list(self):
        body = ('홍콩은 계란 수입에 크게 의존한다. 일본의 계란 수출량은 2025년 21396톤을 기록했다. '
                '홍콩 정부와의 검역협상 타결로 한국산 계란 수출이 재개됐다.')
        excerpt = d._editorial_excerpt(body, '한국산 계란, 홍콩 수출 재개', d.SPECS_BY_KEY['domestic_egg'])
        self.assertIn('한국산 계란 수출이 재개', excerpt)
        self.assertNotIn('21396', excerpt)

    def test_report_subject_is_not_an_unresolved_pronoun(self):
        body = '이처럼 중단됐던 계란 수출길이 다시 열렸다.'
        self.assertIsNone(s._extract_usmef_source_summary(body, kind='domestic_egg'))

    def test_original_body_precedes_publisher_ai_summary(self):
        html = ('<html lang="ko"><meta property="article:published_time" content="2026-09-24">'
                '<h1>미국 소고기 수입 정책 검토</h1><header class="title-article01"><div class="article_txt">'
                + '인공지능이 요약한 소고기 수입 철회 확정. ' * 8 + '</div></header>'
                '<div class="story-news article">' + '백악관은 외국산 소고기 수입 확대 조치의 축소·철회를 검토 중이다. ' * 4 + '</div></html>')
        with patch.object(s, '_download_soup', return_value=BeautifulSoup(html, 'html.parser')):
            original = d._original_article({'url': 'https://example.org/news'}, d.SPECS_BY_KEY['domestic'])
        self.assertNotIn('확정', original['body'])
        self.assertIn('검토 중', original['body'])

    def test_explicit_public_syndicated_original_is_allowed_not_snippet(self):
        candidate = {'url': 'https://publisher.example/article', 'publicNewsUrl': 'https://n.news.naver.com/article/001/123', 'publisher': '원매체'}
        mirror = {'url': candidate['publicNewsUrl'], 'body': '공개 본문', 'publishedDate': date(2026, 9, 24)}
        with patch.object(d, '_read_original_article', side_effect=[None, mirror]):
            found = d._original_article(candidate, d.SPECS_BY_KEY['domestic_egg'])
        self.assertEqual(found['originalUrl'], candidate['url'])
        self.assertEqual(found['publisher'], '원매체')
        with patch.object(d, '_read_original_article', return_value=None) as read:
            self.assertIsNone(d._original_article({**candidate, 'publicNewsUrl': 'https://private.example/api'}, d.SPECS_BY_KEY['domestic_egg']))
        self.assertEqual(read.call_count, 1)

    def test_failed_originals_not_retried_across_query_tiers(self):
        candidate = {'url': 'https://example.org/egg', 'title': '미국 계란 가격 상승', 'body': '미국 계란 가격 상승', 'publishedDate': date(2026, 9, 24)}
        attempted, diagnostics = set(), {}
        with patch.object(d, '_original_article', return_value=None) as read:
            for _ in range(3):
                d._choose_original([candidate], d.SPECS_BY_KEY['domestic_egg'], date(2026, 9, 18), date(2026, 9, 24),
                                   attempted_urls=attempted, diagnostics=diagnostics)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(diagnostics['unreadable'], 1)
        self.assertIn('원문 확인 1건', d._search_failure_message(diagnostics))

    def test_next_candidate_tier_is_checked_when_first_ten_fail(self):
        candidates = [{'url': f'https://example.org/egg/{i}', 'title': '미국 계란 공급 감소', 'body': '미국 계란 공급 감소',
                       'publishedDate': date(2026, 9, 24)} for i in range(11)]
        original = {**candidates[10], 'body': '미국 계란 생산 감소로 공급 부족과 가격 상승이 이어졌다.'}
        with patch.object(d, '_original_article', side_effect=[None] * 10 + [original]) as read:
            found = d._choose_original(candidates, d.SPECS_BY_KEY['domestic_egg'], date(2026, 9, 18), date(2026, 9, 24))
        self.assertEqual(found['url'], original['url'])
        self.assertEqual(read.call_count, 11)


if __name__ == '__main__':
    unittest.main()
