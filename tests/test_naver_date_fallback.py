"""Official API first, with bounded public date-search coverage for older weeks."""
from datetime import date
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from src import overseas_article_digest as s


START, END = date(2026, 8, 30), date(2026, 9, 5)
CREDS = {'NAVER_CLIENT_ID': 'test-id', 'NAVER_CLIENT_SECRET': 'test-secret'}


def candidate(name='api', title='미국 계란 가격 하락', **extra):
    return {'title': title, 'url': 'https://example.org/' + name,
            'body': '미국 계란 공급 회복으로 도매가격 하락',
            'publishedDate': date(2026, 9, 3), **extra}


class NaverDateFallbackTests(unittest.TestCase):
    def test_successful_but_empty_api_does_not_suppress_date_web_search(self):
        original = candidate('web', discoveryMethod='naver_web')
        with patch.dict(os.environ, CREDS), \
             patch.object(s, '_search_naver_news_api', return_value=[]) as api, \
             patch.object(s, '_search_naver_news_web', return_value=[original]) as web:
            self.assertEqual(s._search_naver_news('미국 계란', START, END), [original])
        api.assert_called_once()
        web.assert_called_once_with('미국 계란', START, END)

    def test_sufficient_focused_api_keeps_priority_and_does_not_add_request(self):
        originals = [candidate(str(index)) for index in range(3)]
        with patch.dict(os.environ, CREDS), \
             patch.object(s, '_search_naver_news_api', return_value=originals), \
             patch.object(s, '_search_naver_news_web') as web:
            self.assertIs(s._search_naver_news('미국 계란', START, END), originals)
        web.assert_not_called()

    def test_thin_recipe_candidates_trigger_more_search_without_relaxing_validation(self):
        incidental = [candidate(str(index), title='라면에 계란 넣는 조리법') for index in range(3)]
        market = candidate('market')
        with patch.dict(os.environ, CREDS), \
             patch.object(s, '_search_naver_news_api', return_value=incidental), \
             patch.object(s, '_search_naver_news_web', return_value=[market]) as web:
            found = s._search_naver_news('계란 수입', START, END)
        self.assertEqual(found, incidental + [market])
        web.assert_called_once()

    def test_partial_date_coverage_is_supplemented_and_duplicate_api_record_kept(self):
        originals = s._NaverApiResults([candidate(str(index), discoveryMethod='naver_api') for index in range(3)])
        originals.coverage_incomplete = True
        with patch.dict(os.environ, CREDS), \
             patch.object(s, '_search_naver_news_api', return_value=originals), \
             patch.object(s, '_search_naver_news_web', return_value=[candidate('0'), candidate('web')]):
            found = s._search_naver_news('계란 수입', START, END)
        self.assertEqual(len(found), 4)
        self.assertEqual(found[0]['discoveryMethod'], 'naver_api')

    def test_web_error_cannot_discard_existing_api_candidates(self):
        originals = [candidate()]
        with patch.dict(os.environ, CREDS), \
             patch.object(s, '_search_naver_news_api', return_value=originals), \
             patch.object(s, '_search_naver_news_web', side_effect=s.ArticleDigestError('public search unavailable')):
            self.assertIs(s._search_naver_news('계란 수입', START, END), originals)

    def test_auth_api_error_can_fall_back_to_normal_public_search(self):
        with patch.dict(os.environ, CREDS), \
             patch.object(s, '_search_naver_news_api', side_effect=s.ArticleDigestError('API unavailable')), \
             patch.object(s, '_search_naver_news_web', return_value=[candidate('web')]):
            self.assertEqual(s._search_naver_news('계란 수입', START, END)[0]['url'], candidate('web')['url'])

    def test_far_newer_api_page_stops_before_wasting_another_four_calls(self):
        items = [{'title': '미국 계란 가격', 'originallink': f'https://example.org/{index}',
                  'pubDate': 'Wed, 30 Sep 2026 10:00:00 +0900'} for index in range(100)]
        with patch.object(s, '_request_json', return_value={'items': items}) as request:
            found = s._search_naver_news_api('계란 수입', START, END, 'test', 'test')
        self.assertEqual(found, [])
        self.assertTrue(found.coverage_incomplete)
        self.assertEqual(found.pages_read, 1)
        request.assert_called_once()

    def test_nearby_historical_week_can_still_use_second_api_page(self):
        recent = [{'title': '미국 계란 가격', 'originallink': f'https://example.org/{index}',
                   'pubDate': 'Wed, 09 Sep 2026 10:00:00 +0900'} for index in range(100)]
        target = {'title': '미국 계란 가격', 'originallink': 'https://example.org/target',
                  'pubDate': 'Thu, 03 Sep 2026 10:00:00 +0900'}
        with patch.object(s, '_request_json', side_effect=[{'items': recent}, {'items': [target]}]) as request:
            found = s._search_naver_news_api('계란 수입', START, END, 'test', 'test')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['discoveryMethod'], 'naver_api')
        self.assertEqual(request.call_count, 2)
        self.assertFalse(found.coverage_incomplete)

    def test_public_web_uses_exact_dates_and_never_labels_outside_result_as_this_week(self):
        def card(stamp, slug):
            return (f'<div><a data-heatmap-target=".prof">Test News</a><span>{stamp}</span>'
                    f'<a data-heatmap-target=".tit" href="https://example.org/{slug}">미국 계란 공급 회복</a>'
                    '<p data-heatmap-target=".body">미국 계란 공급량이 늘어 가격 하락</p></div>')
        html = BeautifulSoup(card('2026.09.03.', 'correct') + card('2026.09.06.', 'outside'), 'html.parser')
        with patch.object(s, '_download_soup', return_value=html) as read:
            found = s._search_naver_news_web('미국 계란', START, END)
        query = parse_qs(urlparse(read.call_args.args[0]).query)
        self.assertEqual(query['nso'], ['so:r,p:from20260830to20260905,a:all'])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['publishedDate'], date(2026, 9, 3))
        self.assertEqual(found[0]['discoveryMethod'], 'naver_web')


if __name__ == '__main__':
    unittest.main()
