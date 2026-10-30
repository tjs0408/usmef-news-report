from datetime import date
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src import livestock_article_draft as d


START, END = date(2026, 10, 11), date(2026, 10, 17)
BASE = d.INDEXBOX_EGG_NEWS_URL
ARTICLE = "https://www.indexbox.io/blog/example-us-shell-egg-demand/"
SPEC = d.SPECS_BY_KEY["us_egg"]
BODY = ("The weekly Shell Egg Demand Indicator for shell eggs stood at 2.80 as of October 14, 2026, "
        "according to the USDA AMS MyMarketNews report. The reading was down 4.7 points from the prior week, "
        "reflecting an estimate of shell egg demand calculated from current production and inventory.")


def page(stamp="2026-10-14", *, body=BODY):
    return BeautifulSoup(f'''<html lang="en"><head><link rel="canonical" href="{ARTICLE}">
      <script type="application/ld+json">{{"@type":"NewsArticle","datePublished":"{stamp}T09:00:00Z"}}</script>
      </head><body><h1>USDA Shell Egg Demand Indicator Declines</h1>
      <article>Paid catalog company card: egg prices 999 dollars and 99% growth.</article>
      <div id="abstr-tab-pane"><p>{body}</p>
      <aside class="price__block"><p>Buy eggs report for $4,000. Eggs prices rise 99%.</p></aside>
      <div class="kmp-panel"><article>Company rankings and paid report.</article></div></div>
      </body></html>''', "html.parser")


def listing(stamp="Oct 14, 2026", *, href=ARTICLE):
    return BeautifulSoup(f'''<article class="blog-news-card"><div class="blog-news-card__body">
      <span class="blog-news-card__date">{stamp}</span><a class="blog-news-card__title-link" href="{href}">
      <h3>USDA Shell Egg Demand Indicator Declines</h3></a>
      <p class="blog-news-card__text">USDA AMS reports U.S. egg demand lower.</p></div></article>''', "html.parser")


class UsEggPublicMarketFallbackTests(unittest.TestCase):
    def test_story_tab_is_read_instead_of_paid_company_article_card(self):
        with patch.object(d.source, "_download_soup", return_value=page()):
            article = d._original_article({"url": ARTICLE}, SPEC)
        self.assertEqual(article["body"], BODY)
        self.assertEqual(article["publisher"], "IndexBox")
        self.assertEqual(article["publishedDate"], date(2026, 10, 14))
        self.assertNotIn("$4,000", article["body"])
        self.assertNotIn("999 dollars", article["body"])

    def test_public_category_discovers_same_week_link_without_fixed_article(self):
        with patch.object(d.source, "_download_soup", side_effect=lambda url: listing() if url == BASE else page()):
            article = d._indexbox_egg_article(SPEC, START, END)
        self.assertEqual(article["url"], ARTICLE)
        self.assertEqual(article["publisher"], "IndexBox")
        self.assertEqual(article["sourceMethod"], "search")
        self.assertEqual(article["sourceLanguage"], "en")

    def test_old_actual_publication_is_not_relabelled_from_listing(self):
        with patch.object(d.source, "_download_soup", side_effect=lambda url:
                          listing() if url == BASE else page(stamp="2026-10-09")):
            self.assertIsNone(d._indexbox_egg_article(SPEC, START, END))

    def test_out_of_week_listing_or_external_link_is_never_downloaded(self):
        for html in (listing("Oct 9, 2026"), listing(href="https://untrusted.example/story")):
            with self.subTest(html=html), patch.object(d.source, "_download_soup", return_value=html) as download:
                self.assertIsNone(d._indexbox_egg_article(SPEC, START, END))
                download.assert_called_once_with(BASE)

    def test_foreign_only_egg_body_is_not_proof_of_us_market(self):
        with patch.object(d.source, "_download_soup", side_effect=lambda url: listing() if url == BASE else
                          page(body="Egg prices in Japan are higher due to feed costs. Japanese egg supply remains tight. " * 3)):
            self.assertIsNone(d._indexbox_egg_article(SPEC, START, END))

    def test_missing_public_story_tab_cannot_fall_back_to_paid_catalog(self):
        html = page()
        html.select_one("#abstr-tab-pane").decompose()
        with patch.object(d.source, "_download_soup", return_value=html):
            self.assertIsNone(d._original_article({"url": ARTICLE}, SPEC))

    def test_other_species_does_not_call_egg_fallback(self):
        with patch.object(d.source, "_download_soup") as download:
            self.assertIsNone(d._indexbox_egg_article(d.SPECS_BY_KEY["us_chicken"], START, END))
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
