import copy,json,os,uuid,unittest
from unittest.mock import patch
import test_playbook_campaigns as fixture
from gtm.research_tools import ResearchSession,DiscoverySession
from gtm import db,playbook_campaigns as pc
from scripts.maps_mcp import Maps
class ResearchToolTests(unittest.TestCase):
 def tearDown(self):fixture.CampaignStrategyTests.tearDown(self)
 def setUp(self):
  fixture.CampaignStrategyTests.setUp(self);self.rid=uuid.uuid4().hex;self.cid=uuid.uuid4().hex
  with db.connect() as c:
   c.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',(self.rid,json.dumps(self.s),'awaiting_review',None,db.now()))
   c.execute('INSERT INTO playbook_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(self.cid,self.rid,'p1','needs_verification',json.dumps(self.place),json.dumps(self.research),'{}','{}',None,db.now()))
  self.session=ResearchSession(copy.deepcopy(self.research),self.s,self.cid)
 def test_apollo_tool_scope_and_budget(self):
  class Registry:
   def __init__(self):self.handlers={}
   def register(self,**kw):self.handlers[kw['name']]=kw['handler']
  reg=Registry();self.session.root_task_id='root';self.session.task_roles={'contact':'contact_search','qa':'qa'};self.session.register(reg)
  with patch('gtm.apollo.search',return_value={'contacts':[]}) as search:
   tool=reg.handlers['continere_apollo_contacts']
   self.assertIn('error',json.loads(tool({},task_id='qa')));search.assert_not_called()
   self.assertNotIn('error',json.loads(tool({},task_id='contact')))
   self.assertNotIn('error',json.loads(tool({},task_id='root')))
   self.assertIn('error',json.loads(tool({},task_id='contact')));self.assertEqual(2,search.call_count)
   self.assertEqual(self.research['website'],search.call_args.args[0])
 def test_cross_business_page_blocked(self):
  with patch('gtm.providers.fetch_website') as fetch:
   self.assertRaises(ValueError,self.session.read_page,'https://other.test/team');fetch.assert_not_called()
 def test_page_source_attached_and_budget_bounded(self):
  with patch('gtm.page_reader.fetch_page',return_value={'url':'https://example.test/team','text':'Our practice has three dietitians serving Austin.','links':[]}):
   result=self.session.read_page('https://example.test/team');self.assertEqual('e2',result['evidence'][0]['id'])
   self.session.pages=6;self.assertRaisesRegex(ValueError,'budget',self.session.read_page,'https://example.test/team')
  self.assertTrue(pc.snapshot()['candidates'][0]['agent_activity'])
 def test_validated_save_cannot_approve_contact(self):
  result=self.session.save(copy.deepcopy(self.value));self.assertTrue(result['no_approval']);self.assertTrue(result['no_contact'])
  c=pc.snapshot()['candidates'][0];self.assertEqual('needs_verification',c['stage']);self.assertFalse(c['facts']['qualification_verified'])
  with db.connect() as c:self.assertEqual(0,c.execute('SELECT count(*) FROM manual_contacts').fetchone()[0])
 def test_forged_evidence_cannot_save(self):
  v=copy.deepcopy(self.value);v['fact_evidence']['rdn_count'][0]['quote']='twenty dietitians'
  self.assertRaises(ValueError,self.session.save,v);self.assertFalse(self.session.saved)
 def test_specialist_cannot_save(self):
  class Registry:
   def __init__(self):self.handlers={}
   def register(self,**kw):self.handlers[kw['name']]=kw['handler']
  registry=Registry();self.session.root_task_id='root';self.session.register(registry)
  out=json.loads(registry.handlers['continere_save_findings']({'result':self.value},task_id='child'));self.assertIn('Only the root',out['error'])
 def test_maps_missing_key_cannot_call_provider(self):
  with patch.dict(os.environ,{'GOOGLE_PLACES_API_KEY':''}),patch('gtm.providers.discover') as fetch:
   self.assertTrue(Maps(self.s).call('search_businesses',{'search_term':'dietitian'})['unavailable']);fetch.assert_not_called()
 def test_maps_search_terms_and_session_scope_enforced(self):
  with patch.dict(os.environ,{'GOOGLE_PLACES_API_KEY':'test'}),patch('gtm.providers.discover') as fetch:
   maps=Maps(self.s);self.assertRaises(ValueError,maps.call,'search_businesses',{'search_term':'invented'})
   self.assertRaises(ValueError,maps.call,'place_details',{'place_id':'invented'});fetch.assert_not_called()
 def test_discovery_rejects_invented_place_and_duplicate(self):
  session=DiscoverySession(self.s,self.rid);self.assertRaises(ValueError,session.select,'invented')
  session.capture(json.dumps({'result':json.dumps({'places':[self.place]})}));self.assertTrue(session.select('p1')['duplicate'])
 def test_discovery_saves_one_real_candidate_without_qualification(self):
  session=DiscoverySession(self.s,self.rid);p=dict(self.place,place_id='p2',website='https://another-practice.test')
  session.capture(json.dumps({'result':json.dumps({'places':[p]})}));self.assertTrue(session.select('p2')['no_contact'])
  with db.connect() as c:self.assertEqual('queued',c.execute('SELECT stage FROM playbook_candidates WHERE place_id=?',('p2',)).fetchone()[0])
