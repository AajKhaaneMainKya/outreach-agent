import json
import subprocess
import unittest
from unittest.mock import patch
from gtm import headless_reader as reader

class HeadlessReaderTests(unittest.TestCase):
    def test_rejects_private_target_before_spawn(self):
        with patch.object(reader.providers, 'public_target', side_effect=ValueError('Private')), patch.object(reader.subprocess, 'run') as run:
            with self.assertRaises(ValueError): reader.read_page('http://127.0.0.1')
            run.assert_not_called()

    def test_rejects_arbitrary_interaction(self):
        with self.assertRaises(ValueError): reader.read_page('https://example.com', interaction='submit')

    def test_structured_bridge(self):
        payload={'url':'https://example.com', 'text':'Public content','links':[], 'metadata':{'reader':'playwright-chromium'}}
        with patch.object(reader.providers,'public_target'), patch.object(reader.Path,'exists',return_value=True), patch.object(reader,'_invoke',return_value=subprocess.CompletedProcess([],0,json.dumps(payload),'')) as run:
            self.assertEqual(reader.read_page(payload['url']),payload)
            self.assertEqual(run.call_args.kwargs['timeout'],38)

    def test_bridge_timeout(self):
        with patch.object(reader.providers,'public_target'), patch.object(reader.Path,'exists',return_value=True), patch.object(reader,'_invoke',side_effect=subprocess.TimeoutExpired([],38)):
            with self.assertRaisesRegex(ValueError,'time budget'): reader.read_page('https://example.com')

    def test_request_pins_public_ip(self):
        with patch.object(reader.providers,'public_target',return_value=(__import__('urllib.parse',fromlist=['urlsplit']).urlsplit('https://example.com'),443,'93.184.216.34')), patch.object(reader.providers,'PinnedHTTPS') as connection:
            response=connection.return_value.getresponse.return_value
            response.status=200
            response.read.return_value=b'ok'
            response.getheaders.return_value=[('Content-Type','text/html'),('Set-Cookie','secret')]
            status,headers,body=reader._request('https://example.com')
            connection.assert_called_once_with('example.com',443,'93.184.216.34')
            self.assertNotIn('set-cookie',headers)
            self.assertEqual(body,b'ok')
