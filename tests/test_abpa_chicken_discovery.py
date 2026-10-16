"""Official ABPA fallback discovers URLs and verifies publisher metadata/body."""
from datetime import date
from email.utils import format_datetime
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src import livestock_article_draft as d
from src import overseas_article_digest as s


START, END = date(2026, 10, 4), date(2026, 10, 10)
REPORT_DAY = date(2026, 10, 7)
ARTICLE_URL = "https://abpa-br.org/noticias/frango-exportacoes-publicadas/"
ORIGINAL_TITLE = "Exportações oficiais de frango no Brasil"
ORIGINAL_BODY = (
    "As exportações brasileiras de carne de frango totalizaram 601,7 mil toneladas em outubro. "
    "Segundo a ABPA, produção, oferta e demanda indicam crescimento do mercado brasileiro. "
    "Os embarques e a receita do setor foram superiores aos resultados do ano anterior."
)


def rss(published=date(2026, 10, 7), *, url=ARTICLE_URL):
    stamp = format_datetime(datetime.combine(published, datetime.min.time(), tzinfo=timezone.utc))
    return ("<rss><channel><item><title>Exportações de frango aumentam</title>"
            f"<link>{url}</link><pubDate>{stamp}</pubDate>"
            "<description>Discovery snippet, never the original body.</description>"
            "</item></channel></rss>")


def original(published="2026-10-07", *, body=ORIGINAL_BODY, modified="2026-10-09"):
    stamp = f'<meta property="article:published_time" content="{published}T12:08:35+00:00">' if published else ""
    html = (f'<html lang="pt-BR"><meta property="og:title" content="{ORIGINAL_TITLE}">'
            f'<meta property="og:site_name" content="ABPA">{stamp}'
            f'<meta property="article:modified_time" content="{modified}T12:08:35+00:00">'
            f'<main><h1>{ORIGINAL_TITLE}</h1><div class="elementor-widget-theme-post-content"><p>{body}</p></div></main>'
            '<article>Brazil egg prices and supply changed. Related article text is not chicken evidence.</article></html>')
    return BeautifulSoup(html, "html.parser")


class AbpaChickenDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.spec = d.SPECS_BY_KEY["brazil_chicken"]

    def test_public_news_feed_discovers_original_title_date_and_full_body(self):
        with patch.object(s, "_download_html", return_value=rss()) as feed, \
             patch.object(s, "_download_soup", side_effect=lambda url: original()) as read:
            chosen = d._abpa_chicken_article(self.spec, START, END)
        self.assertEqual(chosen["url"], ARTICLE_URL)
        self.assertEqual(chosen["title"], ORIGINAL_TITLE)
        self.assertEqual(chosen["publishedDate"], date(2026, 10, 7))
        self.assertEqual(chosen["body"], ORIGINAL_BODY)
        self.assertEqual(chosen["publisher"], "ABPA")
        self.assertEqual(chosen["sourceLanguage"], "pt")
        self.assertEqual(chosen["sourceMethod"], "official")
        self.assertFalse(chosen["searchResult"])
        self.assertNotIn("Discovery snippet", chosen["body"])
        self.assertNotIn("Related article", chosen["body"])
        feed.assert_called_once_with(d.ABPA_CHICKEN_NEWS_FEED_URL)
        read.assert_called_once_with(ARTICLE_URL)
        self.assertNotIn("2026", d.ABPA_CHICKEN_NEWS_FEED_URL)

    def test_feed_date_cannot_replace_missing_or_old_original_publication_metadata(self):
        for stamp in (None, "2026-10-03", "2026-10-11"):
            with self.subTest(stamp=stamp), patch.object(s, "_download_html", return_value=rss()), \
                 patch.object(s, "_download_soup", side_effect=lambda url: original(stamp)):
                self.assertIsNone(d._abpa_chicken_article(self.spec, START, END))

    def test_another_week_never_uses_the_previous_article_or_downloads_it(self):
        with patch.object(s, "_download_html", return_value=rss()), patch.object(s, "_download_soup") as read:
            self.assertIsNone(d._abpa_chicken_article(self.spec, date(2026, 10, 11), date(2026, 10, 17)))
        read.assert_not_called()

    def test_feed_date_is_discovery_only_and_is_removed_before_original_reader(self):
        with patch.object(s, "_download_html", return_value=rss()), \
             patch.object(d, "_choose_original", return_value=None) as choose:
            self.assertIsNone(d._abpa_chicken_article(self.spec, START, END))
        self.assertEqual(len(choose.call_args.args[0]), 1)
        self.assertNotIn("publishedDate", choose.call_args.args[0][0])

    def test_unreadable_body_wrong_species_and_external_feed_links_are_rejected(self):
        cases = ((ARTICLE_URL, "short excerpt"),
                 (ARTICLE_URL, "Brazil pork prices and pig production exports increased. " * 5),
                 ("https://unrelated.example/chicken", ORIGINAL_BODY))
        for url, body in cases:
            with self.subTest(url=url, body=body), patch.object(s, "_download_html", return_value=rss(url=url)), \
                 patch.object(s, "_download_soup", side_effect=lambda url: original(body=body)):
                self.assertIsNone(d._abpa_chicken_article(self.spec, START, END))

    def test_avisite_failure_selects_abpa_before_general_news_search(self):
        def page(url):
            if "avisite" in url:
                raise s.ArticleDigestError("publisher unavailable")
            self.assertEqual(url, ARTICLE_URL)
            return original()
        with patch.object(s, "_download_soup", side_effect=page), \
             patch.object(s, "_download_html", return_value=rss()), \
             patch.object(d, "_search_article") as general_search:
            chosen = d._find_section(self.spec, START, END)
        self.assertEqual(chosen["url"], ARTICLE_URL)
        self.assertEqual(chosen["publishedDate"], date(2026, 10, 7))
        self.assertEqual(chosen["sourceMethod"], "official")
        general_search.assert_not_called()

    def test_existing_avisite_original_keeps_priority_over_official_fallback(self):
        preferred = {"url": "https://www.avisite.com.br/frango/", "publishedDate": START}
        with patch.object(s, "_download_soup", return_value=BeautifulSoup("", "html.parser")), \
             patch.object(d, "_choose_original", return_value=preferred), \
             patch.object(d, "_abpa_chicken_article") as abpa:
            chosen = d._preferred_site_article(self.spec, START, END)
        self.assertIs(chosen, preferred)
        abpa.assert_not_called()

    def test_collector_final_selection_preserves_verified_abpa_metadata(self):
        find_section = d._find_section
        def page(url):
            if "avisite" in url:
                raise s.ArticleDigestError("publisher unavailable")
            self.assertEqual(url, ARTICLE_URL)
            return original()
        with patch.object(d, "_usmef_pair", return_value={}), \
             patch.object(d, "_find_section", side_effect=lambda spec, start, end:
                          find_section(spec, start, end) if spec.key == "brazil_chicken" else None), \
             patch.object(d, "_search_article", return_value=None), \
             patch.object(s, "_download_html", return_value=rss()), \
             patch.object(s, "_download_soup", side_effect=page), \
             patch.object(s, "_ensure_ollama_ready", return_value={"available": True}), \
             patch.object(s, "_native_report_sentence", return_value=None), \
             patch.object(s, "_summarize_report_sentence", return_value="브라질 닭고기 수출량은 원문에서 확인한 통계에 따라 증가한 것으로 집계"):
            result = d.collect_weekly_livestock_report_draft(REPORT_DAY)
        section = result["sections"]["brazil_chicken"]
        self.assertEqual(section["status"], "completed")
        self.assertEqual(section["article"]["url"], ARTICLE_URL)
        self.assertEqual(section["article"]["title"], ORIGINAL_TITLE)
        self.assertEqual(section["article"]["publishedDate"], "2026-10-07")
        self.assertEqual(section["article"]["publisher"], "ABPA")
        self.assertEqual(section["sourceMethod"], "official")
        self.assertEqual(section["retryCount"], 0)


if __name__ == "__main__":
    unittest.main()
