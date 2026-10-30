"""Issue discovery never substitutes snippets or metadata for real originals."""
from contextlib import ExitStack
from datetime import date, timedelta
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from src import livestock_article_draft as collector
from src import overseas_article_digest as source
from src.article_cancellation import ArticleDraftCancelled


START, END = date(2026, 10, 18), date(2026, 10, 24)
SPEC = collector.SPECS_BY_KEY['us_pork']
BODY = ('United States pork import restrictions were lifted to improve supply. '
        'Higher consumer demand supported retail pork sales, while distributors reported tight inventories.')


def candidate(name='one', **changes):
    return {'title': 'United States pork import demand and supply ' + name,
            'url': 'https://publisher.example/' + name,
            'publishedDate': START + timedelta(days=2), 'publisher': 'Public publisher',
            'body': 'United States pork imports face new policy changes.', **changes}


def original(name='one', **changes):
    return {**candidate(name), 'body': BODY, 'sourceLanguage': 'en',
            'headlineOnly': False, 'searchResult': False, **changes}


class MarketIssueOriginalTests(unittest.TestCase):
    def search(self, candidates, originals, *, spec=SPEC, excludes=frozenset()):
        diagnostics = {}
        with ExitStack() as stack:
            # Real bounded discovery runs with only its public provider calls
            # mocked; the real country/species/market relevance gates remain.
            rss = stack.enter_context(patch.object(source, '_search_google_news_rss', return_value=candidates))
            web = stack.enter_context(patch.object(collector, '_public_google_candidates', return_value=[]))
            bing = stack.enter_context(patch.object(collector, '_public_bing_candidates', return_value=[]))
            if callable(originals):
                read = stack.enter_context(patch.object(collector, '_original_article', side_effect=originals))
            else:
                read = stack.enter_context(patch.object(collector, '_original_article',
                    side_effect=lambda item, _spec: originals.get(item['url'])))
            infer = stack.enter_context(patch.object(source, '_ollama_generate', side_effect=AssertionError('no model')))
            result = collector._search_editorial_issues(spec, START, END,
                exclude_urls=excludes, diagnostics=diagnostics)
        infer.assert_not_called()
        self.assertLessEqual(read.call_count, 6)
        self.assertEqual(rss.call_count, 2)
        self.assertEqual(web.call_count, 1)
        self.assertEqual(bing.call_count, 2)
        return result, diagnostics, read

    def test_real_original_must_replace_the_search_description(self):
        found = candidate(body='A search snippet claiming pork supply is plentiful.')
        actual = original(body=BODY)
        result, diagnostics, read = self.search([found], {found['url']: actual})
        self.assertIsNotNone(result)
        self.assertEqual(result['body'], BODY)
        self.assertFalse(result['headlineOnly'])
        self.assertFalse(result['searchResult'])
        self.assertEqual(diagnostics['issueOriginalsEligible'], 1)
        self.assertTrue(read.call_args.args[0]['searchResult'])
        self.assertTrue(read.call_args.args[0]['headlineOnly'])

    def test_original_publication_date_is_not_replaced_by_the_listing_week(self):
        for published in (START - timedelta(days=1), END + timedelta(days=1), None):
            with self.subTest(published=published):
                found = candidate()
                result, diagnostics, _ = self.search([found],
                    {found['url']: original(publishedDate=published)})
                self.assertIsNone(result)
                self.assertEqual(diagnostics['issueOriginalsEligible'], 0)

    def test_bad_country_species_and_unverified_originals_cannot_qualify(self):
        invalid = (
            original(title='Brazil pork imports and supply', body=BODY.replace('United States', 'Brazil'),
                     sourceCountry='US', selectionTier=0),
            original(title='United States chicken imports and supply', body=BODY.replace('pork', 'chicken'),
                     sourceCountry='US', selectionTier=0),
            original(headlineOnly=True), original(searchResult=True), original(body='only a headline'),
        )
        for actual in invalid:
            with self.subTest(actual=actual):
                found = candidate()
                result, _, _ = self.search([found], {found['url']: actual})
                self.assertIsNone(result)

    def test_original_url_and_language_are_rechecked_at_issue_boundary(self):
        for changes in ({'url': 'https:///missing-host'},
                        {'originalUrl': 'javascript:alert(1)'},
                        {'sourceLanguage': 'de'}):
            with self.subTest(changes=changes):
                found = candidate()
                result, _, _ = self.search([found], {found['url']: original(**changes)})
                self.assertIsNone(result)

    def test_eu_issue_originals_allow_english_and_german_only(self):
        spec = collector.SPECS_BY_KEY['eu_pork']
        german = ('Deutschland: Das Angebot an Schweinen ist umfangreich, die Nachfrage nach Schweinefleisch '
                  'bleibt schwach. Höhere Futterkosten belasten Erzeuger, während der Absatz im Einzelhandel sinkt.')
        english = ('Germany pork imports were reduced as domestic supplies recovered across EU markets. '
                   'Consumer demand for fresh pork fell while retail distributors held adequate stocks.')
        for language, body in (('en', english), ('de', german), ('fr', german)):
            with self.subTest(language=language):
                found = candidate(title='Deutschland Schweinefleisch Nachfrage und Angebot')
                actual = original(title=found['title'], body=body, sourceLanguage=language)
                result, _, _ = self.search([found], {found['url']: actual}, spec=spec)
                if language == 'fr':
                    self.assertIsNone(result)
                else:
                    self.assertIsNotNone(result)
                    self.assertEqual(result['sourceLanguage'], language)

    def test_opaque_google_wrapper_is_not_downloaded_or_treated_as_an_original(self):
        found = candidate(url='https://news.google.com/rss/articles/opaque-wrapper')
        result, diagnostics, read = self.search([found], lambda *_: self.fail('wrapper must not be downloaded'))
        self.assertIsNone(result)
        self.assertEqual(read.call_count, 0)
        self.assertEqual(diagnostics['issueRedirectsUnresolved'], 1)

    def test_listing_outside_week_and_excluded_url_are_not_redownloaded(self):
        excluded = candidate('excluded')
        outside = candidate('outside', publishedDate=START - timedelta(days=1))
        result, _, read = self.search([excluded, outside], {}, excludes=frozenset([excluded['url']]))
        self.assertIsNone(result)
        read.assert_not_called()

    def test_missing_species_in_title_does_not_hide_explicit_target_body(self):
        found = candidate(title='New import restrictions alter regional market supply')
        actual = original(title=found['title'])
        result, _, _ = self.search([found], {found['url']: actual})
        self.assertIsNotNone(result)
        self.assertEqual(result['url'], actual['url'])
        self.assertIn('United States pork', result['body'])

    def test_six_original_cap_still_inspects_multiple_publishers(self):
        a = [candidate('a-' + str(index), url=f'https://a.example/{index}') for index in range(12)]
        b = [candidate('b-' + str(index), url=f'https://b.example/{index}') for index in range(4)]
        result, diagnostics, read = self.search(a + b, {})
        self.assertIsNone(result)
        self.assertEqual(read.call_count, 6)
        self.assertEqual(diagnostics['issueOriginalsChecked'], 6)
        self.assertEqual({urlparse(call.args[0]['url']).hostname for call in read.call_args_list},
                         {'a.example', 'b.example'})
        # A single publisher can still supply all six when it is the only one.
        _, _, single = self.search(a, {})
        self.assertEqual(single.call_count, 6)

    def test_searched_metadata_cannot_create_a_higher_original_rank(self):
        found = candidate(selectionTier=0, score=999999,
                          issueRank=(99, 99, 99), sourceCountry='US')
        wrong = original(title='Brazil pork exports rise', body=BODY.replace('United States', 'Brazil'))
        result, _, _ = self.search([found], {found['url']: wrong})
        self.assertIsNone(result)

    def test_another_species_cause_does_not_inflate_target_issue_rank(self):
        mixed = original(title='United States pork market update', body=(
            'United States pork prices remained steady and pork supplies were adequate. '
            'United States chicken import prices increased because higher grain costs reduced broiler production. '
            'Poultry exporters halted chicken shipments after the new trade restrictions.'))
        # Country/species eligibility still holds for the pork observation,
        # but chicken's causal trade/cost narrative must not become its issue.
        self.assertGreaterEqual(collector._relevance(mixed, SPEC, trusted_country=False), 0)
        self.assertLessEqual(collector._issue_order(mixed, SPEC)[1][0], 1)

    def test_original_cancellation_propagates_without_generating_a_fallback(self):
        def cancel(*_args):
            raise ArticleDraftCancelled('cancelled original fetch')
        with self.assertRaises(ArticleDraftCancelled):
            self.search([candidate()], cancel)


