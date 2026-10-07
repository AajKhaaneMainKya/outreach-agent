import copy,json,os,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from gtm import db,playbook,playbook_campaigns as campaigns
import test_playbook

class CampaignStrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=patch('gtm.db.DATA',Path(self.tmp.name));self.data.start();db.init();playbook.init();campaigns.init()
        self.s={'icp':'dietitian','city':'Austin, Texas','sender':'Poornima','timezone':'America/Chicago','limit':5,'business':''}
        self.place={'place_id':'p1','name':'Example Practice','website':'https://example.test','source':'https://maps.google.com/example','address':'Austin'}
        self.research={'place_details':{'id':'p1','displayName':{'text':'Example Practice'},'googleMapsUri':'https://maps.google.com/example','internationalPhoneNumber':'+15125551234','userRatingCount':70},'reviews':[],'website':'https://example.test','evidence':[{'id':'e1','quote':'Our practice has 3 RDNs and cash-pay clients.','url':'https://example.test/team','kind':'website','retrieved_at':db.now()}]}
        self.value={'qa_pass':True,'icp':'dietitian','reason':'Source-backed team facts; remaining criteria need verification','findings':['Verify the newest reviews and line type'],'facts':{'rdn_count':3,'cash_pay':True,'staff':None,'hook':None},'fact_evidence':{'rdn_count':[{'evidence_id':'e1','quote':'3 RDNs'}],'cash_pay':[{'evidence_id':'e1','quote':'cash-pay clients'}]},'agent_trace':['Mocked four-specialist research']}
    def tearDown(self):self.data.stop();self.tmp.cleanup()
    def test_discovery_uses_only_authoritative_icp_terms_and_deduplicates(self):
        with patch('gtm.providers.discover',return_value=[self.place]) as discover:
            out=campaigns.discover(self.s)
            self.assertEqual(1,len(out))
            self.assertEqual(playbook.policy()['dietitian']['search'],[c.args[0]['query'] for c in discover.call_args_list])
    def test_invalid_icp_or_missing_connections_never_calls_providers(self):
        with patch.dict(os.environ,{'GOOGLE_PLACES_API_KEY':'','HERMES_MODEL':''}),patch('gtm.providers.discover') as provider:
            self.assertRaisesRegex(ValueError,'VJ strategy is loaded',campaigns.start,self.s);provider.assert_not_called()
        s=dict(self.s,icp='rehab');self.assertRaisesRegex(ValueError,'Ask VJ',campaigns.settings,s)
    def test_agent_cannot_invent_evidence_or_contact_fields(self):
        self.assertEqual(3,campaigns.validate(self.value,self.research,self.s)['facts']['rdn_count'])
        forged=copy.deepcopy(self.value);forged['fact_evidence']['rdn_count'][0]['quote']='10 RDNs'
        self.assertRaisesRegex(ValueError,'invented evidence',campaigns.validate,forged,self.research,self.s)
        forged=copy.deepcopy(self.value);forged['facts']['gmb_phone']='+15125559999'
        self.assertRaisesRegex(ValueError,'contact/approval fields',campaigns.validate,forged,self.research,self.s)
    def test_pipeline_prefills_review_without_approving_or_contacting(self):
        rid=uuid.uuid4().hex
        with db.connect() as conn:conn.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',(rid,json.dumps(self.s),'running',None,db.now()))
        with patch.object(campaigns,'discover',return_value=[self.place]),patch.object(campaigns,'retrieve',return_value=self.research),patch.object(campaigns,'hermes',return_value=self.value):campaigns.run(rid,True)
        snap=campaigns.snapshot();self.assertEqual('awaiting_review',snap['runs'][0]['stage']);c=snap['candidates'][0]
        self.assertEqual('needs_verification',c['stage']);self.assertEqual(3,c['facts']['rdn_count'])
        self.assertFalse(c['facts']['qualification_verified']);self.assertEqual('',c['facts']['line_type'])
        with db.connect() as conn:
            self.assertEqual(0,conn.execute('SELECT count(*) FROM manual_contacts').fetchone()[0])
            self.assertEqual(0,conn.execute('SELECT count(*) FROM manual_prospects').fetchone()[0])
    def test_failed_qa_cannot_enter_contact_queue(self):
        rid=uuid.uuid4().hex;cid=uuid.uuid4().hex
        with db.connect() as conn:
            conn.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',(rid,json.dumps(self.s),'awaiting_review',None,db.now()))
            conn.execute('INSERT INTO playbook_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,rid,'p1','needs_verification',json.dumps(self.place),'{}',json.dumps({'qa_pass':False}),'{}',None,db.now()))
        self.assertRaisesRegex(ValueError,'QA failed',campaigns.accept,cid,test_playbook.facts())

    def test_park_preserves_research_and_releases_new_campaign(self):
        for queued in (False, True):
            with self.subTest(queued=queued):
                rid=uuid.uuid4().hex;cid=uuid.uuid4().hex
                with db.connect() as conn:
                    conn.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',(rid,json.dumps(self.s),'awaiting_review',None,db.now()))
                    conn.execute('INSERT INTO playbook_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,rid,cid,'needs_verification',json.dumps(self.place),json.dumps(self.research),json.dumps(self.value),'{}',None,db.now()))
                    if queued:
                        nxt=uuid.uuid4().hex
                        conn.execute('INSERT INTO playbook_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(nxt,rid,nxt,'queued',json.dumps(self.place),'{}','{}','{}',None,db.now()))
                campaigns.park(cid)
                campaigns.park(cid)  # Repeated delivery must remain safe and successful.
                with db.connect() as conn:
                    parked=conn.execute('SELECT * FROM playbook_candidates WHERE id=?',(cid,)).fetchone()
                    self.assertEqual('parked',parked['stage'])
                    self.assertEqual(self.research,json.loads(parked['research']))
                    self.assertEqual('ready' if queued else 'complete',conn.execute('SELECT stage FROM playbook_runs WHERE id=?',(rid,)).fetchone()['stage'])
                    self.assertEqual(0,conn.execute("SELECT count(*) FROM playbook_runs WHERE stage='awaiting_review'").fetchone()[0])
                    self.assertEqual(0,conn.execute('SELECT count(*) FROM manual_contacts').fetchone()[0])
                with patch.object(campaigns,'connections',return_value={'missing':[]}),patch('gtm.playbook_campaigns.threading.Thread') as thread:
                    new=campaigns.start(dict(self.s,source='web'))
                    thread.return_value.start.assert_called_once()
                with db.connect() as conn:conn.execute("UPDATE playbook_runs SET stage='complete' WHERE id=?",(new,))
