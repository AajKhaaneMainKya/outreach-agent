import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from gtm.server import Handler, TOKEN

class HTTPBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.port=cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def request(self,path='/',method='GET',headers=None,body=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port)
        conn.request(method,path,body=body,headers=headers or {})
        result=conn.getresponse();status=result.status;data=result.read();h=dict(result.getheaders());conn.close()
        return status,data,h

    def test_dashboard_assets_and_security_headers(self):
        status,body,headers=self.request()
        self.assertEqual(200,status)
        self.assertIn(b'Outreach agent',body)
        self.assertIn(b'Created By Rahul',body)
        self.assertNotIn(b'__CSRF_TOKEN__',body)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertEqual('no-store',headers['Cache-Control'])

    def test_dns_rebinding_host_is_rejected(self):
        status,_,_=self.request(headers={'Host':f'attacker.test:{self.port}'})
        self.assertEqual(403,status)

    def test_cross_origin_or_missing_token_cannot_write(self):
        for headers in ({},{'Origin':'https://attacker.test','X-CSRF-Token':TOKEN}, {'Origin':f'http://127.0.0.1:{self.port}'}):
            with patch('gtm.service.start_run') as run:
                status,_,_=self.request('/api/run','POST',headers,json.dumps({'mode':'live'}))
                self.assertEqual(403,status);run.assert_not_called()

    def test_only_allowlisted_static_assets_are_served(self):
        for path in ('/.env','/data/campaign.sqlite3','/../config/strategy.json'):
            self.assertEqual(404,self.request(path)[0])

    def test_same_origin_token_dispatches_requested_demo_action(self):
        headers={'Origin':f'http://127.0.0.1:{self.port}','X-CSRF-Token':TOKEN,'Content-Type':'application/json'}
        with patch('gtm.service.start_run',return_value='test-run') as run:
            status,body,_=self.request('/api/run','POST',headers,json.dumps({'mode':'demo'}))
            self.assertEqual(200,status);run.assert_called_once_with('demo')
            self.assertEqual('test-run',json.loads(body)['run_id'])

    def test_default_workspace_uses_loaded_vj_playbook(self):
        status,body,_=self.request('/')
        self.assertEqual(200,status)
        self.assertIn(b'id="module-select"',body)
        for module in (b'spa',b'dietitian',b'rehab'):self.assertIn(b'value="'+module+b'"',body)
        status,fragment,_=self.request('/playbook-fragment.html')
        self.assertEqual(200,status)
        self.assertIn(b'Strategy loaded',fragment)
        status,body,_=self.request('/rehab')
        self.assertEqual(200,status)
        self.assertIn(b'id="module-select"',body)

    def test_mission_dispatches_prompt_geography_without_saved_city(self):
        headers={'Origin':f'http://127.0.0.1:{self.port}','X-CSRF-Token':TOKEN,'Content-Type':'application/json'}
        from contextlib import contextmanager
        class EmptyDB:
            def execute(self,*a):return self
            def fetchall(self):return []
        @contextmanager
        def fake_db():yield EmptyDB()
        with patch('gtm.server.db.connect',fake_db),patch('gtm.playbook_campaigns.start',return_value='mission-run') as run:
            status,body,_=self.request('/api/playbook/mission','POST',headers,json.dumps({'goal':'Find spas in Seattle and draft outreach','icp':'spa','sender':'Rahul'}))
            self.assertEqual(200,status);self.assertEqual('Seattle',run.call_args.args[0]['city']);self.assertEqual('',run.call_args.args[0]['timezone'])
            self.assertEqual('discover',json.loads(body)['action'])
