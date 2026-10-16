"""Source-pattern recovery and grounding regressions; no HTTP/AI needed."""
import unittest
from unittest.mock import patch

from src import overseas_article_digest as s


BRAZIL_PENDING = (
    "As exportações de frango e mel do Brasil para a União Europeia ainda dependem de etapas administrativas, "
    "apesar da avaliação sanitária favorável. O governo brasileiro busca acelerar a liberação dos embarques "
    "ao mercado europeu. As compras poderão ser retomadas no curto prazo, após a conclusão dos procedimentos burocráticos."
)
JAPAN_PRICE = (
    "鶏卵の流通状況および相場情報について 東京市場・Ｍサイズ基準値 "
    "２０２６年９月の平均相場は、２９８ 円/㎏となりました。 "
    "２０２６年１０月６日の相場は、３１５ 円/㎏となっています。 "
    "過去最高値：３５０ 円/㎏（２０２３年４月）"
)
AU_EXPORTS = (
    "AUSTRALIA’s beef exports continue to be buffeted by tariffs. "
    "For the nine months ending 30 September, Australia’s export trade has hit a record 1.209 million tonnes, "
    "a hefty 82,000t or 7pc higher than last year’s already high figure of 1.127mt. "
    "Exports to US ports reach a record 378,658t – up 50,000t or 15pc on last year’s equivalent period."
)
EGG_IMPORTS = (
    "5일 농림축산식품부가 의원실에 제출한 자료에 따르면 정부는 올 들어 9월까지 "
    "미국(1억2578만개)·태국(562만개)·브라질(112만개)·덴마크(72만개)에서 계란을 수입했다."
)
PORK_SUPPLY = (
    "육류 가격지수는 전월보다 1.1% 하락한 127.9포인트를 기록했다. "
    "EU의 수입 규제 강화에 따른 가금육 수요 약화와 폭염 이후 가축 성장률을 회복한 "
    "유럽산 돼지고기 공급 증가가 하락을 주도했다."
)
CPTPP_IMPORTS = (
    "정부는 CPTPP 가입 논의를 시작했다. 호주산 쇠고기, 멕시코산 쇠고기·돼지고기, "
    "캐나다산 돼지고기·닭고기, 뉴질랜드산 전지분유 등의 수입 증가가 국내 생산 감소로 이어질 수 있다는 전망이다."
)
US_EGGS = (
    "National FOB shell egg weighted average prices lower for the larger sizes. "
    "The undertone is mixed, mostly steady. Supplies are mostly moderate."
)
US_CHICKEN = (
    "National chicken report. Demand is moderate to good. "
    "Floor stocks are well balanced and adequate. The market is steady."
)
GERMAN_PORK = (
    "Der Schlachtschweinemarkt bleibt angespannt. Das reguläre Angebot ist weiterhin gut ausreichend "
    "um den Bedarf am Fleischmarkt zu decken. Für die laufende Woche wird von unveränderten Preisen "
    "ausgegangen, der Druck am Markt bleibt aber spürbar."
)


