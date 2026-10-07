import json,unittest
from unittest.mock import patch
import test_research_tools as fixture
from gtm.research_tools import message,board_rows
from gtm import db,playbook,playbook_campaigns as pc
class AgentBoardTests(fixture.ResearchToolTests):
 def test_board_citations_must_exist(self):
  self.assertRaises(ValueError,message,self.session,'researcher','qualifier','finding','Unsupported',['fake'])
 def test_board_records_author_role_and_source(self):
  message(self.session,'researcher','qualifier','finding','Team evidence',['e1'])
  c=pc.snapshot()['candidates'][0];m=c['agent_board'][0];self.assertEqual('researcher',m['sender']);self.assertEqual('e1',m['evidence'][0]['id'])
 def test_writer_cannot_fetch_new_pages(self):
  class Registry:
   def __init__(self):self.handlers={}
   def register(self,**kw):self.handlers[kw['name']]=kw['handler']
  registry=Registry();self.session.root_task_id='root';self.session.task_roles['writer-id']='writer';self.session.register(registry)
  with patch('gtm.providers.fetch_website') as fetch:
   out=json.loads(registry.handlers['continere_read_business_page']({'url':'https://example.test/team'},task_id='writer-id'));self.assertIn('Only the researcher',out['error']);fetch.assert_not_called()
 def test_no_review_yields_partial_not_sendable(self):
  f=pc.prefill(self.research,self.value,self.s);p=playbook.research_preview(f,self.research,self.value)
  self.assertTrue(p['partial']);self.assertFalse(p['release_allowed']);self.assertIn('[Staff]',p['draft']['text1'])
 def test_web_discovery_does_not_call_places(self):
  place=dict(self.place,discovery_source='duckduckgo')
  with patch.object(pc,'details') as maps,patch('gtm.providers.fetch_website',return_value={'url':place['website'],'text':'Our practice team is here.','links':[]}):
   v=pc.retrieve(place);maps.assert_not_called();self.assertEqual('',v['place_details']['googleMapsUri']);self.assertEqual([],v['reviews']);self.assertIsNone(v['place_details']['userRatingCount'])
 def test_web_settings_need_no_maps_key(self):
  data=dict(self.s,source='web',agent_goal='Find a matching practice')
  s=pc.settings(data);self.assertEqual('web',s['source'])
  with patch.dict('os.environ',{'GOOGLE_PLACES_API_KEY':''}):self.assertNotIn('Google Places key',pc.connections('web')['missing'])

 def test_trusted_direct_mcp_result_capture(self):
  from gtm.research_tools import DiscoverySession
  session=DiscoverySession(self.s,self.rid);p=dict(self.place,place_id='web-result')
  session.capture(json.dumps({'places':[p]}));self.assertIn('web-result',session.places)

 def test_fresh_specialist_qa_required_before_save(self):
  self.session.completed_roles={'researcher','qualifier','writer'}
  self.assertRaisesRegex(ValueError,'qa',self.session.save,self.value);self.assertFalse(self.session.saved)

 def test_agent_can_retract_unsupported_prior_fact(self):
  with db.connect() as c:c.execute('UPDATE playbook_candidates SET analysis=? WHERE id=?',(json.dumps(self.value),self.cid))
  value=dict(self.value);value['facts']=dict(self.value['facts'],cash_pay=None)
  self.session.save(value);self.assertIsNone(pc.snapshot()['candidates'][0]['facts']['cash_pay'])
 def test_specialist_evidence_includes_authoritative_policy(self):
  self.assertIn('money_line',self.session.evidence()['authoritative_policy'])
