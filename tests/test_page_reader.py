import unittest
from unittest.mock import patch,Mock
from gtm.page_reader import fetch_page
class PageReaderTests(unittest.TestCase):
 def test_static_content_avoids_browser(self):
  with patch('gtm.providers.public_target'),patch('gtm.providers.fetch_website',return_value={'url':'https://example.com','text':'Useful content '*30}):
   slot=Mock();self.assertEqual('http',fetch_page('https://example.com',acquire_browser=slot)['reader']);slot.assert_not_called()
 def test_explicit_browser_respects_budget(self):
  with patch('gtm.providers.public_target'):
   slot=Mock(side_effect=ValueError('budget exhausted'))
   self.assertRaisesRegex(ValueError,'budget',fetch_page,'https://example.com',render=True,acquire_browser=slot)
 def test_private_target_rejected_before_any_fetch(self):
  with patch('gtm.providers.public_target',side_effect=ValueError('Private target')),patch('gtm.providers.fetch_website') as fetch:
   self.assertRaisesRegex(ValueError,'Private',fetch_page,'http://127.0.0.1');fetch.assert_not_called()

 def test_thin_content_uses_local_browser(self):
  with patch('gtm.providers.public_target'),patch('gtm.providers.fetch_website',return_value={'url':'https://example.com','text':'Enable JavaScript'}),patch('gtm.headless_reader.read_page',return_value={'url':'https://example.com','text':'Rendered review text','links':[]}) as browser:
   slot=Mock();result=fetch_page('https://example.com',acquire_browser=slot)
   self.assertEqual('playwright',result['reader']);slot.assert_called_once();browser.assert_called_once()
 def test_explicit_review_interaction_is_passed_to_local_reader(self):
  with patch('gtm.providers.public_target'),patch('gtm.headless_reader.read_page',return_value={'url':'https://example.com','text':'Public reviews','links':[]}) as browser,patch('gtm.providers.fetch_website') as plain:
   fetch_page('https://example.com',render=True,interaction='reviews')
   browser.assert_called_once_with('https://example.com',interaction='reviews');plain.assert_not_called()
 def test_browser_failure_preserves_limited_http_source_without_fabrication(self):
  with patch('gtm.providers.public_target'),patch('gtm.providers.fetch_website',return_value={'url':'https://example.com','text':'Thin content'}),patch('gtm.headless_reader.read_page',side_effect=ValueError('Unavailable')):
   result=fetch_page('https://example.com');self.assertEqual('Thin content',result['text']);self.assertTrue(result['limited_content']);self.assertIn('browser_failure',result)
