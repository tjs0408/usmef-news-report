"""Model-free Australian recovery through public publisher discovery only."""
from contextlib import ExitStack
from dataclasses import replace
from datetime import date
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src import livestock_article_draft as d
from src import overseas_article_digest as s


START, END = date(2026, 9, 27), date(2026, 10, 3)
BASE = 'https://www.beefcentral.com/'
SPEC = replace(d.SPECS_BY_KEY['australia'], publisher='Beef Central', listings=(BASE,))
BRIEF = '호주 소고기 수출은 주요 시장의 수입 수요 변화와 공급 확대에 따라 경쟁 심화'


def original(name, *, ready=False, **changes):
    return {'title': 'Australia cattle prices and supply ' + str(name),
            'url': BASE + str(name) + '/', 'publisher': 'Beef Central',
            'publishedDate': date(2026, 10, 2), 'sourceLanguage': 'en',
            'body': ('Australia cattle prices and supply change in this market report. ' * 4)
                    + ('NATIVE READY' if ready else 'MODEL ONLY'), **changes}


def page(items=(), *, next_url=None):
    cards = ''.join('<article><h2><a href="' + item['url'] + '">' + item['title']
                    + '</a></h2><time datetime="' + item['publishedDate'].isoformat()
                    + '"></time></article>' for item in items)
    next_link = '<a rel="next" href="' + next_url + '">Next</a>' if next_url else ''
    return BeautifulSoup(cards + next_link, 'html.parser')