class NativeRecoveryTests(unittest.TestCase):
    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_source_patterns_recover_without_model_and_obey_limits(self):
        cases = (('brazil_chicken', BRAZIL_PENDING), ('japan_egg', JAPAN_PRICE),
                 ('australia', AU_EXPORTS), ('domestic_egg', EGG_IMPORTS),
                 ('domestic_pork', PORK_SUPPLY), ('domestic', CPTPP_IMPORTS),
                 ('domestic_chicken', CPTPP_IMPORTS), ('domestic_pork', CPTPP_IMPORTS),
                 ('us_egg', US_EGGS), ('us_chicken', US_CHICKEN), ('eu_pork', GERMAN_PORK))
        for kind, body in cases:
            with self.subTest(kind=kind), patch.object(s, '_ollama_generate') as model:
                summary = s._summarize_report_sentence(kind, 'Original source', body)
                self.assertTrue(s._valid_brief(summary, kind, body), summary)
                self.assertTrue(40 <= len(summary) <= s.SUMMARY_LIMITS[kind])
                model.assert_not_called()

    def test_japanese_current_price_uses_date_basis_and_fullwidth_digits(self):
        result = s._native_report_sentence('japan_egg', JAPAN_PRICE)
        self.assertIn('M 규격', result)
        self.assertIn('10월 6일', result)
        self.assertIn('315엔', result)
        self.assertNotIn('298', result)
        self.assertNotIn('350', result)
        changed = JAPAN_PRICE.replace('３１５', '２７７').replace('１０月６日', '１１月８日')
        result = s._native_report_sentence('japan_egg', changed)
        self.assertIn('11월 8일', result)
        self.assertIn('277엔', result)
        self.assertTrue(s._valid_brief(result, 'japan_egg', changed))
        for body in (JAPAN_PRICE.replace('１０月６日', '１０月３２日'),
                     JAPAN_PRICE.replace('M', 'L').replace('Ｍ', 'Ｌ'),
                     JAPAN_PRICE.replace('日の相場は', '日の価格予想は')):
            self.assertIsNone(s._japan_egg_market_summary(body))

    def test_australian_national_trade_does_not_use_us_destination_number(self):
        result = s._native_report_sentence('australia', AU_EXPORTS)
        self.assertIn('9개월', result)
        self.assertIn('120만 9000톤', result)
        self.assertIn('7% 증가', result)
        self.assertNotIn('378', result)
        changed = AU_EXPORTS.replace('nine months', 'six months').replace('1.209', '1.456').replace('7pc', '8pc')
        result = s._native_report_sentence('australia', changed)
        self.assertIn('6개월', result)
        self.assertIn('145만 6000톤', result)
        self.assertIn('8% 증가', result)
        self.assertTrue(s._valid_brief(result, 'australia', changed))
        self.assertFalse(s._valid_brief(result.replace('증가', '감소'), 'australia', changed))
        self.assertFalse(s._valid_brief(result.replace('톤', '두'), 'australia', changed))
        self.assertIsNone(s._australian_beef_export_summary(AU_EXPORTS.replace("Australia’s export trade", "Brazil’s export trade")))

    def test_months_are_not_item_counts_and_pc_is_percentage(self):
        self.assertNotIn((9.0, 'items'), s._numeric_unit_facts('9개월 동안 계란 315개를 생산'))
        self.assertIn((315.0, 'items'), s._numeric_unit_facts('9개월 동안 계란 315개를 생산'))
        self.assertEqual(s._numeric_unit_facts('7pc higher and 82,000t'), {(7.0, 'percent'), (82000.0, 'tonne')})
        self.assertEqual(s._percent_directions('7pc higher'), {(7.0, 'up')})

    def test_brazil_still_pending_and_not_first_time_or_other_species(self):
        result = s._native_report_sentence('brazil_chicken', BRAZIL_PENDING)
        self.assertIn('행정 절차', result)
        self.assertIn('필요', result)
        self.assertNotIn('승인 완료', result)
        self.assertIsNone(s._native_report_sentence('brazil_chicken', BRAZIL_PENDING.replace('frango', 'carne bovina')))
        self.assertIsNone(s._brazil_chicken_trade_summary(BRAZIL_PENDING.split('. ', 1)[0] + '.'))
        negated = BRAZIL_PENDING.replace('ainda dependem', 'não dependem')
        self.assertIsNone(s._brazil_chicken_trade_summary(negated))

    def test_egg_import_amount_is_dynamic_without_invented_sum_or_chronology(self):
        result = s._native_report_sentence('domestic_egg', EGG_IMPORTS)
        self.assertIn('1억 2578만개', result)
        self.assertIn('태국·브라질·덴마크', result)
        self.assertNotIn('이어', result)
        changed = EGG_IMPORTS.replace('9월', '8월').replace('1억2578만개', '7654만개')
        result = s._native_report_sentence('domestic_egg', changed)
        self.assertIn('8월까지', result)
        self.assertIn('7654만개', result)
        self.assertTrue(s._valid_brief(result, 'domestic_egg', changed))
        self.assertIsNone(s._korean_egg_import_summary(EGG_IMPORTS.replace('수입했다', '수입할 예정이다')))

    def test_pork_supply_uses_its_own_cause_not_poultry_demand(self):
        result = s._native_report_sentence('domestic_pork', PORK_SUPPLY)
        self.assertIn('유럽산 돼지고기', result)
        self.assertIn('폭염 이후 가축 성장률', result)
        self.assertNotIn('가금육', result)
        self.assertNotIn('수입 규제', result)
        self.assertIsNone(s._grounded_market_statistic('domestic_pork', PORK_SUPPLY.replace('공급 증가가', '공급 감소가')))

    def test_cptpp_condition_and_species_survive_without_invented_origins(self):
        for kind, product in (('domestic', '쇠고기'), ('domestic_pork', '돼지고기'), ('domestic_chicken', '닭고기')):
            result = s._native_report_sentence(kind, CPTPP_IMPORTS)
            self.assertIn('CPTPP 가입 시', result)
            self.assertIn(product, result)
            self.assertIn('가능성', result)
            self.assertNotIn('지속', result)
            self.assertFalse(s._valid_brief(result.replace('CPTPP 가입 시', '향후 시장에서'), kind, CPTPP_IMPORTS))

    def test_country_and_species_are_bound_together_in_korean_sources(self):
        body = CPTPP_IMPORTS.split('. ', 1)[1]
        correct = '캐나다산 닭고기 수입 증가로 국내 생산 감소 가능성'
        wrong = correct.replace('캐나다', '호주')
        self.assertTrue(s._brief_content_supported(correct, 'domestic_chicken', body))
        self.assertFalse(s._brief_content_supported(wrong, 'domestic_chicken', body))
        accepted_bad_draft = '호주산 쇠고기와 멕시코산 돼지고기의 증가로 국내 소고기 생산 감소가 지속될 것으로 전망'
        self.assertFalse(s._valid_brief(accepted_bad_draft, 'domestic', body))
        self.assertIn(('캐나다', 'chicken'), s._korean_origin_species_pairs(body))
        self.assertNotIn(('호주', 'chicken'), s._korean_origin_species_pairs(body))

    def test_changed_official_narrative_requires_fresh_translation(self):
        for kind, body in (
            ('us_egg', US_EGGS.replace('prices lower', 'prices higher')),
            ('us_chicken', US_CHICKEN.replace('well balanced and adequate', 'inadequate')),
            ('eu_pork', GERMAN_PORK.replace('unveränderten Preisen', 'steigenden Preisen')),
        ):
            self.assertIsNone(s._native_report_sentence(kind, body))

    def test_usda_national_price_movement_is_read_dynamically(self):
        for original, translated in (('steady to lower', '보합~하락'), ('steady to higher', '보합~상승'),
                                     ('steady', '보합'), ('lower', '하락'), ('higher', '상승')):
            body = f'National FOB shell egg weighted average prices are {original}. Supplies are mostly moderate.'
            summary = s._native_report_sentence('us_egg', body)
            self.assertIn(translated, summary)
            self.assertTrue(s._valid_brief(summary, 'us_egg', body))
        for body in ('National FOB shell egg weighted average prices are not steady to lower. Supplies are mostly moderate.',
                     'National FOB shell egg weighted average prices are steady to lower. Supplies are light.'):
            self.assertIsNone(s._native_report_sentence('us_egg', body))

    def test_broiler_placements_preserve_animal_unit_and_weekly_direction(self):
        body = ('189.689 million broiler-type chicks were placed into meat production, 3.632 million less '
                'than the previous week, but 2% more than a year ago. Those birds will start heading to market in early November.')
        result = s._native_report_sentence('us_chicken', body)
        self.assertIn('입식수', result)
        self.assertIn('363만 2000마리 줄어', result)
        self.assertIn('1억 8968만 9000마리', result)
        self.assertTrue(s._valid_brief(result, 'us_chicken', body))
        changed = body.replace('189.689', '190.222').replace('3.632', '4.001').replace('million less', 'million more')
        result = s._native_report_sentence('us_chicken', changed)
        self.assertIn('400만 1000마리 늘어', result)
        self.assertIn('1억 9022만 2000마리', result)
        self.assertTrue(s._valid_brief(result, 'us_chicken', changed))
        self.assertFalse(s._valid_brief(result.replace('마리', '개'), 'us_chicken', changed))
        self.assertIsNone(s._extract_broiler_stat_summary(body.replace('chicks', 'eggs')))
        self.assertIsNone(s._extract_broiler_stat_summary(body.replace('previous week', 'previous year')))

    def test_correct_model_prose_is_nominalized_before_fact_validation(self):
        body = 'US egg prices rose 5% on the year due to a decline in supply.'
        prose = '미국 계란 가격은 공급 감소의 영향으로 전년과 비교해 5% 상승한 수준을 기록했다.'
        with patch.object(s, '_ollama_generate', return_value={'response': prose}) as model:
            result = s._summarize_report_sentence('us_egg', 'US egg price increase', body)
        self.assertTrue(result.endswith('기록'))
        self.assertTrue(s._valid_brief(result, 'us_egg', body))
        self.assertEqual(model.call_count, 1)

    def test_declared_encodings_preserve_original_korean(self):
        text = '<meta charset="euc-kr"><article>유럽산 돼지고기 공급 증가</article>'
        self.assertEqual(s._decode_source_html(text.encode('euc-kr'), None), text)
        self.assertEqual(s._decode_source_html(text.encode('euc-kr'), 'utf-8'), text)
        utf8 = '<meta charset="utf-8"><article>미국 계란 가격 하락</article>'
        self.assertEqual(s._decode_source_html(utf8.encode(), 'iso-8859-1'), utf8)


if __name__ == '__main__':
    unittest.main()
