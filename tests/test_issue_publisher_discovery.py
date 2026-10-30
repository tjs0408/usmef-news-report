"""Public publisher discovery when Google returns opaque/blocked pages.

Every HTTP, date-archive and original-reader callback is mocked. These are
discovery links only; original date/body verification happens in the caller.
"""
from contextlib import ExitStack
from datetime import date
from threading import Event
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src import livestock_article_draft as d
from src import overseas_article_digest as s
from src.article_cancellation import ArticleDraftCancelled, article_cancellation_scope


START, END = date(2026, 10, 18), date(2026, 10, 24)
SPEC = d.SPECS_BY_KEY['australia']


def wrapped(name, publisher_url, **changes):
    return {'url': 'https://news.google.com/rss/articles/opaque-' + name,
            'publisherUrl': publisher_url, 'publisher': name,
            'title': 'Australian beef demand and cattle prices ' + name,
            'body': '', **changes}


def link(host, name):
    return {'url': 'https://' + host + '/' + name, 'title': 'Australian beef demand ' + name,
            'publishedDate': date(2026, 10, 21), 'publisher': host,
            'discoveryMethod': 'publisher_archive'}


class IssuePublisherDiscoveryTests(unittest.TestCase):
    def mocks(self, stack):
        soup = BeautifulSoup('<main>Public publisher home</main>', 'html.parser')
        download = stack.enter_context(patch.object(s, '_download_soup', return_value=soup))
        listing = stack.enter_context(patch.object(d, '_listing_candidates', return_value=[]))
        history = stack.enter_context(patch.object(d, 'public_history_candidates', return_value=[]))
        original = stack.enter_context(patch.object(d, '_original_article', side_effect=AssertionError('not original verification')))
        model = stack.enter_context(patch.object(s, '_ollama_generate', side_effect=AssertionError('no inference')))
        stack.enter_context(patch.object(d, 'market_issue_rank', return_value=(0,)))
        return download, listing, history, original, model

    def test_at_most_two_new_publishers_excluding_baseline_and_www_alias(self):
        candidates = [wrapped('baseline', 'https://www.baseline.example/'),
                      wrapped('A', 'https://www.alpha.example/'),
                      wrapped('A alias', 'https://alpha.example/'),
                      wrapped('B', 'https://beta.example/'),
                      wrapped('C', 'https://gamma.example/')]
        diagnostics = {}
        with ExitStack() as stack:
            download, listing, history, original, model = self.mocks(stack)
            listing.side_effect = lambda _page, url, *_args: [link('alpha.example' if 'alpha' in url else 'beta.example', 'visible')]
            history.side_effect = lambda _page, url, **_kwargs: [link('alpha.example' if 'alpha' in url else 'beta.example', 'dated')]
            found = d._issue_publisher_candidates(candidates, SPEC, START, END,
                frozenset({'https://baseline.example/current-original'}), diagnostics)
        self.assertEqual({call.args[0] for call in download.call_args_list},
                         {'https://www.alpha.example/', 'https://beta.example/'})
        self.assertEqual(download.call_count, 2)
        self.assertEqual(listing.call_count, 2)
        self.assertEqual(history.call_count, 2)
        self.assertEqual(len(found), 4)
        self.assertEqual(diagnostics['issuePublisherPages'], 2)
        self.assertEqual(diagnostics['issuePublisherCandidates'], 4)
        original.assert_not_called()
        model.assert_not_called()

    def test_only_opaque_search_records_can_advertise_publisher_sources(self):
        candidates = [wrapped('direct', 'https://ignored.example/', url='https://direct.example/story'),
                      wrapped('missing', ''),
                      wrapped('Google', 'https://news.google.com/'),
                      wrapped('real', 'https://publisher.example/')]
        diagnostics = {}
        with ExitStack() as stack:
            download, _listing, _history, _original, _model = self.mocks(stack)
            d._issue_publisher_candidates(candidates, SPEC, START, END, frozenset(), diagnostics)
        download.assert_called_once_with('https://publisher.example/')
        self.assertFalse(any('rss/articles' in call.args[0] for call in download.call_args_list))

    def test_rejects_bad_scheme_credentials_port_and_missing_hostname(self):
        invalid = ('javascript:alert(1)', 'file:///C:/private', 'https:missing-host',
                   'https://user:secret@publisher.example/', 'https://publisher.example:bad/',
                   'https://publisher.example:70000/', 'ftp://publisher.example/')
        diagnostics = {}
        with ExitStack() as stack:
            download, listing, history, _original, _model = self.mocks(stack)
            result = d._issue_publisher_candidates([wrapped(str(i), url) for i, url in enumerate(invalid)],
                                                   SPEC, START, END, frozenset(), diagnostics)
        self.assertEqual(result, [])
        self.assertEqual(diagnostics, {'issuePublisherPages': 0, 'issuePublisherCandidates': 0})
        download.assert_not_called()
        listing.assert_not_called()
        history.assert_not_called()

    def test_home_forbidden_stops_that_publisher_without_archive_retry(self):
        with ExitStack() as stack:
            download, listing, history, _original, _model = self.mocks(stack)
            download.side_effect = s.ArticleDigestError('403 inaccessible publisher')
            diagnostics = {}
            result = d._issue_publisher_candidates([wrapped('blocked', 'https://blocked.example/')],
                                                   SPEC, START, END, frozenset(), diagnostics)
        self.assertEqual(result, [])
        download.assert_called_once_with('https://blocked.example/')
        listing.assert_not_called()
        history.assert_not_called()
        self.assertEqual(diagnostics['issuePublisherListingUnavailable'], 1)
        self.assertNotIn('403', str(diagnostics))

    def test_rejects_literal_private_and_non_public_publisher_addresses(self):
        invalid = ('http://127.0.0.1/', 'http://192.168.1.1/', 'http://10.0.0.1/',
                   'http://172.16.1.1/', 'http://169.254.169.254/', 'http://0.0.0.0/',
                   'http://224.0.0.1/', 'http://255.255.255.255/',
                   'http://[::1]/', 'http://[fe80::1]/', 'http://[fc00::1]/',
                   'https://localhost/', 'https://api.localhost/', 'https://intranet/',
                   'https://api.local/', 'https://api.internal/',
                   'http://2130706433/', 'http://0x7f000001/', 'http://127.1/',
                   'https://publisher.example:8443/', 'https://pub lisher.example/')
        with ExitStack() as stack:
            download, listing, history, _original, _model = self.mocks(stack)
            result = d._issue_publisher_candidates([wrapped(str(i), url) for i, url in enumerate(invalid)],
                                                   SPEC, START, END, frozenset(), {})
        self.assertEqual(result, [])
        download.assert_not_called()
        listing.assert_not_called()
        history.assert_not_called()

    def test_trailing_dot_does_not_bypass_local_or_baseline_hostname_checks(self):
        invalid = ('https://localhost./', 'https://api.internal./', 'https://api.local./',
                   'https://baseline.example./')
        with ExitStack() as stack:
            download, _listing, history, _original, _model = self.mocks(stack)
            result = d._issue_publisher_candidates([wrapped(str(i), url) for i, url in enumerate(invalid)],
                SPEC, START, END, frozenset({'https://www.baseline.example/article'}), {})
        self.assertEqual(result, [])
        download.assert_not_called()
        history.assert_not_called()

    def test_dated_archive_gets_selected_week_species_language_and_publisher(self):
        with ExitStack() as stack:
            _download, listing, history, _original, _model = self.mocks(stack)
            dated = link('publisher.example', 'weekly-event')
            history.return_value = [dated]
            result = d._issue_publisher_candidates([wrapped('Named publisher', 'https://publisher.example/')],
                                                   SPEC, START, END, frozenset(), {})
        self.assertIs(result[0], dated)
        self.assertEqual(history.call_args.args[1], 'https://publisher.example/')
        self.assertEqual({key: value for key, value in history.call_args.kwargs.items() if key != 'diagnostics'},
                         {'species': 'beef', 'language': 'en', 'publisher': 'Named publisher',
                          'start': START, 'end': END})
        self.assertEqual(listing.call_args.args[3:5], (START, END))
        self.assertEqual(listing.call_args.args[2].publisher, 'Named publisher')

    def test_discovery_can_return_more_than_six_links_without_reading_bodies(self):
        diagnostics = {'issueOriginalsChecked': 6}
        with ExitStack() as stack:
            _download, listing, history, original, _model = self.mocks(stack)
            listing.return_value = [link('publisher.example', str(i)) for i in range(8)]
            history.return_value = [link('publisher.example', 'archive-' + str(i)) for i in range(7)]
            result = d._issue_publisher_candidates([wrapped('publisher', 'https://publisher.example/')],
                                                   SPEC, START, END, frozenset(), diagnostics)
        self.assertEqual(len(result), 15)
        self.assertEqual(diagnostics['issuePublisherCandidates'], 15)
        self.assertEqual(diagnostics['issueOriginalsChecked'], 6, 'original budget belongs to downstream inspection')
        original.assert_not_called()

    def test_archive_integer_counters_are_namespaced_without_page_or_header_data(self):
        diagnostics = {}
        def archive(*_args, diagnostics, **_kwargs):
            diagnostics.update(publisherArchiveRequests=2, publisherArchiveCandidates=3)
            return [link('publisher.example', str(i)) for i in range(3)]
        with ExitStack() as stack:
            _download, _listing, history, _original, _model = self.mocks(stack)
            history.side_effect = archive
            d._issue_publisher_candidates([wrapped('publisher', 'https://publisher.example/')],
                                          SPEC, START, END, frozenset(), diagnostics)
        self.assertEqual(diagnostics['issuePublisherArchiveRequests'], 2)
        self.assertEqual(diagnostics['issuePublisherArchiveCandidates'], 3)
        self.assertTrue(all(type(value) is int for value in diagnostics.values()))

    def test_archive_debug_strings_boolean_and_non_string_keys_are_not_diagnostics(self):
        diagnostics = {}
        def archive(*_args, diagnostics, **_kwargs):
            diagnostics.update({'publisherArchiveRequests': 1, 'rawPage': '<html>private</html>',
                                'httpHeaders': {'Authorization': 'private'}, 'boolFlag': True,
                                'timing': 0.1, '': 2, 12: 4})
            return []
        with ExitStack() as stack:
            _download, _listing, history, _original, _model = self.mocks(stack)
            history.side_effect = archive
            d._issue_publisher_candidates([wrapped('publisher', 'https://publisher.example/')],
                                          SPEC, START, END, frozenset(), diagnostics)
        self.assertEqual(diagnostics, {'issuePublisherPages': 1, 'issuePublisherArchiveRequests': 1,
                                      'issuePublisherCandidates': 0})
        self.assertTrue(all(type(value) is int for value in diagnostics.values()))

    def test_cancellation_propagates_from_existing_scope_without_request(self):
        event = Event()
        event.set()
        with ExitStack() as stack:
            download, _listing, history, _original, _model = self.mocks(stack)
            with self.assertRaises(ArticleDraftCancelled), article_cancellation_scope(event):
                d._issue_publisher_candidates([wrapped('publisher', 'https://publisher.example/')],
                                              SPEC, START, END, frozenset(), {})
        download.assert_not_called()
        history.assert_not_called()

    def test_cancellation_inside_publisher_lookup_is_not_treated_as_unavailable(self):
        with ExitStack() as stack:
            download, _listing, history, _original, _model = self.mocks(stack)
            download.side_effect = ArticleDraftCancelled('reload cancelled')
            with self.assertRaises(ArticleDraftCancelled):
                d._issue_publisher_candidates([wrapped('publisher', 'https://publisher.example/')],
                                              SPEC, START, END, frozenset(), {})
        download.assert_called_once()
        history.assert_not_called()


if __name__ == '__main__':
    unittest.main()