class NativePublisherRecoveryTests(unittest.TestCase):
    def source_mocks(self, stack, originals):
        stack.enter_context(patch.object(d, '_relevance', return_value=1))
        stack.enter_context(patch.object(d, '_with_selection', side_effect=lambda item, *_args, **_kwargs: item))
        stack.enter_context(patch.object(s, '_native_report_sentence', side_effect=lambda _key, body:
                                    BRIEF if 'NATIVE READY' in body else None))
        stack.enter_context(patch.object(s, '_fit_report_summary', return_value=BRIEF))
        stack.enter_context(patch.object(s, '_valid_brief', return_value=True))
        stack.enter_context(patch.object(s, '_native_source_excerpt', return_value='actual source passage'))
        stack.enter_context(patch.object(d, 'public_month_search_urls', return_value=[]))
        history = stack.enter_context(patch.object(d, 'public_history_candidates', return_value=[]))
        read = stack.enter_context(patch.object(d, '_original_article', side_effect=lambda candidate, _spec:
                                               originals.get(candidate['url'])))
        infer = stack.enter_context(patch.object(s, '_ollama_generate', side_effect=AssertionError('no inference')))
        return read, history, infer

    def test_au_native_search_reads_public_publisher_before_opaque_news(self):
        ready = original('dynamic-ready', ready=True)
        diagnostics = {}
        with ExitStack() as stack:
            read, _history, infer = self.source_mocks(stack, {ready['url']: ready})
            listing = stack.enter_context(patch.object(s, '_download_soup', return_value=page([ready])))
            rss = stack.enter_context(patch.object(s, '_search_google_news_rss'))
            result = d._search_article(d.SPECS_BY_KEY['australia'], START, END,
                                       diagnostics=diagnostics, native_only=True)
        self.assertEqual(result['url'], ready['url'])
        self.assertEqual(result['sourceMethod'], 'search')
        self.assertEqual(result['_nativeReadySummary'], ('australia', ready['body'], BRIEF))
        self.assertEqual(result['publishedDate'], date(2026, 10, 2))
        self.assertEqual(diagnostics['originalsChecked'], 1)
        listing.assert_called_once_with(BASE)
        read.assert_called_once()
        rss.assert_not_called()
        infer.assert_not_called()

    def test_public_dated_archive_continues_after_readable_unready_listing(self):
        unready = [original('first-' + str(i)) for i in range(3)]
        ready = original('archive-current-week', ready=True)
        diagnostics = {}
        with ExitStack() as stack:
            read, history, infer = self.source_mocks(stack,
                {item['url']: item for item in unready + [ready]})
            history.return_value = [ready]
            stack.enter_context(patch.object(s, '_download_soup', return_value=page(unready)))
            result = d._preferred_site_article(SPEC, START, END, native_only=True, diagnostics=diagnostics)
        self.assertEqual(result['url'], ready['url'])
        self.assertEqual(diagnostics['originalsChecked'], 4)
        self.assertEqual(read.call_count, 4)
        self.assertEqual(history.call_args.kwargs['start'], START)
        self.assertEqual(history.call_args.kwargs['end'], END)
        infer.assert_not_called()

    def test_excluded_stale_future_and_external_listing_links_are_not_read(self):
        excluded = original('failed-original', ready=True)
        stale = original('stale', ready=True, publishedDate=date(2026, 9, 26))
        future = original('future', ready=True, publishedDate=date(2026, 10, 4))
        external = original('external', ready=True, url='https://untrusted.example/story/')
        ready = original('different-original', ready=True)
        all_items = [excluded, stale, future, external, ready]
        with ExitStack() as stack:
            read, _history, _infer = self.source_mocks(stack, {item['url']: item for item in all_items})
            stack.enter_context(patch.object(s, '_download_soup', return_value=page(all_items)))
            result = d._preferred_site_article(SPEC, START, END, native_only=True,
                                               exclude_urls=frozenset({excluded['url']}))
        self.assertEqual(result['url'], ready['url'])
        self.assertEqual([call.args[0]['url'] for call in read.call_args_list], [ready['url']])

    def test_original_publication_cannot_be_relabelled_from_listing(self):
        listing_item = original('changed-date', ready=True)
        actual = {**listing_item, 'publishedDate': date(2026, 9, 26)}
        diagnostics = {}
        with ExitStack() as stack:
            read, _history, _infer = self.source_mocks(stack, {actual['url']: actual})
            stack.enter_context(patch.object(s, '_download_soup', return_value=page([listing_item])))
            result = d._preferred_site_article(SPEC, START, END, native_only=True, diagnostics=diagnostics)
        self.assertIsNone(result)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(diagnostics['outsideWeek'], 1)

    def test_publisher_reads_share_prior_eighteen_original_allowance(self):
        unready = [original('bad-' + str(i)) for i in range(25)]
        diagnostics = {'originalsChecked': 17}
        with ExitStack() as stack:
            read, history, _infer = self.source_mocks(stack, {item['url']: item for item in unready})
            stack.enter_context(patch.object(s, '_download_soup', return_value=page(unready)))
            result = d._preferred_site_article(SPEC, START, END, native_only=True, diagnostics=diagnostics)
        self.assertIsNone(result)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(diagnostics['originalsChecked'], 18)
        history.assert_not_called()

    def test_publisher_and_general_search_together_never_read_more_than_eighteen(self):
        local = [original('local-' + str(i)) for i in range(3)]
        discovered = [original('discovered-' + str(i)) for i in range(25)]
        diagnostics = {}
        with ExitStack() as stack:
            read, _history, _infer = self.source_mocks(stack,
                {item['url']: item for item in local + discovered})
            stack.enter_context(patch.object(s, '_download_soup', return_value=page(local)))
            stack.enter_context(patch.object(s, '_search_google_news_rss', return_value=discovered))
            bing = stack.enter_context(patch.object(d, '_public_bing_candidates'))
            result = d._search_article(d.SPECS_BY_KEY['australia'], START, END,
                                       native_only=True, diagnostics=diagnostics)
        self.assertIsNone(result)
        self.assertEqual(read.call_count, 18)
        self.assertEqual(diagnostics['originalsChecked'], 18)
        bing.assert_not_called()

    def test_existing_six_page_bound_is_preserved(self):
        count = 0
        def next_page(_url):
            nonlocal count
            count += 1
            return page(next_url=BASE + 'page/' + str(count + 1) + '/')
        with ExitStack() as stack:
            read, _history, _infer = self.source_mocks(stack, {})
            listing = stack.enter_context(patch.object(s, '_download_soup', side_effect=next_page))
            official = stack.enter_context(patch.object(d, '_official_market_article'))
            result = d._preferred_site_article(SPEC, START, END, native_only=True)
        self.assertIsNone(result)
        self.assertEqual(listing.call_count, len(SPEC.listings) + 5)
        read.assert_not_called()
        official.assert_not_called()

    def test_unavailable_publisher_can_fall_back_to_general_search(self):
        with patch.object(s, '_download_soup', side_effect=s.ArticleDigestError('offline')), \
             patch.object(s, '_search_google_news_rss', return_value=[]) as rss, \
             patch.object(d, '_public_bing_candidates', return_value=[]), \
             patch.object(d, '_public_google_candidates', return_value=[]):
            result = d._search_article(d.SPECS_BY_KEY['australia'], START, END, native_only=True)
        self.assertIsNone(result)
        self.assertGreater(rss.call_count, 0)

    def test_ordinary_publisher_call_keeps_legacy_chooser_arguments(self):
        item = original('ordinary')
        with patch.object(s, '_download_soup', return_value=page([item])), \
             patch.object(d, '_choose_original', return_value=item) as choose:
            result = d._preferred_site_article(SPEC, START, END)
        self.assertIs(result, item)
        self.assertEqual(result['url'], item['url'])
        self.assertNotIn('native_only', choose.call_args.kwargs)
        self.assertNotIn('exclude_urls', choose.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
