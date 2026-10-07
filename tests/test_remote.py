import base64, json, os
from unittest.mock import patch
import test_http

class RemoteTests(test_http.HTTPBoundaryTests):
    def test_remote_reads_require_password(self):
        with patch.dict(os.environ,{'GTM_PUBLIC_ORIGIN':'https://gtm.example.test','GTM_REMOTE_PASSWORD':'a'*40}):
            self.assertEqual(401,self.request()[0])
            auth='Basic '+base64.b64encode(('continere:'+'a'*40).encode()).decode()
            self.assertEqual(200,self.request(headers={'Host':'gtm.example.test','Authorization':auth})[0])
            h={'Host':'gtm.example.test','Authorization':auth,'Origin':'https://gtm.example.test','X-CSRF-Token':__import__('gtm.server',fromlist=['TOKEN']).TOKEN,'Content-Type':'application/json'}
            with patch('gtm.playbook.create',return_value='pid') as create:
                self.assertEqual(200,self.request('/api/playbook/create','POST',h,json.dumps({'business':'x'}))[0]);create.assert_called_once()
            h['Origin']='https://attacker.test'
            self.assertEqual(403,self.request('/api/playbook/create','POST',h,'{}')[0])
