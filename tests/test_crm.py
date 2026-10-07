import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from gtm import db,crm,playbook,playbook_campaigns

class CRMTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.addCleanup(patch.stopall);patch.object(db,'DATA',Path(self.temp.name)).start()
  patch.dict(os.environ,{'ALLOW_FOLLOWUP_SEND':'false'}).start()
  db.init();playbook.init();playbook_campaigns.init();crm.init()
  self.cid=crm.create({'business':'Real practice','icp':'spa','website':'https://practice.test'})['id']
  self.settings={'sender_email':'vijai@continerehealth.com','sender_name':'Vijai','postal_address':'Test business address',
   'domain_ready':True,'daily_limit':5,'subject_template':'Requested details for $business','body_template':'Test-only VJ-approved follow-up for $contact_name.',
   'approved_by':'VJ','template_source':'Test fixture approval','template_approved':True}
  crm.save_settings(self.settings)
 def contact(self):
  with db.connect() as c:return crm.get(c,self.cid)
 def permission(self):
  p=self.contact();crm.update(self.cid,{'revision':p['revision'],'name':'Owner','email':'owner@practice.test','stage':'contacted',
   'record_consent':True,'email_verified':True,'consent_method':'call','consent_evidence':'Recipient asked: please email the details.'})
 def draft(self):
  self.permission();eid=crm.prepare(self.cid)['id']
  with db.connect() as c:e=crm.email(c,eid)
  crm.approve(eid,{'revision':e['revision'],'reviewed':True});return eid,e['revision']
 def test_create_dedup_no_assumed_consent(self):
  self.assertEqual(self.cid,crm.create({'business':'Duplicate','icp':'spa','website':'https://practice.test/team'})['id'])
  self.assertEqual({},self.contact()['consent'])
  with self.assertRaisesRegex(ValueError,'recipient request'):crm.prepare(self.cid)
 def test_permission_needs_verified_address_and_proof(self):
  p=self.contact()
  with self.assertRaisesRegex(ValueError,'Confirm'):crm.update(self.cid,{'revision':p['revision'],'email':'owner@practice.test','record_consent':True})
  self.permission();self.assertEqual('one_requested_followup',self.contact()['consent']['purpose'])
 def test_email_change_revokes_permission_and_approval(self):
  eid,rev=self.draft();p=self.contact()
  crm.update(self.cid,{'revision':p['revision'],'email':'different@practice.test','name':'Owner','stage':'interested'})
  self.assertEqual({},self.contact()['consent'])
  with db.connect() as c:self.assertEqual('draft',crm.email(c,eid)['stage'])
 def test_settings_source_and_unsafe_placeholders_blocked(self):
  for changes in [{'approved_by':'Agent'},{'template_source':''},{'body_template':'$made_up_claim'}]:
   with self.assertRaises(ValueError):crm.save_settings(dict(self.settings,**changes))
 def test_stale_template_requires_new_draft(self):
  self.permission();eid=crm.prepare(self.cid)['id'];crm.save_settings(dict(self.settings,body_template='New approved test-only body'))
  with self.assertRaisesRegex(ValueError,'fresh draft'):crm.approve(eid,{'revision':1,'reviewed':True})
 def test_approval_does_not_send(self):
  with patch('gtm.gmail.send') as send:
   eid,rev=self.draft();send.assert_not_called()
   with self.assertRaisesRegex(ValueError,'disabled'):crm.send(eid,{'revision':rev})
   send.assert_not_called()
 def test_requested_send_once_and_new_request(self):
  eid,rev=self.draft()
  with patch.dict(os.environ,{'ALLOW_FOLLOWUP_SEND':'true'}),patch('gtm.crm.sync'),patch('gtm.gmail.token_path',return_value=Path(__file__)),patch('gtm.gmail.send',return_value={'id':'message','threadId':'thread'}) as send:
   self.assertTrue(crm.send(eid,{'revision':rev})['sent']);self.assertEqual('owner@practice.test',send.call_args.args[0]['email'])
   with self.assertRaises(ValueError):crm.send(eid,{'revision':rev})
   self.assertEqual(1,send.call_count)
  self.assertEqual({},self.contact()['consent'])
  self.permission();self.assertNotEqual(eid,crm.prepare(self.cid)['id'])
 def test_send_error_unknown_never_retried_even_new_permission(self):
  eid,rev=self.draft()
  with patch.dict(os.environ,{'ALLOW_FOLLOWUP_SEND':'true'}),patch('gtm.crm.sync'),patch('gtm.gmail.token_path',return_value=Path(__file__)),patch('gtm.gmail.send',side_effect=TimeoutError) as send:
   with self.assertRaisesRegex(ValueError,'uncertain'):crm.send(eid,{'revision':rev})
   self.permission()
   with self.assertRaisesRegex(ValueError,'uncertain'):crm.prepare(self.cid)
   self.assertEqual(1,send.call_count)
 def test_stop_global_suppression_and_no_reactivation(self):
  eid,rev=self.draft();crm.record_reply(self.cid,{'text':'Please unsubscribe me'})
  self.assertTrue(self.contact()['stage']=='suppressed')
  with db.connect() as c:
   self.assertIsNotNone(c.execute('SELECT 1 FROM suppressions WHERE key=?',('owner@practice.test',)).fetchone())
   self.assertEqual('cancelled',crm.email(c,eid)['stage'])
  with self.assertRaisesRegex(ValueError,'reactivated'):crm.update(self.cid,{'revision':self.contact()['revision'],'stage':'interested'})
 def test_quoted_unsubscribe_footer_not_optout(self):
  self.permission();result=crm.record_reply(self.cid,{'text':'Thanks, interested.\nOn Monday someone wrote:\n> To stop receiving emails from us, reply unsubscribe.'})
  self.assertFalse(result['suppressed'])
  with self.assertRaisesRegex(ValueError,'reply arrived'):crm.prepare(self.cid)
 def test_daily_cap_and_missing_gmail_block(self):
  eid,rev=self.draft()
  with patch.dict(os.environ,{'ALLOW_FOLLOWUP_SEND':'true'}),patch('gtm.crm.sync'),patch('gtm.gmail.token_path',return_value=Path('/missing-file')),patch('gtm.gmail.send') as send:
   with self.assertRaisesRegex(ValueError,'Connect'):crm.send(eid,{'revision':rev})
   send.assert_not_called()
 def test_sync_optout_deduplicates_keeps_body_local(self):
  eid,rev=self.draft()
  with db.connect() as c:c.execute("UPDATE crm_emails SET stage='sent',gmail_id='sent-id',gmail_thread='thread' WHERE id=?",(eid,))
  message={'id':'incoming','payload':{'mimeType':'text/plain','headers':[{'name':'From','value':'owner@practice.test'}], 'body':{'data':'dW5zdWJzY3JpYmU'}}}
  with patch('gtm.gmail.profile',return_value='vijai@continerehealth.com'),patch('gtm.gmail.request',return_value={'messages':[message]}):crm.sync();crm.sync()
  self.assertEqual('suppressed',self.contact()['stage'])
  with db.connect() as c:self.assertEqual(1,c.execute("SELECT count(*) FROM crm_activity WHERE id='gmail:incoming'").fetchone()[0])
 def test_restart_marks_reserved_send_unknown(self):
  eid,rev=self.draft()
  with db.connect() as c:c.execute("UPDATE crm_emails SET stage='sending' WHERE id=?",(eid,))
  crm.init()
  with db.connect() as c:self.assertEqual('unknown',crm.email(c,eid)['stage'])
