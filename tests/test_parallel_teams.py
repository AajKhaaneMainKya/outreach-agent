import copy,json,threading,unittest
from unittest.mock import patch
import test_playbook_campaigns as fixtures
from gtm import db,playbook_campaigns as campaigns

class ParallelTeamTests(unittest.TestCase):
    setUp=fixtures.CampaignStrategyTests.setUp
    tearDown=fixtures.CampaignStrategyTests.tearDown
    def seed(self,count=3):
        self.s['team_count']=3
        with db.connect() as conn:
            conn.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',('parallel',json.dumps(self.s),'running',None,db.now()))
            for i in range(count):
                place=dict(self.place,place_id=f'p{i}',name=f'Practice {i}')
                conn.execute('INSERT INTO playbook_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(f'c{i}','parallel',f'p{i}','queued',json.dumps(place),'{}','{}','{}',None,db.now()))
    def states(self):
        with db.connect() as conn:
            return {r['id']:r['stage'] for r in conn.execute('SELECT id,stage FROM playbook_candidates')},conn.execute("SELECT stage FROM playbook_runs WHERE id='parallel'").fetchone()[0]
    def test_three_candidates_research_concurrently_isolated_and_finish_together(self):
        self.seed();barrier=threading.Barrier(3);seen=[];lock=threading.Lock()
        def retrieve(place):
            research=copy.deepcopy(self.research);research['place_details']['id']=place['place_id'];return research
        def hermes(research,s,cid):
            with lock:seen.append((cid,research['place_details']['id'],id(research)))
            barrier.wait(timeout=5)
            with db.connect() as conn:self.assertEqual('running',conn.execute("SELECT stage FROM playbook_runs WHERE id='parallel'").fetchone()[0])
            return copy.deepcopy(self.value)
        with patch.object(campaigns,'retrieve',side_effect=retrieve),patch.object(campaigns,'hermes',side_effect=hermes):campaigns.run('parallel')
        states,stage=self.states();self.assertEqual({'needs_verification'},set(states.values()));self.assertEqual('awaiting_review',stage)
        self.assertEqual(3,len({r[2] for r in seen}));self.assertEqual({('c0','p0'),('c1','p1'),('c2','p2')},{r[:2] for r in seen})
        with db.connect() as conn:self.assertEqual(0,conn.execute('SELECT count(*) FROM manual_contacts').fetchone()[0])
    def test_failed_first_candidate_does_not_block_other_teams(self):
        self.seed(6)
        def hermes(research,s,cid):
            if cid=='c0':raise ValueError('No accessible source')
            return copy.deepcopy(self.value)
        with patch.object(campaigns,'retrieve',side_effect=lambda _:copy.deepcopy(self.research)),patch.object(campaigns,'hermes',side_effect=hermes):campaigns.run('parallel')
        states,stage=self.states();self.assertEqual('failed',states['c0']);self.assertEqual(5,list(states.values()).count('needs_verification'));self.assertEqual('awaiting_review',stage)
    def test_park_one_team_does_not_stop_or_resurrect_others(self):
        self.seed()
        def hermes(research,s,cid):
            if cid=='c0':campaigns.park(cid)
            return copy.deepcopy(self.value)
        with patch.object(campaigns,'retrieve',side_effect=lambda _:copy.deepcopy(self.research)),patch.object(campaigns,'hermes',side_effect=hermes):campaigns.run('parallel')
        states,stage=self.states();self.assertEqual('parked',states['c0']);self.assertEqual(2,list(states.values()).count('needs_verification'));self.assertEqual('awaiting_review',stage)
    def test_excluded_multilocation_spa_is_skipped_and_next_candidate_researched(self):
        self.s['icp']='spa';self.seed(2)
        def hermes(research,s,cid):
            v=copy.deepcopy(self.value);v['icp']='spa';v['facts']={'locations':2 if cid=='c0' else 1};return v
        with patch.object(campaigns,'retrieve',side_effect=lambda _:copy.deepcopy(self.research)),patch.object(campaigns,'hermes',side_effect=hermes):campaigns.run('parallel')
        states,stage=self.states();self.assertEqual('skipped',states['c0']);self.assertEqual('needs_verification',states['c1'])
        self.assertTrue(campaigns.qualification_notice({'facts':{'context':'We operate several locations.'}},self.s))
    def test_defaults_and_parallel_bounds(self):
        s=dict(self.s);s.pop('limit');out=campaigns.settings(s);self.assertEqual(6,out['limit']);self.assertEqual(3,out['team_count'])
        self.assertRaises(ValueError,campaigns.settings,dict(s,team_count=4))
        self.assertRaises(ValueError,campaigns.settings,dict(s,limit=13))
    def test_review_queue_does_not_block_new_discovery(self):
        self.seed(1)
        with db.connect() as conn:conn.execute("UPDATE playbook_runs SET stage='awaiting_review'");conn.execute("UPDATE playbook_candidates SET stage='needs_verification'")
        with patch.object(campaigns,'connections',return_value={'missing':[]}),patch.object(campaigns.threading,'Thread') as thread:
            campaigns.start(dict(self.s,source='web'));thread.return_value.start.assert_called_once()
