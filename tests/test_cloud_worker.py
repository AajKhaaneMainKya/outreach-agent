import importlib.util,json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('cloud_worker',Path(__file__).resolve().parents[1]/'scripts/cloud_worker.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
class CloudWorkerTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE cloud_jobs(id TEXT PRIMARY KEY,stage TEXT,status INTEGER,result TEXT)');self.job={'id':'test-job','path':'/api/playbook/research','data':{}}
 def tearDown(self):
  self.db.close()
 def test_cloud_send_never_allowed(self):
  self.assertFalse(w.allowed('/api/prospect/'+'a'*32+'/send'));self.assertTrue(w.allowed('/api/playbook/'+'a'*32+'/approve'))
 def test_interrupted_job_not_executed(self):
  self.db.execute('INSERT INTO cloud_jobs(id,stage) VALUES (?,?)',('test-job','running'));self.db.commit()
  with patch.object(w,'execute') as execute,patch.object(w,'cloud') as cloud:
   w.process(self.job,self.db,{},lambda **kw:None);execute.assert_not_called();self.assertEqual(cloud.call_args.args[1]['stage'],'needs_review')
 def test_completed_job_receipt_only(self):
  self.db.execute('INSERT INTO cloud_jobs VALUES (?,?,?,?)',('test-job','complete',200,json.dumps({'ok':True})));self.db.commit()
  with patch.object(w,'execute') as execute,patch.object(w,'cloud') as cloud:
   w.process(self.job,self.db,{},lambda **kw:None);execute.assert_not_called();self.assertEqual(cloud.call_args.args[1]['result'],{'ok':True})
 def test_response_interrupt_not_retried(self):
  with patch.object(w,'execute',side_effect=TimeoutError) as execute,patch.object(w,'cloud') as cloud:
   w.process(self.job,self.db,{},lambda **kw:None);self.assertEqual(execute.call_count,1);self.assertEqual(cloud.call_args.args[1]['stage'],'needs_review')
 def test_receipt_retry_does_not_execute_action(self):
  self.db.execute('INSERT INTO cloud_jobs VALUES (?,?,?,?)',('test-job','complete',200,json.dumps({'ok':True})));self.db.commit()
  with patch.object(w,'execute') as execute,patch.object(w,'cloud'):
   w.acknowledge_results(self.db,{});execute.assert_not_called();self.assertEqual(self.db.execute('SELECT stage FROM cloud_jobs').fetchone()[0],'acknowledged')
 def test_email_replies_removed_from_cloud_snapshot(self):
  payloads=[{'replies':[{'text':'private email body'}],'integrations':{'send_enabled':True}},{},{},{},{}]
  class R:
   def __init__(self,data):self.data=json.dumps(data).encode();self.i=0
   def read(self,n=-1):v=self.data[self.i:] if n<0 else self.data[self.i:self.i+n];self.i+=len(v);return v
   def __enter__(self):return self
   def __exit__(self,*args):pass
  with patch.object(w.urllib.request,'urlopen',side_effect=[R(x) for x in payloads]):
   s=w.snapshots();self.assertEqual(s['/api/state']['replies'],[]);self.assertFalse(s['/api/state']['integrations']['send_enabled'])
