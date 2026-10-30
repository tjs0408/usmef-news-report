from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import article_source_text_cache as cache


class ArticleSourceTextCacheTests(unittest.TestCase):
    def test_only_identical_pdf_bytes_and_extractor_version_reuse_source_text(self):
        document = b'%PDF-1.7 public-original'
        texts = {'beef': '미국 쇠고기 공급과 가격 변화를 기록한 원문. ' * 12,
                 'pork': '미국 돼지고기 생산과 수요를 확인한 원문. ' * 12}
        with tempfile.TemporaryDirectory() as directory, patch.object(cache, 'CACHE_DIR', Path(directory)):
            cache.save_source_text(document, texts)
            self.assertEqual(cache.load_source_text(document), texts)
            self.assertIsNone(cache.load_source_text(document + b' corrected'))
            with patch.object(cache, 'EXTRACTOR_VERSION', 'new-extractor'):
                self.assertIsNone(cache.load_source_text(document))
            stored = next(Path(directory).glob('*.json')).read_text(encoding='utf-8')
            self.assertNotIn('summary', stored)
            self.assertNotIn('reportDate', stored)

    def test_corrupt_missing_or_non_pdf_source_cannot_supply_evidence(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cache, 'CACHE_DIR', Path(directory)):
            self.assertIsNone(cache.load_source_text(b'%PDF-1.7 missing'))
            cache.save_source_text(b'HTML challenge', {'beef': 'x' * 150})
            cache.save_source_text(b'%PDF-1.7 invalid text', {'egg': 'x' * 150})
            cache.save_source_text(b'%PDF-1.7 missing pork', {'beef': 'x' * 150})
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
