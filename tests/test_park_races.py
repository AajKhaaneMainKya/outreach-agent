import copy,json,unittest
from unittest.mock import patch
import test_playbook_campaigns as fixtures
from gtm import db,playbook_campaigns as campaigns

class ParkRaceTests(unittest.TestCase):
    setUp=fixtures.CampaignStrategyTests.setUp
    tearDown=fixtures.CampaignStrategyTests.tearDown
    def seed(self,stage='needs_verification'):
        with db.connect() as conn:
            conn.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',('race',json.dumps(self.s),'awaiting_review',None,db.now()))
            conn.execute('INSERT INTO playbook_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',('candidate','race','race-place',stage,json.dumps(self.place),json.dumps(self.research),json.dumps(self.value),'{}',None,db.now()))
        return 'candidate'

    def assert_parked(self):
        with db.connect() as conn:
            row=conn.execute("SELECT * FROM playbook_candidates WHERE id='candidate'").fetchone()
            self.assertEqual('parked',row['stage'])
            run=conn.execute("SELECT * FROM playbook_runs WHERE id='race'").fetchone()
            self.assertEqual('complete',run['stage'])
            self.assertIsNone(run['error'])
            self.assertEqual(0,conn.execute("SELECT count(*) FROM manual_contacts").fetchone()[0])

    def test_park_during_preparation_success_cannot_reopen_run(self):
        cid=self.seed()
        with patch.object(campaigns.threading,'Thread') as thread:
            campaigns.prepare_script(cid)
            task=thread.call_args.kwargs['target']
        campaigns.park(cid)
        with patch.object(campaigns,'hermes',return_value=copy.deepcopy(self.value)):
            task()
        self.assert_parked()

    def test_park_during_preparation_failure_cannot_reopen_run(self):
        cid=self.seed()
        with patch.object(campaigns.threading,'Thread') as thread:
            campaigns.prepare_script(cid)
            task=thread.call_args.kwargs['target']
        campaigns.park(cid)
        with patch.object(campaigns,'hermes',side_effect=ValueError('late failure')):
            task()
        self.assert_parked()

    def test_park_during_retrieve_preserves_saved_evidence(self):
        cid=self.seed('queued')
        def retrieve(place):
            campaigns.park(cid)
            return dict(self.research,evidence=[])
        with patch.object(campaigns,'retrieve',side_effect=retrieve),patch.object(campaigns,'hermes') as worker:
            campaigns.run('race')
            worker.assert_not_called()
        self.assert_parked()
        with db.connect() as conn:
            self.assertEqual(self.research,json.loads(conn.execute("SELECT research FROM playbook_candidates WHERE id=?",(cid,)).fetchone()[0]))

    def test_park_during_research_success_cannot_resurrect_candidate(self):
        cid=self.seed('queued')
        def research(*args):
            campaigns.park(cid)
            return copy.deepcopy(self.value)
        with patch.object(campaigns,'retrieve',return_value=self.research),patch.object(campaigns,'hermes',side_effect=research):
            campaigns.run('race')
        self.assert_parked()

    def test_park_during_research_failure_cannot_fail_completed_run(self):
        cid=self.seed('queued')
        def research(*args):
            campaigns.park(cid)
            raise ValueError('late error')
        with patch.object(campaigns,'retrieve',return_value=self.research),patch.object(campaigns,'hermes',side_effect=research):
            campaigns.run('race')
        self.assert_parked()
