import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as server


class ArticleJobDiagnosticsTests(unittest.TestCase):
    def test_failed_job_record_is_inspectable_without_private_runtime_data(self):
        job_id = 'a' * 32
        job = {
            'reportDate': '2026-10-14', 'status': 'completed', 'elapsedSeconds': 623.5,
            'readyCount': 3, '_requestId': 'PRIVATE_REQUEST', 'startedAt': 123,
            'result': {'weekStart': '2026-10-11', 'weekEnd': '2026-10-17'},
            'sections': {'us': {
                'status': 'summary_error', 'summaryError': '한 줄 길이 초과',
                'article': {'title': 'Public news', 'publishedDate': '2026-10-14',
                            'url': 'https://example.org/news', 'sourceExcerpt': 'EXCLUDED_BODY'},
                'diagnostics': {'modelCalls': 2, 'modelSeconds': 40, 'Authorization': 'PRIVATE_HEADER',
                                'validationReasons': [{'length': 62, 'reasons': ['허용 줄 수 초과']}]},
            }},
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(server, 'OUTPUT_DIR', Path(directory)):
            server._save_article_job_diagnostics(job_id, job)
            raw = (Path(directory) / f'article_diagnostics_{job_id}.json').read_text(encoding='utf-8')
        profile = json.loads(raw)
        self.assertEqual(profile['readyCount'], 3)
        self.assertEqual(profile['sections']['us']['diagnostics']['modelCalls'], 2)
        self.assertEqual(profile['weekStart'], '2026-10-11')
        for private in ('PRIVATE_REQUEST', 'PRIVATE_HEADER', 'EXCLUDED_BODY', 'startedAt'):
            self.assertNotIn(private, raw)

    def test_diagnostics_write_failure_never_changes_job_outcome(self):
        with patch.object(Path, 'mkdir', side_effect=OSError('unavailable')):
            server._save_article_job_diagnostics('a' * 32, {'status': 'completed', 'sections': {}})


if __name__ == '__main__':
    unittest.main()
