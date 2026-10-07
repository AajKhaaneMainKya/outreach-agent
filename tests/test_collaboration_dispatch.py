import ast,json,re,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import test_research_tools as fixtures
from gtm.research_tools import message,board_rows
from gtm import db

class CollaborationDispatchTests(unittest.TestCase):
    tearDown=fixtures.ResearchToolTests.tearDown
    def setUp(self):
        fixtures.ResearchToolTests.setUp(self)
        self.session.root_task_id='mission-test'
        self.session.completed_roles=set()
        self.delegate=Mock()
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'scripts/hermes_worker.py').read_text())
        dispatch=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='dispatch')
        module=ast.Module(body=[dispatch],type_ignores=[])
        namespace={'json':json,'session':self.session,'dt':SimpleNamespace(delegate_task=self.delegate),'project':root,'payload':{'authoritative_policy':{'test':'VJ'}},'message':message,'role_for':lambda goal:re.match(r'^\[([^]]+)\]',goal).group(1)}
        exec(compile(module,'hermes-dispatch-test','exec'),namespace)
        self.dispatch=namespace['dispatch']
        self.agent=object()
    def exchanges(self):
        with db.connect() as conn:return board_rows(conn,self.cid)
    def test_question_routes_to_recipient_with_shared_board_and_reply(self):
        question=message(self.session,'writer','researcher','question','Verify the staff review',['e1'])
        self.delegate.side_effect=lambda **kw:json.dumps({'results':[{'task_index':i,'summary':'Verified evidence e1'} for i,_ in enumerate(kw['tasks'])]})
        self.dispatch(self.agent,{'tasks':[{'goal':'[qa] Check the proposed draft','context':'draft'}]})
        self.assertEqual(3,self.delegate.call_count)
        routed=self.delegate.call_args_list[1].kwargs['tasks'][0]
        self.assertTrue(routed['goal'].startswith('[researcher]'))
        context=json.loads(routed['context'])
        self.assertEqual(question['message_id'],context['questions_to_answer'][0]['id'])
        self.assertTrue(any(m['summary']=='Verify the staff review' for m in context['shared_agent_exchanges']))
        self.assertEqual({'test':'VJ'},context['authoritative_policy'])
        self.assertTrue(any(m['sender']=='researcher' and m['recipient']=='writer' and question['message_id'] in m['summary'] for m in self.exchanges()))
        self.assertEqual({},self.session.pending_messages)
        returned=self.delegate.call_args_list[2].kwargs['tasks'][0]
        self.assertTrue(returned['goal'].startswith('[writer]'))
        consumed=json.loads(returned['context'])['answers_to_consume']
        self.assertEqual(question['message_id'],consumed[0]['request']['id'])
        self.assertEqual('Verified evidence e1',consumed[0]['answer'])
        self.assertEqual({},self.session.reply_readers)
    def test_feedback_chains_stop_at_two_followup_rounds_and_block_save(self):
        def delegate(**kw):
            role=re.match(r'^\[([^]]+)\]',kw['tasks'][0]['goal']).group(1)
            recipient='writer' if role=='qa' else 'qa'
            message(self.session,role,recipient,'feedback','Revise unsupported claim')
            return json.dumps({'results':[{'task_index':0,'summary':'Checked but requires correction'}]})
        self.delegate.side_effect=delegate
        result=json.loads(self.dispatch(self.agent,{'tasks':[{'goal':'[qa] Check draft'}]}))
        self.assertEqual(3,self.delegate.call_count)
        self.assertIn('follow_up',result)
        self.assertTrue(self.session.pending_messages)
        self.session.completed_roles={'researcher','qualifier','writer','qa'}
        self.assertRaisesRegex(ValueError,'unanswered',self.session.save,self.value)
        self.assertTrue(any(m['kind']=='blocker' and 'budget' in m['summary'] for m in self.exchanges()))
        self.assertFalse(self.session.saved)
    def test_empty_summary_keeps_question_pending(self):
        message(self.session,'writer','researcher','question','Missing evidence')
        self.delegate.return_value=json.dumps({'results':[{'task_index':0,'summary':''}]})
        self.dispatch(self.agent,{'tasks':[{'goal':'[researcher] Answer question'}]})
        self.assertEqual(3,self.delegate.call_count)
        self.assertTrue(self.session.pending_messages)
        self.assertNotIn('researcher',self.session.completed_roles)

    def test_unconsumed_reply_blocks_save(self):
        self.session.completed_roles={'researcher','qualifier','writer','qa'}
        self.session.reply_readers={'writer':[{'request':{'id':'answer-needed'},'answer':'Verified staff e1'}]}
        self.assertRaisesRegex(ValueError,'unanswered',self.session.save,self.value)
        self.assertFalse(self.session.saved)
