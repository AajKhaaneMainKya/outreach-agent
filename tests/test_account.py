import json,unittest
from unittest.mock import patch
from types import SimpleNamespace
from gtm import account
class AccountTests(unittest.TestCase):
 def setUp(self):account._cached=None
 def test_secrets_are_never_returned(self):
  with patch('gtm.account.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps({'logged_in':True,'auth_mode':'chatgpt','api_key':'SECRET','access_token':'SECRET'}))):
   result=account.status()
  self.assertTrue(result['logged_in']);self.assertEqual('openai-codex',result['provider']);self.assertNotIn('SECRET',json.dumps(result))
 def test_unavailable_account_fails_closed(self):
  with patch('gtm.account.subprocess.run',side_effect=TimeoutError):self.assertFalse(account.status()['logged_in'])
