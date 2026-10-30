"""Offline issue diversity: real commodity facts, not forced topic rotation."""
import unittest

from src.market_issue_selection import (
    FOREIGN_MARKET_KINDS, issue_queries, market_issue_profile, market_issue_rank,
)


class MarketIssueSelectionTests(unittest.TestCase):
    def test_all_eight_foreign_sections_have_three_unrestricted_issue_queries(self):
        self.assertEqual(FOREIGN_MARKET_KINDS, {
            'us', 'australia', 'us_pork', 'eu_pork', 'us_chicken',
            'brazil_chicken', 'us_egg', 'japan_egg',
        })
        for kind in FOREIGN_MARKET_KINDS:
            with self.subTest(kind=kind):
                queries = issue_queries(kind)
                self.assertEqual(len(queries), 3)
                self.assertEqual(len(set(queries)), 3)
                self.assertTrue(all(3 <= len(query.split()) <= 6 for query in queries))
                self.assertFalse(any('site:' in query for query in queries))
                self.assertFalse(any('2026' in query for query in queries))
        for kind in ('unknown', 'domestic', 'domestic_pork'):
            self.assertEqual(issue_queries(kind), ())
        self.assertIn('Deutschland', issue_queries('eu_pork')[0])
        self.assertIn('Brasil', issue_queries('brazil_chicken')[0])
        self.assertIn('日本', issue_queries('japan_egg')[0])

    def test_source_cause_and_effect_outrank_many_weekly_production_figures(self):
        plain = 'US cattle production rose 3%, slaughter increased 2%, and inventory reached 30 million head.'
        issue = 'US cattle supply fell due to drought, pushing wholesale beef prices higher.'
        self.assertEqual(market_issue_profile('us', 'Weekly figures', plain)['level'], 1)
        profile = market_issue_profile('us', 'Cattle market', issue)
        self.assertEqual(profile['level'], 3)
        self.assertEqual(profile['pattern'], 'linked_market_change')
        self.assertGreater(market_issue_rank('us', '', issue), market_issue_rank('us', '', plain))
        self.assertIn(profile['evidence'], issue)

    def test_tariff_policy_and_consumer_change_beat_daily_quote(self):
        daily = 'US egg wholesale prices are $3.20 per dozen and supplies are moderate.'
        policy = 'The United States suspended tariffs on imported eggs to ease supply shortages.'
        demand = 'US egg consumption declined as households reduced purchases.'
        self.assertEqual(market_issue_profile('us_egg', '', daily)['level'], 1)
        self.assertEqual(market_issue_profile('us_egg', '', policy)['level'], 3)
        self.assertGreater(market_issue_rank('us_egg', '', demand), market_issue_rank('us_egg', '', daily))

    def test_retail_consumer_prices_are_an_issue_without_inventing_a_cause(self):
        source = 'US pork consumer prices rose 4% from a year earlier.'
        profile = market_issue_profile('us_pork', 'Consumer prices', source)
        self.assertEqual(profile['level'], 2)
        self.assertEqual(profile['pattern'], 'consumer_price_change')
        self.assertEqual(profile['evidence'], source)
        self.assertNotIn('because', profile['evidence'])

    def test_labor_supply_disruption_is_an_issue_without_a_statistical_release(self):
        source = 'US chicken processing slowed because labor shortages disrupted supplies to retailers.'
        profile = market_issue_profile('us_chicken', 'Processing workforce', source)
        self.assertEqual(profile['level'], 3)
        self.assertIn('cost_risk_policy', profile['themes'])
        self.assertIn('supply', profile['themes'])

    def test_generic_operational_allowance_is_not_a_trade_policy(self):
        source = 'US chicken production rose 3% as automation allowed processing of 100 million birds.'
        profile = market_issue_profile('us_chicken', 'Production', source)
        self.assertEqual(profile['level'], 1)
        self.assertNotEqual(profile['pattern'], 'policy_market_change')

    def test_explicitly_retracted_market_claim_is_not_a_richer_issue(self):
        source = ('US pork supply fell due to disease and retail prices rose. '
                  'That claim was retracted as incorrect.')
        self.assertEqual(market_issue_rank('us_pork', 'Market correction', source), (0, 0, 0))

    def test_local_language_market_changes_are_supported(self):
        sources = (
            ('brazil_chicken', 'Os preços do frango aumentaram devido à demanda e custos de ração.'),
            ('japan_egg', '日本の鶏卵価格は猛暑の影響で供給不足となり上昇。'),
            ('eu_pork', 'Die Schweinefleischpreise steigen aufgrund knapper Produktion und hoher Futterkosten.'),
        )
        for kind, body in sources:
            with self.subTest(kind=kind):
                profile = market_issue_profile(kind, '', body)
                self.assertEqual(profile['level'], 3)

    def test_target_species_does_not_borrow_another_species_or_fuel_cause(self):
        for source in (
            'US chicken prices rose due to labor shortages. US pork production is 120 million pounds.',
            'US gasoline prices rose due to supply shortages. US pork production is 120 million pounds.',
            'US chicken prices rose due to supply shortages and pork production is 120 million pounds.',
        ):
            with self.subTest(source=source):
                profile = market_issue_profile('us_pork', 'Pork market', source)
                self.assertEqual(profile['level'], 1)
                self.assertNotIn('shortages', profile['evidence'])
                self.assertNotIn('chicken', profile['evidence'])
                self.assertNotIn('gasoline', profile['evidence'])

    def test_separate_statistical_paragraphs_cannot_be_pooled_into_a_cause(self):
        source = 'US egg production rose 4%.\nUS egg prices are $3.20 per dozen.\nUS egg imports were 30 million.'
        profile = market_issue_profile('us_egg', 'Egg statistics', source)
        self.assertLessEqual(profile['level'], 2)
        self.assertNotEqual(profile['pattern'], 'linked_market_change')
        self.assertNotEqual(profile['evidence'], source)

    def test_metadata_headlines_events_promotions_medical_and_history_do_not_gain(self):
        title = 'US beef prices rose because cattle supply fell'
        cases = (
            ('us', title, title + '\nPublished October 1, 2026\nShare Facebook\nhttps://example.org/market'),
            ('us', 'Conference', 'The cattle conference discussed beef supply, prices, imports and demand.'),
            ('us', 'Promotion', 'Sponsored: beef prices are lower, buy now to support demand.'),
            ('us_egg', 'Medical', 'US egg cell-culture vaccines increased because clinical demand rose.'),
            ('us_pork', 'History', 'The pork company was founded in 2011 and production increased to 100 million.'),
        )
        for kind, title, body in cases:
            with self.subTest(kind=kind, body=body):
                self.assertEqual(market_issue_rank(kind, title, body), (0, 0, 0))

    def test_unknown_domestic_and_embedded_word_matches_are_zero(self):
        for kind, body in (
            ('unknown', 'US cattle supply fell due to drought.'),
            ('domestic', 'US cattle supply fell due to drought.'),
            ('us_pork', 'US pigment prices rose due to supply restrictions.'),
            ('us_egg', 'US nugget production increased due to demand.'),
        ):
            self.assertEqual(market_issue_rank(kind, 'market', body), (0, 0, 0))

    def test_rank_is_deterministic_not_number_count_or_repetition(self):
        source = 'US pork demand rose because retail prices fell.'
        rank = market_issue_rank('us_pork', 'Market', source)
        self.assertEqual(rank, market_issue_rank('us_pork', 'Market', source * 150))
        self.assertTrue(all(type(value) is int for value in rank))
        self.assertEqual(len(rank), 3)
        self.assertEqual(rank, market_issue_rank('us_pork', 'Market', source))
        self.assertEqual(market_issue_rank('us_pork', '', None), (0, 0, 0))

    def test_ranking_does_not_establish_country_or_date_eligibility(self):
        # This source must still be rejected by the caller for a US section.
        body = 'Chinese pork supply fell due to disease and retail prices rose.'
        self.assertEqual(market_issue_profile('us_pork', '', body)['level'], 3)
        self.assertNotIn('country', market_issue_profile('us_pork', '', body))


if __name__ == '__main__':
    unittest.main()
