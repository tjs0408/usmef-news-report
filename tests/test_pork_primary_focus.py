"""Pork briefs must describe pork markets, not merely compare chicken to pork.

The evidence is synthetic. Tests exercise the common relevance gate both for
the selected original and for the two displayed replacement links, offline.
"""
from datetime import date
import unittest
from unittest.mock import patch

from src import livestock_article_draft as d


START, END = date(2026, 10, 11), date(2026, 10, 17)
PORK = d.SPECS_BY_KEY["domestic_pork"]
CHICKEN = d.SPECS_BY_KEY["domestic_chicken"]
EGG = d.SPECS_BY_KEY["domestic_egg"]

CHICKEN_COMPARISON = (
    "장기간 지속되는 고물가와 엔화 약세의 영향으로 일본에서 닭고기 소비가 "
    "돼지고기를 추월하는 이례적인 상황이 벌어지고 있다. "
    "일본 가계가 상대적으로 저렴한 닭고기를 선택하면서 닭고기 소비가 늘었다. "
    "닭고기는 돼지고기보다 가격이 낮아 부담을 덜 수 있다는 설명이다. "
    "현지 유통업계는 닭고기 수요 증가에 맞춰 닭고기 공급 물량을 확보하고 있다."
)
PORK_PRICE = (
    "독일 돼지고기 도매가격은 전주보다 4% 하락했다. "
    "독일 도축장의 돼지고기 공급 물량 증가와 소비 수요 둔화가 가격 하락의 원인이다. "
    "돼지고기 수출 물량은 전월보다 3% 늘었고 현지 양돈농가는 출하 시기를 조정했다."
)
EGG_FINANCE = (
    "브라질산 계란을 수입하면서 투입한 재정의 적정성을 놓고 논란이 이어졌다. "
    "브라질산 계란은 항공운임과 관세를 합친 개당 수입 단가가 1464원에 달했다. "
    "정부는 계란 공급 부족에 대비한 수급 안정 조치였다고 설명했다. "
    "야당은 계란 구입 가격과 수송비를 합친 재정 부담을 따져야 한다고 밝혔다. "
    "양국 정상은 공동성명에서 브라질산 쇠고기·돼지고기의 한국 시장 접근 약속도 재확인했다."
)
CPTPP = (
    "정부는 CPTPP 가입 논의를 시작했다. 호주산 쇠고기, 멕시코산 쇠고기·돼지고기, "
    "캐나다산 돼지고기·닭고기, 뉴질랜드산 전지분유 등의 수입 증가가 "
    "국내 생산 감소로 이어질 수 있다는 전망이다."
)


def article(name, title, body, **changes):
    return {
        "url": "https://example.org/" + name,
        "title": title,
        "publisher": "검증 매체",
        "publishedDate": date(2026, 10, 16),
        "sourceLanguage": "ko",
        "body": body,
        **changes,
    }


def chicken_story(name="chicken"):
    return article(name, "일본, 돼지고기보다 닭고기 소비 증가", CHICKEN_COMPARISON)


def pork_story(name="pork"):
    return article(name, "독일 돼지고기 공급 증가로 도매가격 하락", PORK_PRICE)