class MarketIssueBaselineTests(unittest.TestCase):
    def test_failed_optional_scan_preserves_verified_baseline(self):
        baseline = original('baseline')
        for effect in (None, RuntimeError('provider unavailable')):
            with self.subTest(effect=effect), patch.object(collector, '_search_article',
                    return_value=None, side_effect=effect) as search:
                result = collector._broaden_editorial_candidate(baseline, SPEC, START, END)
            self.assertEqual(result['url'], baseline['url'])
            self.assertEqual(result['body'], baseline['body'])
            self.assertEqual(result['publishedDate'], baseline['publishedDate'])
            self.assertTrue(result['_issueComparisonDone'])
            self.assertTrue(search.call_args.kwargs['editorial'])
            self.assertIn(baseline['url'], search.call_args.kwargs['exclude_urls'])
            self.assertNotIn('_issueComparisonDone', baseline)

    def test_completed_comparison_is_not_repeated_and_cancel_is_not_swallowed(self):
        baseline = original('baseline', _issueComparisonDone=True)
        with patch.object(collector, '_search_article') as search:
            self.assertIs(collector._broaden_editorial_candidate(baseline, SPEC, START, END), baseline)
        search.assert_not_called()
        with patch.object(collector, '_search_article', side_effect=ArticleDraftCancelled('stop')):
            with self.assertRaises(ArticleDraftCancelled):
                collector._broaden_editorial_candidate(original('base'), SPEC, START, END)

    def test_alternative_pool_keeps_baseline_and_caps_total_at_five(self):
        baseline = original('baseline')
        clauses = (
            'United States pork import tariffs were suspended to ease a shortage in domestic supply. '
            'Additional import licenses were approved for local wholesalers and major distributors.',
            'United States pork consumer demand rose as grocery chains changed their retail offers. '
            'Customers bought more fresh cuts while restaurants adjusted their purchasing contracts.',
            'United States pork processing supply fell after disease restrictions halted animal movements. '
            'Affected factories postponed slaughter and exporters reported interrupted cargo deliveries.',
            'United States pork feed costs increased because grain prices rose sharply during the summer. '
            'Higher production expenses reduced producer margins despite stable farmgate values.',
            'United States pork inventories declined as export shipments grew following new trade agreements. '
            'Refrigerated warehouses held lower stocks and overseas buyers placed additional orders.',
            'United States pork retail prices were lower as consumers switched to cheaper sources of protein. '
            'Foodservice companies increased orders and expanded their distribution of fresh products.',
        )
        issues = [original(str(index), body=body) for index, body in enumerate(clauses)]
        scanned = {**issues[0], 'alternatives': issues[1:]}
        with patch.object(collector, '_search_article', return_value=scanned):
            result = collector._broaden_editorial_candidate(baseline, SPEC, START, END)
        pool = [result] + result['alternatives']
        self.assertEqual(len(pool), 5)
        self.assertIn(baseline['url'], {item['url'] for item in pool})
        self.assertTrue(all(item['_issueComparisonDone'] for item in pool))


if __name__ == '__main__':
    unittest.main()
