import json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from gtm import db,playbook,playbook_campaigns as pc
from gtm.research_tools import ResearchSession,board_rows
class MissingEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=patch('gtm.db.DATA',Path(self.tmp.name));self.p.start();db.init();playbook.init();pc.init()
  self.cid=uuid.uuid4().hex;self.rid=uuid.uuid4().hex
  self.research={'website':'https://example.com','place_details':{'displayName':{'text':'Example Spa'}},'evidence':[],'reviews':[]}
  self.campaign={'icp':'spa','city':'New York','sender':'Rahul'}
  with db.connect() as c:
   c.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',(self.rid,json.dumps(self.campaign),'running',None,db.now()))
   c.execute('INSERT INTO playbook_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(self.cid,self.rid,'place','researching','{}',json.dumps(self.research),'{}','{}',None,db.now()))
  self.session=ResearchSession(self.research,self.campaign,self.cid);self.session.root_task_id='mission'
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def test_targeted_queries_budget_and_messages(self):
  with patch('gtm.web_discovery.search',return_value=[{'href':'https://example.com/reviews','body':'Unverified review snippet'}]) as search,patch('gtm.providers.public_target'):
   for purpose in ('review','qualification','contact'):self.session.search_missing(purpose)
   self.assertEqual(3,search.call_count)
   self.assertTrue(all('Example Spa New York' in c.args[0] for c in search.call_args_list))
   self.assertRaisesRegex(ValueError,'already attempted',self.session.search_missing,'review')
  self.assertEqual([],self.research['reviews']);self.assertTrue(all(e['kind']=='search_lead' for e in self.research['evidence']))
  with db.connect() as c:messages=board_rows(c,self.cid)
  self.assertEqual(6,len(messages));self.assertEqual(0,len([m for m in messages if m.get('no_contact') is False]))
 def test_unavailable_search_records_blocker_without_fabrication(self):
  with patch('gtm.web_discovery.search',side_effect=ValueError('Unavailable')):self.assertTrue(self.session.search_missing('review')['unavailable'])
  self.assertEqual([],self.research['evidence']);self.assertIn('review',self.session.search_attempts)
 def test_source_fetch_requires_returned_url_and_shared_page_budget(self):
  self.assertRaisesRegex(ValueError,'returned',self.session.read_search_page,'https://example.com/unknown')
  self.session.search_urls.add('https://example.com/reviews');self.session.pages=6
  self.assertRaisesRegex(ValueError,'six-page',self.session.read_search_page,'https://example.com/reviews')
 def test_save_requires_attempts_after_specialist_findings(self):
  self.session.completed_roles={'researcher','qualifier','writer','qa'}
  self.assertRaisesRegex(ValueError,'Try missing evidence searches',self.session.save,{})

 def test_browser_reads_share_a_two_read_budget(self):
  self.session.browser_slot();self.session.browser_slot()
  self.assertRaisesRegex(ValueError,'Two-browser',self.session.browser_slot)
