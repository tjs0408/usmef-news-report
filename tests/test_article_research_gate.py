import unittest

from src import livestock_article_draft as d


class ArticleResearchGateTests(unittest.TestCase):
    def test_broiler_colonization_presentation_is_not_a_market_article(self):
        article = {
            "title": "AAAP: Salmonella across broiler-production stages",
            "body": (
                "Excerpts from presentations during the annual meeting of the American Association "
                "of Avian Pathologists. University of Georgia, USA, researchers found almost 20% "
                "of salmonellosis cases linked to contaminated chicken consumption. Salmonella "
                "prevalence is lower in breeders; there is a need to understand how broiler "
                "flocks become colonized."
            ),
        }
        self.assertLess(d._relevance(article, d.SPECS_BY_KEY["us_chicken"]), 0)

    def test_salmonella_recall_with_export_effect_remains_a_candidate(self):
        article = {
            "title": "US chicken exports suspended after Salmonella recall",
            "body": (
                "US chicken exports face a temporary suspension following a Salmonella recall. "
                "Researchers at a laboratory identified the pathogen. Supplies available to "
                "importers will fall while the recall is completed."
            ),
        }
        self.assertGreaterEqual(d._relevance(article, d.SPECS_BY_KEY["us_chicken"]), 0)

    def test_cage_free_law_headline_requires_actual_egg_market_body(self):
        article = {
            "title": "Trump administration's challenge to Michigan cage-free law dismissed",
            "body": (
                "A U.S. federal judge dismissed an attempt to eliminate Michigan's cage-free egg law. "
                "Egg producers prepared for the law. Egg prices have come down after a nationwide "
                "bird flu outbreak and production remains cage-free."
            ),
        }
        self.assertGreaterEqual(d._relevance(article, d.SPECS_BY_KEY['us_egg'], trusted_country=True), 0)
        self.assertLess(d._relevance({**article, 'body': 'US chicken production practices are discussed.'},
                                    d.SPECS_BY_KEY['us_egg'], trusted_country=True), 0)


if __name__ == "__main__":
    unittest.main()
