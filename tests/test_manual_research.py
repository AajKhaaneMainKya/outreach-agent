import copy,json,os,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from gtm import db,playbook,playbook_campaigns as c
class ManualResearchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.data=patch('gtm.db.DATA',Path(self.tmp.name));self.data.start();db.init();playbook.init();c.init()
  self.input={'source':'manual','icp':'dietitian','city':'Austin','sender':'Operator','timezone':'America/Chicago','limit':1,'business':'Example Practice','website':'https://example.test','gmb_url':'https://maps.google.com/example','gmb_phone':'','review_count':None,'reviews':[]}
 def tearDown(self):self.data.stop();self.tmp.cleanup()
 def test_no_google_calls_and_unknown_contacts_stay_unknown(self):
  s=c.settings(self.input)
  with patch('gtm.providers.discover',side_effect=AssertionError('No paid discovery')),patch('gtm.providers.api_json',side_effect=AssertionError('No Google request')),patch('gtm.providers.fetch_website',return_value={'url':'https://example.test','text':'Our practice has three registered dietitians.','links':[]}):
   places=c.discover(s);research=c.retrieve(places[0])
  self.assertIsNone(research['place_details']['userRatingCount']);self.assertEqual([],research['reviews']);self.assertTrue(research['evidence'])
  f=c.prefill(research,{'facts':{}},s);self.assertFalse(f['gmb_number_verified']);self.assertFalse(f['hook_verified']);self.assertEqual('',f['line_type'])
 def test_manual_start_bypasses_places_requirement(self):
  with patch.dict(os.environ,{'GOOGLE_PLACES_API_KEY':'','HERMES_MODEL':'gpt-6-luna'}),patch('gtm.account.status',return_value={'logged_in':True}),patch('gtm.playbook_campaigns.threading.Thread') as thread:
   rid=c.start(self.input);self.assertTrue(rid);thread.return_value.start.assert_called_once()
 def test_reviews_are_untrusted_and_require_real_source(self):
  invalid=dict(self.input,gmb_url='https://attacker.example/maps');self.assertRaises(ValueError,c.settings,invalid)
  invalid=dict(self.input,reviews=[{'stars':6,'text':'x'}]);self.assertRaises(ValueError,c.settings,invalid)
 def test_manual_retry_does_not_require_places(self):
  rid=uuid.uuid4().hex;s=c.settings(self.input)
  with db.connect() as d:d.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',(rid,json.dumps(s),'failed',None,db.now()))
  with patch.dict(os.environ,{'GOOGLE_PLACES_API_KEY':'','HERMES_MODEL':'gpt-6-luna'}),patch('gtm.account.status',return_value={'logged_in':True}),patch('gtm.playbook_campaigns.threading.Thread') as thread:
   c.advance(rid);thread.return_value.start.assert_called_once()

 def test_missing_gmb_can_be_researched_but_never_marked_verified(self):
  s=c.settings(dict(self.input,gmb_url=''))
  with patch('gtm.providers.fetch_website',return_value={'url':'https://example.test','text':'A source-backed practice description.','links':[]}):research=c.retrieve(c.discover(s)[0])
  f=c.prefill(research,{'facts':{}},s)
  self.assertEqual('',f['gmb_url']);self.assertFalse(f['gmb_number_verified']);self.assertFalse(f['qualification_verified'])
 def test_entered_reviews_and_business_details_carry_into_result(self):
  pasted={'stars':5,'text':'Jamie was kind and listened carefully.','date':'2026-09-01'}
  s=c.settings(dict(self.input,gmb_phone='+15125551234',review_count=209,reviews=[pasted]))
  with patch('gtm.providers.fetch_website',return_value={'url':'https://example.test','text':'A source-backed practice description.','links':[]}):research=c.retrieve(c.discover(s)[0])
  f=c.prefill(research,{'facts':{}},s)
  self.assertEqual('Example Practice',f['business']);self.assertEqual('+15125551234',f['gmb_phone']);self.assertEqual(209,f['reviews']);self.assertEqual(pasted['text'],f['newest_reviews'][0]['text']);self.assertEqual(self.input['gmb_url'],f['newest_reviews'][0]['source'])

 def test_skipping_last_candidate_finishes_run_without_losing_research(self):
  rid=uuid.uuid4().hex;cid=uuid.uuid4().hex;s=c.settings(self.input)
  with db.connect() as d:
   d.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',(rid,json.dumps(s),'awaiting_review',None,db.now()))
   d.execute('INSERT INTO playbook_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,rid,'p1','needs_verification','{}',json.dumps({'evidence':['preserved']}),'{}','{}',None,db.now()))
  c.park(cid)
  with db.connect() as d:
   self.assertEqual('complete',d.execute('SELECT stage FROM playbook_runs WHERE id=?',(rid,)).fetchone()['stage'])
   self.assertIn('preserved',d.execute('SELECT research FROM playbook_candidates WHERE id=?',(cid,)).fetchone()['research'])

 def test_duplicate_submission_preserves_existing_record_and_does_not_start(self):
  rid=uuid.uuid4().hex;cid=uuid.uuid4().hex;s=c.settings(self.input);place=c.discover(s)[0]
  with db.connect() as d:
   d.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',(rid,json.dumps(s),'complete',None,db.now()))
   d.execute('INSERT INTO playbook_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,rid,place['place_id'],'parked',json.dumps(place),'{}','{}','{}',None,db.now()))
  with patch.dict(os.environ,{'GOOGLE_PLACES_API_KEY':'','HERMES_MODEL':'gpt-6-luna'}),patch('gtm.account.status',return_value={'logged_in':True}),patch('gtm.playbook_campaigns.threading.Thread') as thread:
   self.assertRaisesRegex(ValueError,'already saved',c.start,self.input);thread.assert_not_called()
  with db.connect() as d:self.assertEqual(1,d.execute('SELECT count(*) FROM playbook_runs').fetchone()[0])
