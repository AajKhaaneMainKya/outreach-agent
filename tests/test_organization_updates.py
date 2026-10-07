import unittest
import test_research_tools as fixtures
from gtm.research_tools import ResearchSession,message,organization_updates
from gtm import db
class OrgTests(unittest.TestCase):
 setUp=fixtures.ResearchToolTests.setUp
 tearDown=fixtures.ResearchToolTests.tearDown
 def test_same_campaign_only_and_keeps_identity(self):
  self.session.root_task_id='first'
  message(self.session,'researcher','all','finding','First business has missing reviews',['e1'])
  other=ResearchSession(self.research,self.s,self.cid);other.cid='other';other.root_task_id='second'
  messages=organization_updates(other)
  self.assertEqual(1,len(messages));self.assertEqual(self.cid,messages[0]['candidate_id'])
  other.run_id='unrelated';self.assertEqual([],organization_updates(other))
 def test_own_questions_not_broadcast_as_other_team_tasks(self):
  self.session.root_task_id='first'
  message(self.session,'writer','qa','question','Check my own hook')
  other=ResearchSession(self.research,self.s,self.cid);other.cid='other'
  self.assertEqual([],organization_updates(other))
