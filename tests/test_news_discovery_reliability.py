"""Dated official-source fallbacks, focused candidates and bounded recovery."""
from datetime import date
from unittest.mock import patch
import unittest

from bs4 import BeautifulSoup

from src import livestock_article_draft as d
from src import overseas_article_digest as s


START, END = date(2026, 10, 4), date(2026, 10, 10)


def article(name, **extra):
    return {"title": "US egg prices and supply " + name, "url": "https://example.org/" + name,
            "body": "US egg prices fell as production and supplies recovered. " * 3,
            "publishedDate": date(2026, 10, 6), "publisher": "Test", **extra}


class DiscoveryReliabilityTests(unittest.TestCase):
    def test_official_german_market_uses_original_date_and_description(self):
        # The articleBody field is empty on this publisher's current template.
        html = '<html lang="de-DE"><main><h1 itemprop="headline">Schlachtschweine</h1>'
        html += '<time itemprop="datePublished" datetime="2026-10-06">06.10.2026</time>'
        html += '<h5 itemprop="description">' + (
            'Das Angebot am Schlachtschweinemarkt reicht aus, die Preise bleiben unverändert. ' * 3)
        html += '</h5><div itemprop="articleBody"></div></main></html>'
        with patch.object(s, "_download_soup", return_value=BeautifulSoup(html, "html.parser")):
            found = d._official_market_article(d.SPECS_BY_KEY["eu_pork"], START, END)
            self.assertEqual(found["publishedDate"], date(2026, 10, 6))
            self.assertEqual(found["sourceLanguage"], "de")
            self.assertEqual(found["sourceMethod"], "official")
            self.assertIn("Angebot", found["briefBody"])
            self.assertIsNone(d._official_market_article(d.SPECS_BY_KEY["eu_pork"], date(2026, 10, 11), date(2026, 10, 17)))

    def test_usda_report_date_is_month_day_and_must_match_header(self):
        body = ('Daily National Shell Egg Index Report Agricultural Marketing Service Tue Oct 6, 2026 '
                'Report for: 10/06/2026 National shell egg prices are lower. Supplies are moderate. '
                'NEGOTIATED REGIONAL VOLUME MOVEMENT Shell Eggs Tables 999.99')
        with patch.object(d, "_public_pdf_text", return_value=body), \
             patch.object(d, "_usda_archive_article", return_value=None):
            found = d._official_market_article(d.SPECS_BY_KEY["us_egg"], START, END)
            self.assertEqual(found["publishedDate"], date(2026, 10, 6))
            self.assertIn("Supplies are moderate", found["briefBody"])
            self.assertNotIn("999.99", found["briefBody"])
            self.assertIsNone(d._official_market_article(d.SPECS_BY_KEY["us_egg"], date(2026, 10, 11), date(2026, 10, 17)))
        for invalid in (body.replace('10/06/2026', '10/05/2026'), body.replace('10/06/2026', '13/06/2026')):
            with patch.object(d, "_public_pdf_text", return_value=invalid), \
                 patch.object(d, "_usda_archive_article", return_value=None):
                self.assertIsNone(d._official_market_article(d.SPECS_BY_KEY["us_egg"], START, END))

    def test_preferred_original_precedes_official_fallback(self):
        spec = d.SPECS_BY_KEY["us_egg"]
        with patch.object(s, "_download_soup", return_value=BeautifulSoup("", "html.parser")), \
             patch.object(d, "_choose_original", return_value=article("preferred")), \
             patch.object(d, "_official_market_article") as official:
            found = d._preferred_site_article(spec, START, END)
        self.assertTrue(found["url"].endswith("preferred"))
        official.assert_not_called()

    def test_google_redirects_are_resolved_separately_not_counted_as_originals(self):
        candidates = [article("wrapped", url="https://news.google.com/rss/articles/token"), article("direct")]
        diagnostics = {}
        with patch.object(d, "_original_article", side_effect=lambda candidate, spec: candidate) as read:
            found = d._choose_original(candidates, d.SPECS_BY_KEY["us_egg"], START, END, diagnostics=diagnostics)
        self.assertEqual(found["url"], candidates[1]["url"])
        self.assertEqual(read.call_count, 1)
        self.assertEqual(diagnostics["originalsChecked"], 1)
        self.assertEqual(diagnostics["redirectsUnresolved"], 1)

    def test_headline_search_cannot_transfer_rss_date_to_different_original(self):
        wrapped = article("wrapped", url="https://news.google.com/rss/articles/token",
                          publisherUrl="https://publisher.example/")
        original = {"title": "US egg prices changed", "body": "US egg prices changed",
                    "url": "https://publisher.example/unrelated", "publisher": "Publisher"}
        def public_search(query, language, start, end):
            return [original] if query.startswith("site:") else []
        with patch.object(s, "_search_google_news_rss", return_value=[wrapped]), \
             patch.object(d, "_preferred_site_article", return_value=None), \
             patch.object(d, "_public_bing_candidates", return_value=[]), \
             patch.object(d, "_public_google_candidates", side_effect=public_search), \
             patch.object(d, "_choose_original", return_value=None) as choose:
            d._search_article(d.SPECS_BY_KEY["us_egg"], START, END)
        final_candidates = choose.call_args.args[0]
        publisher_original = next(item for item in final_candidates if item["url"] == original["url"])
        self.assertNotIn("publishedDate", publisher_original)

    def test_alternative_links_exclude_products_and_domestic_restaurant_stories(self):
        spec = d.SPECS_BY_KEY["japan_egg"]
        market = article("market", title="日本の鶏卵相場が上昇", body="日本の鶏卵供給が減り価格が上昇しました。" * 6)
        product = article("product", title="人気鍋チェーン監修の煮たまごが誕生", body="日本のたまご価格と新商品発売について。" * 6)
        main = {**market, "url": "https://example.jp/main", "alternatives": [product]}
        self.assertEqual(d._candidate_links(main, spec, START, END, search_missing=False), [])
        for title in ('交渉成功: recipe egg market', '9개월 만에 철수했던 교촌치킨, 日 시장 재도전…가라아게 넘을까',
                      '이 대통령 치킨값 점검…가맹점들 본사 부담 걱정'):
            candidate = article("restaurant", title=title, body="일본 닭고기 수요와 공급 가격은 변동했다. " * 8)
            self.assertLess(d._relevance(candidate, d.SPECS_BY_KEY["domestic_chicken"]), 0)

    def test_summary_recovery_reuses_verified_alternate_without_another_search(self):
        main = article("main", alternatives=[article("alternate")])
        def summarize(key, title, body):
            if "main" in title:
                raise s.ArticleDigestError("invalid response")
            return "미국 계란 공급 회복으로 가격 하락"
        with patch.object(d, "_usmef_pair", return_value={}), \
             patch.object(d, "_find_section", side_effect=lambda spec, start, end: main if spec.key == "us_egg" else None), \
             patch.object(d, "_search_article", return_value=None) as search, \
             patch.object(d, "_candidate_links", return_value=[]), \
             patch.object(s, "_ensure_ollama_ready", return_value={"available": True}), \
             patch.object(s, "_native_report_sentence", return_value=None), \
             patch.object(s, "_summarize_report_sentence", side_effect=summarize):
            result = d.collect_weekly_livestock_report_draft(date(2026, 10, 7))
        section = result["sections"]["us_egg"]
        self.assertEqual(section["status"], "completed")
        self.assertTrue(section["article"]["url"].endswith("alternate"))
        # The US egg source receives one initial comparison, but recovery
        # must reuse the verified alternate instead of opening another crawl.
        comparison = [call for call in search.call_args_list if call.kwargs.get('editorial')]
        self.assertEqual([call.args[0].key for call in comparison], ['us_egg'])
        self.assertEqual(comparison[0].args[1:3], (START, END))
        self.assertEqual([call.args[0].key for call in search.call_args_list
                          if not call.kwargs.get('editorial')], ["us", "us_pork"])

    def test_domestic_recovery_can_reuse_full_multi_species_original(self):
        spec = d.SPECS_BY_KEY['domestic_chicken']
        main = article('main', title='EU 가금육 수요 약화', body='유럽의 닭고기 수요와 가격이 달라졌다. ' * 8,
                       alternatives=[article('related', title='유럽 닭고기 수요 변화',
                                             body='유럽 닭고기 공급은 생산량 감소로 줄어 가격이 상승했다. ' * 5)])
        shared = article('shared', title='CPTPP 관세만의 문제 아니다', sourceMethod='naver', body=(
            '정부는 CPTPP 가입 논의를 시작했다. 호주산 쇠고기, 멕시코산 쇠고기·돼지고기, '
            '캐나다산 돼지고기·닭고기, 뉴질랜드산 전지분유 등의 수입 증가가 국내 생산 감소로 이어질 수 있다는 전망이다.'))
        found = d._verified_summary_alternatives(main, spec, START, END, [shared, shared])
        self.assertEqual(found[0]['url'], main['alternatives'][0]['url'])
        shared_candidate = next(item for item in found if item['url'] == shared['url'])
        self.assertEqual(shared_candidate['sourceMethod'], 'naver')
        self.assertEqual(len(found), 2)
        self.assertIn('CPTPP 가입 시', s._native_report_sentence(spec.key, shared_candidate['body']))

    def test_shared_recovery_keeps_week_species_and_domestic_boundaries(self):
        main = article('main')
        wrong_species = article('beef', title='호주 쇠고기 수출 증가', body='호주 쇠고기 수요와 수출량 증가. ' * 8)
        stale = article('stale', title='미국 닭고기 수입 증가', body='미국 닭고기 수요와 수입량 증가. ' * 8,
                        publishedDate=date(2026, 9, 30))
        self.assertEqual(d._verified_summary_alternatives(main, d.SPECS_BY_KEY['domestic_chicken'], START, END, [wrong_species, stale]), [])
        self.assertEqual(d._verified_summary_alternatives(main, d.SPECS_BY_KEY['us_egg'], START, END, [article('other')]), [])


if __name__ == "__main__":
    unittest.main()
