import copy,json,uuid,unittest
import test_playbook_campaigns as fixture
from gtm import db
from gtm.research_tools import DiscoverySession

class DiscoveryPoolTests(unittest.TestCase):
 def setUp(self):
  fixture.CampaignStrategyTests.setUp(self)
  self.rid=uuid.uuid4().hex
  with db.connect() as c:c.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',(self.rid,json.dumps(self.s),'running',None,db.now()))
 def tearDown(self):fixture.CampaignStrategyTests.tearDown(self)
 def places(self,n):
  return [dict(self.place,place_id='pool'+str(i),name='Practice '+str(i),website='https://practice'+str(i)+'.test') for i in range(n)]
 def session(self,limit):return DiscoverySession(dict(self.s,limit=limit),self.rid)
 def test_one_candidate_compatibility(self):
  s=self.session(1);s.capture({'places':self.places(3)});s.complete_pool()
  self.assertEqual(1,len(s.selected_places));self.assertEqual(s.selected,s.selected_places[0])
  self.assertTrue(s.select('pool1')['budget_reached'])
 def test_multiple_source_candidates_queued_without_contact(self):
  s=self.session(6);s.capture(json.dumps({'result':json.dumps({'places':self.places(8)})}));s.complete_pool()
  self.assertEqual(6,len(s.selected_places))
  with db.connect() as c:
   self.assertEqual(6,c.execute("SELECT count(*) FROM playbook_candidates WHERE stage='queued'").fetchone()[0])
   self.assertEqual(0,c.execute('SELECT count(*) FROM manual_contacts').fetchone()[0])
 def test_duplicate_ids_domains_and_existing_records_blocked(self):
  s=self.session(6);rows=self.places(3);rows.append(dict(rows[0],place_id='alternate'))
  s.capture({'places':rows});s.complete_pool();self.assertEqual(3,len(s.selected_places))
  self.assertTrue(s.select('pool0')['duplicate'])
  second=self.session(6);second.capture({'places':rows});second.complete_pool();self.assertEqual([],second.selected_places)
 def test_fabrication_blocked(self):
  s=self.session(6);s.capture({'places':self.places(2)})
  with self.assertRaisesRegex(ValueError,'actual business'):s.select('invented')
  self.assertFalse(s.saved)
 def test_partial_source_pool_and_maximum(self):
  s=self.session(100);self.assertEqual(12,s.limit);s.capture({'places':self.places(2)});s.complete_pool();self.assertEqual(2,len(s.selected_places))
 def test_default_pool_target(self):
  campaign=dict(self.s);campaign.pop('limit');self.assertEqual(6,DiscoverySession(campaign,self.rid).limit)
 def test_captured_identity_is_not_replaced_or_mutated(self):
  s=self.session(6);p=self.places(1)[0];s.capture({'places':[p]});p['name']='Changed outside session'
  s.capture({'places':[dict(p,name='Later conflicting identity')]})
  self.assertEqual('Practice 0',s.places['pool0']['name'])
 def test_malformed_search_record_not_queued(self):
  s=self.session(6);s.capture({'places':[{'place_id':'fake'},dict(self.place,place_id='')]})
  self.assertEqual({},s.places);self.assertEqual([],s.complete_pool())
 def test_only_actual_root_can_select(self):
  class Registry:
   def __init__(self):self.handlers={}
   def register(self,**kw):self.handlers[kw['name']]=kw['handler']
  s=self.session(6);s.root_task_id='trusted-root';s.capture({'places':self.places(1)})
  registry=Registry();s.register(registry)
  denied=json.loads(registry.handlers['continere_select_prospect']({'place_id':'pool0'},task_id='child'))
  self.assertIn('only it selects',denied['error']);self.assertFalse(s.saved)
  allowed=json.loads(registry.handlers['continere_select_prospect']({'place_id':'pool0'},task_id='trusted-root'))
  self.assertTrue(allowed['saved'])
 def test_editorial_capture_cannot_backfill_pool(self):
  s=self.session(6);p=self.places(1)[0]
  s.capture({'places':[dict(p,place_id='editorial',name='10 Incredible Luxury Spa Resorts In Florida',website='https://floridatrippers.com/best-spa-resorts-in-florida/'),p]})
  s.complete_pool();self.assertEqual(['pool0'],[p['place_id'] for p in s.selected_places])
 def test_google_places_business_without_website_retained(self):
  s=self.session(6);p=dict(self.place,place_id='actual-google-id',website='',source='https://maps.google.com/actual-business')
  s.capture({'places':[p]});s.complete_pool();self.assertEqual(1,len(s.selected_places))
