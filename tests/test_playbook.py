import copy, json, tempfile, unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from gtm import db, playbook

def facts(icp='spa',line='mobile'):
    return dict(business='Example Spa',city='Austin',icp=icp,gmb_url='https://maps.google.com/example',gmb_phone='+15125551234',website='https://example.test',timezone='UTC',sender='Poornima',facts_source='Verified GMB/menu/team',menu='Facials, massage',context='Verified competitor or cash-pay information',reviews=70,staff_count=4,locations=1,years_open=3,rdn_count=3,independent=True,owner_run=True,chain=False,franchise=False,hospital_employed=False,cash_pay=True,insurance_only=False,no_text=False,line_type=line,lookup_source='Human line lookup',newest_reviews=[{'stars':5,'text':'Elena gave me a wonderful facial.','date':f'2026-10-0{5-i}','source':'https://maps.google.com/example'} for i in range(5)],hook='a wonderful facial.',staff='Elena',gmb_number_verified=True,qualification_verified=True,hook_verified=True,safe_fields_verified=True)

class PlaybookTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.patch=patch('gtm.db.DATA',Path(self.tmp.name));self.patch.start();db.init();playbook.init()
    def tearDown(self): self.patch.stop();self.tmp.cleanup()
    def test_qualifies_both_and_skips_all_exclusions(self):
        for icp in ('spa','dietitian'): self.assertEqual('qualified',playbook.qualification(facts(icp))[0])
        for key,val in [('chain',True),('franchise',True),('menu','Botox'),('menu','filler'),('menu','med spa'),('menu','aesthetics'),('locations',2),('staff_count',2),('reviews',49),('years_open',1),('owner_run',False),('independent',False)]:
            f=facts();f[key]=val;self.assertEqual('skip',playbook.qualification(f)[0],key)
        for key,val in [('rdn_count',1),('rdn_count',2),('hospital_employed',True),('cash_pay',False),('reviews',49)]:
            f=facts('dietitian');f[key]=val;self.assertEqual('skip',playbook.qualification(f)[0],key)
    def test_verbatim_hook_and_template(self):
        f=facts();d=playbook.compose(f)
        self.assertIn('Try it free for 2 weeks:',d['text1']);self.assertIn('Reply STOP',d['text1']);self.assertEqual(playbook.policy()['money_line'],d['money_line'])
        f['hook']='invented review';self.assertRaises(ValueError,playbook.compose,f)
        f=facts();f['hook']=' '.join(['word']*15);self.assertRaises(ValueError,playbook.compose,f)
        f=facts();f['newest_reviews'][0]['stars']=1;f['newest_reviews']= [f['newest_reviews'][0]]*5;self.assertRaises(ValueError,playbook.compose,f)
    def test_missing_source_or_unknown_line_blocks(self):
        for key,val in [('line_type','unknown'),('gmb_number_verified',False),('qualification_verified',False),('timezone','Unknown/Zone'),('safe_fields_verified',False)]:
            f=facts();f[key]=val;self.assertRaises(ValueError,playbook.create,f)
    def test_one_prospect_and_duplicate_history(self):
        pid=playbook.create(facts());f=facts();f['business']='Another';f['gmb_phone']='+15125551235';self.assertRaises(ValueError,playbook.create,f)
        playbook.outcome(pid,{'outcome':'Park','next_step':'None','due':'None'})
        self.assertRaises(ValueError,playbook.create,facts())
    def test_hours_channels_and_tamper(self):
        pid=playbook.create(facts())
        with db.connect() as conn:
            p=playbook.get(conn,pid)
            for hour,blocked in [(7,True),(8,False),(19,False),(20,True)]:
                self.assertEqual(blocked,any('Outside' in x for x in playbook.blockers(conn,p,'text1',datetime(2026,10,5,hour,tzinfo=timezone.utc))))
            self.assertTrue(playbook.blockers(conn,p,'call',datetime(2026,10,5,12,tzinfo=timezone.utc)))
            self.assertTrue(playbook.blockers(conn,p,'question_reply',datetime(2026,10,5,12,tzinfo=timezone.utc)))
            p['draft']['text1']+=' Invented discount';self.assertTrue(any('Template changed' in x for x in playbook.blockers(conn,p,'text1')))
    def test_approval_required_release_reserved_once_stop_all_channels(self):
        pid=playbook.create(facts());self.assertRaises(ValueError,playbook.handover,pid,{'manual_only':True,'action':'text1'})
        at=datetime(2026,10,5,12,tzinfo=timezone.utc)
        with patch('gtm.playbook.datetime') as dt:
            dt.now.return_value=at;dt.fromisoformat.side_effect=datetime.fromisoformat
            playbook.approve(pid,{'action':'text1','claims_reviewed':True})
            result=playbook.handover(pid,{'action':'text1','manual_only':True});self.assertIn('Reply STOP',result['script'])
            self.assertRaises(ValueError,playbook.handover,pid,{'action':'text1','manual_only':True})
        row=playbook.outcome(pid,{'outcome':'Reply','reply':'STOP','next_step':'Review','due':'Today'})
        self.assertEqual('Never contact again',row['Next step'])
        with db.connect() as conn:
            p=playbook.get(conn,pid)
            for a in ('text1','text2','call','voicemail'):self.assertTrue(any('suppression' in x for x in playbook.blockers(conn,p,a,at)))
    def test_day3_no_reply_and_lifetime_two_texts(self):
        pid=playbook.create(facts());base=datetime(2026,10,5,12,tzinfo=timezone.utc)
        with db.connect() as conn:
            conn.execute('INSERT INTO manual_contacts(prospect_id,action,created) VALUES(?,?,?)',(pid,'text1',base.isoformat()))
            p=playbook.get(conn,pid)
            self.assertTrue(any('day 3' in x for x in playbook.blockers(conn,p,'text2',base+timedelta(days=1))))
            self.assertFalse(playbook.blockers(conn,p,'text2',base+timedelta(days=2)))
            conn.execute('INSERT INTO manual_contacts(prospect_id,action,created) VALUES(?,?,?)',(pid,'text2',(base+timedelta(days=2)).isoformat()))
            self.assertTrue(any('Two texts' in x for x in playbook.blockers(conn,p,'text2',base+timedelta(days=3))))
    def test_any_reply_cancels_followup(self):
        pid=playbook.create(facts());base=datetime(2026,10,5,12,tzinfo=timezone.utc)
        with db.connect() as conn:conn.execute('INSERT INTO manual_contacts(prospect_id,action,created) VALUES(?,?,?)',(pid,'text1',base.isoformat()))
        playbook.outcome(pid,{'outcome':'Question','reply':'How does it work?','next_step':'Ask VJ','due':'Today'})
        with db.connect() as conn:self.assertTrue(any('Any reply' in x for x in playbook.blockers(conn,playbook.get(conn,pid),'text2',base+timedelta(days=2))))
    def test_pdf_and_policy_integrity_fail_closed(self):
        original=Path.read_bytes
        with patch.object(Path,'read_bytes',lambda p:b'changed' if p.name.endswith('.pdf') else original(p)):
            self.assertRaises(ValueError,playbook.policy)

    def test_skip_needs_no_lookup_or_review(self):
        f=facts();f.update(chain=True,gmb_phone='',timezone='',line_type='',hook='',newest_reviews=[])
        pid=playbook.create(f)
        with db.connect() as conn:self.assertEqual('skip',playbook.get(conn,pid)['stage'])
    def test_booked_call_requires_dated_15_minute_slot(self):
        pid=playbook.create(facts())
        self.assertRaises(ValueError,playbook.outcome,pid,{'outcome':'Booked call','next_step':'Think about it','due':'Tomorrow'})
        r=playbook.outcome(pid,{'outcome':'Booked call','next_step':'15-minute calendar slot confirmed','due':'2026-10-07T12:00:00+00:00'})
        self.assertEqual('Booked call',r['Outcome'])

    def test_edits_clear_approval_and_stop_needs_no_extra_fields(self):
        pid=playbook.create(facts());at=datetime(2026,10,5,12,tzinfo=timezone.utc)
        with patch('gtm.playbook.datetime') as dt:
            dt.now.return_value=at;dt.fromisoformat.side_effect=datetime.fromisoformat
            playbook.approve(pid,{'action':'text1','claims_reviewed':True})
        corrected=facts();corrected['sender']='VJ';playbook.edit(pid,corrected)
        with db.connect() as conn:self.assertIsNone(playbook.get(conn,pid)['approval_hash'])
        row=playbook.outcome(pid,{'reply':'STOP'})
        self.assertEqual('Never contact again',row['Next step'])
        self.assertRaises(ValueError,playbook.edit,pid,corrected)
    def test_plain_stop_is_optout_in_rehab(self):
        from gtm.agents import classify
        self.assertEqual('opt_out',classify('STOP')[0])
