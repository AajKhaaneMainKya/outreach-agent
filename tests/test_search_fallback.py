import unittest
from unittest.mock import Mock
from gtm.web_discovery import _search_backends, SEARCH_BACKENDS

class SearchFallbackTests(unittest.TestCase):
    def run_search(self, outcomes):
        factory = Mock()
        factory.return_value.text.side_effect = outcomes
        return factory

    def test_first_success_does_not_search_other_engines(self):
        factory = self.run_search([[{'href': 'https://example.com', 'body': 'lead'}]])
        rows = _search_backends(factory, 'day spa in Austin', 10)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(rows[0]['search_backend'], 'duckduckgo')
        self.assertEqual(rows[0]['search_attempts'], [{'backend':'duckduckgo','outcome':'results'}])

    def test_failure_and_empty_trigger_bounded_fallbacks(self):
        factory = self.run_search([RuntimeError('blocked'), [], [{'href':'https://example.com'}]])
        rows = _search_backends(factory, 'query', 10)
        self.assertEqual(rows[0]['search_backend'], 'mojeek')
        self.assertEqual([c.kwargs['backend'] for c in factory.return_value.text.call_args_list], list(SEARCH_BACKENDS))
        self.assertEqual([a['outcome'] for a in rows[0]['search_attempts']], ['unavailable','empty','results'])

    def test_all_empty_returns_empty(self):
        factory = self.run_search([[], [], []])
        self.assertEqual(_search_backends(factory, 'query', 10), [])
        self.assertEqual(factory.call_count, 3)

    def test_all_failed_reports_unavailable(self):
        factory = self.run_search([RuntimeError('blocked')]*3)
        with self.assertRaisesRegex(ValueError, 'no prospects invented'):
            _search_backends(factory, 'query', 10)
        self.assertEqual(factory.call_count, 3)

    def test_invalid_rows_trigger_fallback(self):
        factory = self.run_search([[None, {'title':'missing URL'}], [{'href':'https://example.com'}]])
        rows = _search_backends(factory, 'query', 10)
        self.assertEqual(rows[0]['search_backend'], 'brave')