class PorkPrimaryFocusTests(unittest.TestCase):
    def test_chicken_consumption_surpassing_pork_is_chicken_not_pork(self):
        candidate = chicken_story()
        self.assertLess(d._relevance(candidate, PORK), 0)
        self.assertGreaterEqual(d._relevance(candidate, CHICKEN), 0)

    def test_repeating_comparison_mentions_cannot_manufacture_pork_focus(self):
        comparisons = (
            "일본 닭고기 소비는 돼지고기 소비를 넘어섰다. ",
            "일본 닭고기 가격은 돼지고기보다 30% 저렴해 닭고기 수요가 늘었다. ",
            "일본 소비자들은 돼지고기 대신 닭고기를 구입해 닭고기 판매가 증가했다. ",
        )
        for comparison in comparisons:
            for repetitions in (1, 6):
                with self.subTest(comparison=comparison, repetitions=repetitions):
                    candidate = chicken_story()
                    candidate["body"] += " " + comparison * repetitions
                    self.assertLess(d._relevance(candidate, PORK), 0)
                    self.assertGreaterEqual(d._relevance(candidate, CHICKEN), 0)

    def test_pork_own_price_supply_production_and_trade_facts_remain_valid(self):
        facts = (
            ("미국 돼지고기 소매가격 하락", "미국 돼지고기 소매가격은 공급 증가로 전년보다 2.1% 하락했다."),
            ("독일 돼지고기 공급 확대", "독일 돼지고기 공급은 도축 물량 증가로 전월보다 5% 늘었다."),
            ("미국 돼지고기 생산 증가", "미국 돼지고기 생산량은 출하 체중 상승으로 전년보다 3% 증가했다."),
            ("브라질 돼지고기 수출 확대", "브라질 돼지고기 수출량은 해외 수요 회복으로 전년보다 8% 늘었다."),
        )
        for title, body in facts:
            with self.subTest(title=title):
                self.assertGreaterEqual(d._relevance(article("independent", title, body), PORK), 0)

    def test_general_cpi_headline_with_pork_supply_explanation_is_usable(self):
        candidate = article("cpi", "미국 소비자물가 발표, 식품별 가격 차별화", (
            "미국 소비자물가는 전년보다 2.4% 상승했다. "
            "미국 돼지고기 소매가격은 공급 확대로 전년보다 2.1% 하락했다. "
            "닭고기 가격은 전년보다 3% 상승했고 계란 가격은 4% 하락했다."
        ))
        self.assertGreaterEqual(d._relevance(candidate, PORK), 0)
        self.assertEqual(d._selection_profile(candidate, PORK)[0], 1)

    def test_pork_fact_buried_in_unrelated_car_company_finance_is_not_selected(self):
        candidate = article('car-finance', '농민 희생 딛고 글로벌 3위 오른 현대차, 상생기금은 생색',
            '현대차의 농어촌 상생기금 출연 규모를 논의했다. ' * 15 +
            '미국산 돼지고기 수입 증가로 국내 생산량이 감소했다. 독일 돼지고기 수출량도 증가했다.')
        self.assertLess(d._relevance(candidate, PORK), 0)

    def test_cptpp_multi_species_import_production_consequences_remain_valid(self):
        candidate = article("cptpp", "CPTPP 가입 논의와 해외 축산물 교역 변화", CPTPP)
        self.assertGreaterEqual(d._relevance(candidate, PORK), 0)
        self.assertGreaterEqual(d._relevance(candidate, CHICKEN), 0)

    def test_egg_finance_story_incidental_market_access_pledge_is_not_pork(self):
        candidate = article("egg-finance", "브라질산 계란 수입단가 논란, 돼지고기 개방 약속도", EGG_FINANCE)
        self.assertLess(d._relevance(candidate, PORK), 0)
        self.assertGreaterEqual(d._relevance(candidate, EGG), 0)

    def test_comparison_statistics_and_shared_price_pressure_are_not_a_pork_section(self):
        candidate = chicken_story()
        candidate['title'] = '소고기는 사치, 돼지고기도 버겁다…닭고기에 1위 내준 일본'
        candidate['body'] += (' 일본 돼지고기 소비량은 258만톤, 소고기는 116만톤이었다. '
            '엔저로 수입 소고기와 돼지고기 가격이 오른 가운데 육류 전반의 가격 상승 압력이 커지고 있다.')
        self.assertLess(d._relevance(candidate, PORK), 0)

    def test_independently_substantial_pork_section_in_mixed_story_remains_valid(self):
        candidate = article("mixed", "브라질산 계란 수입 논란과 돼지고기 교역 변화", (
            EGG_FINANCE + "\n\n브라질 돼지고기 시장 동향\n"
            "브라질 돼지고기 생산량은 도축 마릿수 증가로 전년보다 4% 늘었다. "
            "브라질 돼지고기 수출량은 아시아 수요 확대로 8% 증가했다. "
            "현지 돼지고기 도매가격은 공급 확대 영향으로 전월보다 2% 하락했다."
        ))
        self.assertGreaterEqual(d._relevance(candidate, PORK), 0)

    def test_independent_pork_price_fact_in_chicken_comparison_story_remains_valid(self):
        candidate = chicken_story()
        candidate["body"] += (
            "\n일본 돼지고기 생산량은 사육 마릿수 감소로 전년보다 6% 줄었다. "
            "일본 돼지고기 소매가격은 공급 부족으로 전년보다 9% 상승했다. "
            "일본 돼지고기 수입량은 현지 생산 감소를 보완하기 위해 4% 증가했다."
        )
        self.assertGreaterEqual(d._relevance(candidate, PORK), 0)

    def test_original_selection_does_not_promote_chicken_comparison_to_pork(self):
        chicken = chicken_story()
        pork = pork_story()
        with patch.object(d, "_original_article", side_effect=lambda candidate, _spec: candidate), \
             patch.object(d.source, "_ollama_generate") as model:
            selected = d._choose_original([chicken, pork], PORK, START, END)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["url"], pork["url"])
        self.assertNotIn(chicken["url"], [item["url"] for item in selected["alternatives"]])
        model.assert_not_called()

    def test_displayed_candidate_links_apply_the_same_pork_focus_gate(self):
        main = pork_story("main")
        chicken = chicken_story()
        valid = article("independent-trade", "브라질 돼지고기 수출 증가", (
            "브라질 돼지고기 수출량은 아시아 수요 회복으로 전년보다 8% 증가했다. "
            "현지 양돈업계는 돼지고기 수출 시장 확대에 맞춰 생산과 출하 물량을 조정했다."
        ))
        main["alternatives"] = [chicken, valid]
        with patch.object(d, "_search_article") as search, \
             patch.object(d.source, "_ollama_generate") as model:
            links = d._candidate_links(main, PORK, START, END, search_missing=False)
        self.assertEqual([item["url"] for item in links], [valid["url"]])
        self.assertEqual([item["url"] for item in main["_candidateLinkOriginals"]], [valid["url"]])
        search.assert_not_called()
        model.assert_not_called()

    def test_summary_recovery_revalidates_shared_and_existing_originals(self):
        main = pork_story("main")
        chicken = chicken_story()
        egg = article("egg-finance", "브라질산 계란 수입단가 논란, 돼지고기 개방 약속도", EGG_FINANCE)
        valid = article("valid", "CPTPP 가입 논의와 해외 축산물 교역 변화", CPTPP)
        main["alternatives"] = [chicken, egg]
        with patch.object(d.source, "_ollama_generate") as model:
            alternatives = d._verified_summary_alternatives(main, PORK, START, END, [chicken, egg, valid])
        self.assertEqual([item["url"] for item in alternatives], [valid["url"]])
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
