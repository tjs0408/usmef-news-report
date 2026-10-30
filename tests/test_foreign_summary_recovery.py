"""Regressions for the two rejected 10/1 drafts; no HTTP/model calls."""
from datetime import date
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from src import overseas_article_digest as s
from src import livestock_article_draft as d


# Short public-source passages, not saved summaries for a particular week.
YARDING = "Total cattle yardings for the week achieved 63,163, down 15,587, week on week."
BRAZIL_LEAD = ("As exportações brasileiras de carne de frango e mel para a União Europeia (UE) "
               "poderão ser retomadas em breve.")
MEETING = ("A sinalização foi dada nesta quarta-feira (30) pelo comissário europeu de Comércio "
           "e Segurança Econômica, durante encontro com os ministros em Milwaukee, nos Estados Unidos.")
PENDING = ("Após o cumprimento das etapas administrativas ainda pendentes, os embarques de produtos "
           "das cadeias de aves e mel poderão ser autorizados novamente pelos países do bloco. "
           "Apesar da sinalização, a liberação das exportações ainda depende de uma decisão técnica da Comissão Europeia.")


class ForeignSummaryRecoveryTests(unittest.TestCase):
    def setUp(self):
        s._summarize_report_sentence.cache_clear()

    def tearDown(self):
        s._summarize_report_sentence.cache_clear()

    def test_cattle_yarding_count_and_delta_without_head_suffix(self):
        summary = s._native_report_sentence("australia", YARDING)
        self.assertEqual(summary, "호주 소 가축시장 주간 출하두수 전주보다 1만 5587두 줄어 6만 3163두 기록")
        self.assertTrue(s._valid_brief(summary, "australia", YARDING))
        self.assertTrue(40 <= len(summary) <= 95)
        self.assertEqual(s._numeric_unit_facts(YARDING), {(63163.0, "animals"), (15587.0, "animals")})

    def test_yarding_rule_uses_changed_numbers_not_a_saved_week(self):
        source = YARDING.replace("63,163", "80,901").replace("15,587", "2,738").replace("down", "up")
        summary = s._native_report_sentence("australia", source)
        self.assertIn("2738두 늘어 8만 901두", summary)
        self.assertTrue(s._valid_brief(summary, "australia", source))
        source = YARDING.replace("15,587", "0")
        self.assertIn("변동 없이", s._native_report_sentence("australia", source))

    def test_yarding_head_suffix_and_reached_form(self):
        source = YARDING.replace("achieved", "reached").replace("15,587,", "15,587 head,")
        self.assertIsNotNone(s._native_report_sentence("australia", source))

    def test_no_yarding_rule_for_sheep_prices_or_missing_comparison(self):
        for source in (YARDING.replace("cattle", "sheep"), YARDING.replace("cattle yardings", "cattle prices"),
                       YARDING.replace(", week on week", ""), YARDING.replace(", down ", ", not down ")):
            with self.subTest(source=source):
                self.assertIsNone(s._cattle_yarding_change(source))
                self.assertIsNone(s._native_report_sentence("australia", source))

    def test_yarding_amount_cannot_be_changed_to_currency_or_percentage(self):
        source = YARDING + " Other beef prices were $5 per kg."
        for summary in ("호주 소고기 가격은 전주보다 1만5587달러 줄어 6만3163달러를 기록",
                        "호주 소 가축시장 출하두수는 전주비 15587% 감소한 6만3163두를 기록"):
            self.assertFalse(s._brief_content_supported(summary, "australia", source))

    def test_cattle_excerpt_excludes_lamb_statistics(self):
        text = "Higher fuel costs influence markets. Cattle market " + YARDING + " Sheep market Lamb yardings decreased by 4,501 head."
        excerpt = s._mla_cattle_excerpt(text)
        self.assertIn(YARDING, excerpt)
        self.assertNotIn("Lamb", excerpt)
        self.assertNotIn("4,501", excerpt)
        self.assertEqual(s._mla_cattle_excerpt("A beef export report with no section headings."),
                         "A beef export report with no section headings.")

    def test_brazil_passive_export_statement_preserves_possibility(self):
        summary = s._native_report_sentence("brazil_chicken", BRAZIL_LEAD)
        self.assertIsNotNone(summary)
        self.assertIn("가능성", summary)
        self.assertTrue(s._valid_brief(summary, "brazil_chicken", BRAZIL_LEAD))

    def test_brazil_pending_approval_caveat_survives_meeting_metadata(self):
        body = " ".join((BRAZIL_LEAD, MEETING, PENDING))
        summary = s._native_report_sentence("brazil_chicken", body)
        self.assertEqual(summary, "브라질 닭고기 EU 수출 재개 가능성 제기, 실제 재개에 추가 승인 절차 필요")
        self.assertNotIn("30", summary)
        self.assertTrue(s._valid_brief(summary, "brazil_chicken", body))

    def test_negated_chicken_reopening_or_honey_only_not_completed(self):
        for body in (BRAZIL_LEAD.replace("poderão", "não poderão"),
                     "A UE não pode retomar compras de frango do Brasil.",
                     "A UE descartou retomar compras de frango do Brasil.",
                     BRAZIL_LEAD.replace("carne de frango e mel", "mel")):
            with self.subTest(body=body):
                self.assertIsNone(s._native_report_sentence("brazil_chicken", body))

    def test_bovine_approval_cannot_become_a_chicken_condition(self):
        body = BRAZIL_LEAD + " A liberação da carne bovina ainda depende de uma decisão técnica da Comissão Europeia."
        summary = s._native_report_sentence("brazil_chicken", body)
        self.assertNotIn("추가 승인", summary)
        self.assertIn("가능성", summary)

    def test_meeting_calendar_cannot_displace_export_lead(self):
        excerpt = s._market_fact_excerpt(BRAZIL_LEAD + " " + MEETING)
        self.assertEqual(excerpt, BRAZIL_LEAD)
        self.assertNotIn("Milwaukee", excerpt)
        self.assertNotIn("30", excerpt)

    def test_failed_translation_gets_one_repair_from_original(self):
        body = "Australian beef production fell 5% on the year due to reduced cattle supplies."
        complete = "호주 소고기 생산량은 소 공급 물량이 줄어든 영향으로 전년과 비교해 5% 감소한 수준을 기록"
        with patch.object(s, "_extract_report_facts", side_effect=s.ArticleSummaryValidationError("invalid")), \
             patch.object(s, "_repair_korean_report_sentence", return_value=complete) as repair, \
             patch.object(s, "_compose_report_sentence") as compose:
            self.assertEqual(s._summarize_report_sentence("australia", "Beef production", body),
                             s.compact_report_summary(complete, "australia", source=body))
            repair.assert_called_once()
            self.assertEqual(repair.call_args.kwargs["facts"], [body])
            self.assertEqual(repair.call_args.kwargs["draft"], "")
            compose.assert_not_called()

    def test_failed_repair_cannot_invent_a_statistic_or_outlook(self):
        body = "Australian beef production fell 5% on the year due to reduced cattle supplies."
        for wrong in ("호주 소고기 생산량은 소 공급 감소로 전년과 비교해 50% 감소한 수준을 기록",
                      "호주 소고기 생산량은 소 공급 감소로 앞으로도 감소세가 이어질 것으로 전망",
                      "호주 소고기 생산은 감소"):
            with self.subTest(wrong=wrong), \
                 patch.object(s, "_extract_report_facts", side_effect=s.ArticleSummaryValidationError("invalid")), \
                 patch.object(s, "_repair_korean_report_sentence", return_value=wrong) as repair:
                with self.assertRaises(s.ArticleDigestError):
                    s._summarize_report_sentence("australia", "Beef production", body)
                repair.assert_called_once()

    def test_transport_failure_does_not_retry_as_a_translation_failure(self):
        with patch.object(s, "_extract_report_facts", side_effect=s.ArticleDigestError("offline")), \
             patch.object(s, "_repair_korean_report_sentence") as repair:
            with self.assertRaisesRegex(s.ArticleDigestError, "offline"):
                s._summarize_report_sentence("australia", "Beef production", "Australian beef production declined.")
            repair.assert_not_called()

    def test_exact_two_passages_need_no_inference(self):
        with patch.object(s, "_ollama_generate") as generate:
            for kind, body in (("australia", YARDING), ("brazil_chicken", BRAZIL_LEAD + " " + PENDING)):
                summary = s._summarize_report_sentence(kind, "market news", body)
                self.assertTrue(s._valid_brief(summary, kind, body))
            generate.assert_not_called()

    def test_collector_uses_full_source_for_approval_even_if_brief_omits_it(self):
        article = {"title": "Export reopening", "url": "https://example.org/public-news", "publishedDate": date(2026, 9, 30),
                   "publisher": "Public newspaper", "body": BRAZIL_LEAD + " " + PENDING, "briefBody": BRAZIL_LEAD}
        with patch.object(d, "_usmef_pair", return_value={}), patch.object(d, "_search_article", return_value=None), \
             patch.object(d, "_find_section", side_effect=lambda spec, start, end: article if spec.key == "brazil_chicken" else None), \
             patch.object(s, "_ensure_ollama_ready", return_value={"available": False, "message": "offline"}), \
             patch.object(s, "_ollama_generate") as generate:
            result = d.collect_weekly_livestock_report_draft(date(2026, 10, 1))
        self.assertEqual(result["readyCount"], 1)
        self.assertEqual(result["sections"]["brazil_chicken"]["status"], "completed")
        self.assertIn("추가 승인", result["sections"]["brazil_chicken"]["summary"])
        generate.assert_not_called()

    def test_actual_article_container_wins_over_newsis_wrapper(self):
        body = ("중국이 브라질의 소고기 수입품에 대해 55%의 추가 관세를 부과한다고 상무부가 발표했다. "
                "상무부는 올해 브라질 소고기 수입 할당량이 100% 소진됐다고 밝혔다. "
                "브라질 수출업체들은 유럽연합과 수출 재개를 위한 협상을 벌이고 있다.")
        html = ('<html lang="ko"><meta property="article:published_time" content="2026-10-01T11:30:00+09:00">'
                '<h1>브라질 소고기에 추가 관세</h1><div class="article_view articleView">'
                '<div>구글에서 선호하는 매체로 추가 작게 크게 등록 2026.10.01</div>'
                '<div class="viewer"><article><div class="caption">유엔 총회 사진 설명</div>'
                f'<p>{body}</p></article></div><aside>돼지고기 수입 소식</aside></div></html>')
        with patch.object(s, "_download_soup", return_value=BeautifulSoup(html, "html.parser")):
            result = d._read_original_article({"url": "https://example.org/public"}, d.SPECS_BY_KEY["domestic"])
        self.assertEqual(result["body"], body)
        self.assertNotIn("구글", result["briefBody"])
        self.assertNotIn("총회", result["briefBody"])

    def test_newdaily_inner_text_and_original_publication_date(self):
        body = "가입이 이뤄질 경우 캐나다산 돼지고기와 닭고기 수입이 늘어나 국내 생산은 감소할 것으로 전망됐다. " * 3
        html = ('<html lang="ko"><meta property="article:published_time" content="2026-09-27T08:00:00+0900">'
                '<h1>CPTPP 가입에 따른 축산물 수입 증가 전망</h1><div class="article-body">'
                f'<div>표제·화면 버튼</div><div id="article_conent">{body}</div></div></html>')
        with patch.object(s, "_download_soup", return_value=BeautifulSoup(html, "html.parser")):
            result = d._read_original_article({"url": "https://example.org/2026/09/23/news.html"}, d.SPECS_BY_KEY["domestic_pork"])
        self.assertNotIn("화면 버튼", result["body"])
        self.assertEqual(result["publishedDate"], date(2026, 9, 27))

    def test_korean_cpi_does_not_become_overseas_pork_because_of_imported_beef(self):
        article = {"title": '9월 물가 2.9%↑…정부 "석유 최고가격제 없었다면 3.5%"',
                   "body": "국산쇠고기는 전년 동월보다 6.6%, 수입쇠고기는 7.2%, 돼지고기는 1.9% 각각 올랐다."}
        self.assertFalse(d._domestic_overseas_focus(article, d.SPECS_BY_KEY["domestic_pork"]))
        article.update(title="미국 9월 소비자물가 상승, 돼지고기 공급 부족", body="미국 돼지고기 가격은 공급 부족으로 4% 상승했다.")
        self.assertTrue(d._domestic_overseas_focus(article, d.SPECS_BY_KEY["domestic_pork"]))
        article['title'] = "미국 돼지고기 공급 부족에 가격 상승"
        self.assertTrue(d._domestic_overseas_focus(article, d.SPECS_BY_KEY["domestic_pork"]))

    def test_tariff_announcement_preserves_importer_exporter_and_quota_cause(self):
        body = ("중국이 남미의 친중 국가인 브라질의 소고기 수입품에 대해 1일부터 55%의 추가 관세를 부과한다고 상무부가 발표했다. "
                "상무부는 올해 브라질 소고기 수입 할당량이 100% 소진됐다고 이유를 밝혔다.")
        summary = s._native_report_sentence("domestic", body)
        self.assertEqual(summary, "중국이 브라질산 쇠고기 수입 할당량 소진에 따라 55%의 추가 관세를 부과")
        self.assertTrue(s._valid_brief(summary, "domestic", body))
        self.assertIsNone(s._native_report_sentence("domestic", body.replace("부과한다고", "부과하지 않는다고")))
        summary = s._native_report_sentence("domestic", body.replace("소진됐다고", "소진되지 않았다고"))
        self.assertNotIn("소진에 따라", summary)
        self.assertIn("55%", summary)
        alternate = body.replace("중국이", "일본이").replace("브라질", "호주").replace("55%", "27%")
        summary = s._native_report_sentence("domestic", alternate)
        self.assertIn("일본이 호주산", summary)
        self.assertIn("27%", summary)

    def test_korean_qualitative_excerpt_retains_context_before_repair(self):
        body = "미국 쇠고기 수입 정책 검토가 이어지고 있다. 정부는 물가 부담과 농가 수익에 미치는 영향을 함께 검토한다."
        self.assertEqual(s._market_fact_excerpt(body), body)

    def test_korean_egg_legal_article_is_not_selected_by_an_overseas_comparison(self):
        article = {"title": "계란 유통 81.7%가 도매인데…가격은 소매가 좌우",
                   "body": "공정거래위원회는 대한산란계협회에 과징금을 부과했다. 일본 계란 가격과 유통 구조도 비교된다."}
        self.assertFalse(d._domestic_overseas_focus(article, d.SPECS_BY_KEY["domestic_egg"]))
        article.update(title="홍콩에 한국산 계란 수출 재개", body="홍콩 계란 시장에 한국산 계란 수출이 재개돼 공급 물량이 확대됐다.")
        self.assertTrue(d._domestic_overseas_focus(article, d.SPECS_BY_KEY["domestic_egg"]))

    def test_domestic_final_sentence_must_keep_an_overseas_event(self):
        domestic = "공정거래위원회는 대한산란계협회가 거래 가격을 결정했다며 과징금 5억9400만원을 부과"
        self.assertFalse(s._valid_brief(domestic, "domestic_egg", domestic))
        local_only = "한국 농촌경제연구원 예측에 따르면 앞으로 돼지고기 생산량이 감소할 가능성이 지속"
        self.assertFalse(s._valid_brief(local_only, "domestic_pork", local_only))
        foreign = "한국산 계란의 홍콩 수출이 다시 시작되면서 홍콩 계란시장의 공급 물량이 확대될 것으로 전망"
        self.assertTrue(s._valid_brief(foreign, "domestic_egg", foreign))

    def test_cptpp_forecast_retains_the_policy_condition_and_target_species(self):
        body = ("정부가 CPTPP 가입 논의에 착수했다. "
                "호주산 소고기, 멕시코산 소고기·돼지고기, 캐나다산 돼지고기·닭고기 등의 수입 증가로 국내 축산물 생산이 줄어들 것으로 예상됐다.")
        for kind, product in (("domestic_pork", "돼지고기"), ("domestic_chicken", "닭고기")):
            summary = s._native_report_sentence(kind, body)
            self.assertIn("CPTPP 가입 시", summary)
            self.assertIn(product, summary)
            self.assertIn("예상", summary)
            self.assertTrue(s._valid_brief(summary, kind, body))
            self.assertIsNone(s._grounded_market_statistic(kind, body.replace("수입 증가로", "수입 증가가 없어").replace("생산이 줄어들", "생산이 줄어들지 않을")))


if __name__ == "__main__":
    unittest.main()
