import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from gtm import apollo

class ApolloTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.addCleanup(patch.stopall)
  patch('gtm.apollo.DATA',Path(self.temp.name)).start()
  patch.dict(os.environ,{'APOLLO_API_KEY':'synthetic-key','ALLOW_APOLLO_ENRICHMENT':'false','APOLLO_DAILY_ENRICHMENT_LIMIT':'5'}).start()
  self.person={'id':'p1','name':'Test Owner','title':'Owner','organization':{'name':'Practice','primary_domain':'practice.org'},'email':'owner@practice.org','email_status':'verified','phone_numbers':[{'raw_number':'private'}],'personal_emails':['private@email.org']}
 def test_search_omits_emails_and_phone_and_scopes_domain(self):
  with patch('gtm.apollo.request',return_value={'people':[self.person]}) as req:
   result=apollo.search('https://www.practice.org/team',['owner'],5)
  self.assertEqual(['practice.org'],req.call_args.args[1]['q_organization_domains_list'])
  self.assertEqual('',result['contacts'][0]['email']);self.assertNotIn('phone_numbers',result['contacts'][0])
  self.assertTrue(result['no_contact']);self.assertTrue(result['contacts'][0]['current_employer_domain_matches'])
  self.assertEqual(0o600,(Path(self.temp.name)/'apollo/contacts.sqlite3').stat().st_mode&0o777)
 def test_bad_domains_and_limits_block_before_request(self):
  with patch('gtm.apollo.request') as req:
   for domain in ['localhost','https://user:password@practice.org','127.0.0.1','https://practice.org:9999','fake.test']:
    with self.assertRaises(ValueError):apollo.search(domain)
   with self.assertRaises(ValueError):apollo.search('practice.org',limit=11)
   req.assert_not_called()
 def test_missing_key_and_redirect_never_leak(self):
  with patch.dict(os.environ,{'APOLLO_API_KEY':''}):
   with self.assertRaisesRegex(ValueError,'Save APOLLO_API_KEY'):apollo.request('auth/health')
  with self.assertRaisesRegex(ValueError,'redirect refused'):apollo.NoRedirect().redirect_request(None,None,302,'',{},'https://other.org')
 def test_enrichment_disabled_and_unsaved_id_blocked(self):
  with patch('gtm.apollo.request') as req:
   with self.assertRaisesRegex(ValueError,'off'):apollo.enrich('p1','practice.org',True)
   with patch.dict(os.environ,{'ALLOW_APOLLO_ENRICHMENT':'true'}):
    with self.assertRaisesRegex(ValueError,'saved Apollo search'):apollo.enrich('invented','practice.org',True)
   req.assert_not_called()
 def seed(self):
  with patch('gtm.apollo.request',return_value={'people':[self.person]}):apollo.search('practice.org')
 def test_explicit_enrichment_and_cache_preserves_flags(self):
  self.seed()
  with patch.dict(os.environ,{'ALLOW_APOLLO_ENRICHMENT':'true'}),patch('gtm.apollo.request',return_value={'person':self.person}) as req:
   result=apollo.enrich('p1','practice.org',True)
   for k in ['reveal_personal_emails','reveal_phone_number','run_waterfall_email','run_waterfall_phone']:self.assertIs(False,req.call_args.args[1][k])
   self.assertEqual('owner@practice.org',result['email']);self.assertTrue(result['no_approval'])
  self.seed()
  with patch.dict(os.environ,{'ALLOW_APOLLO_ENRICHMENT':'true'}),patch('gtm.apollo.request') as req:
   self.assertEqual('owner@practice.org',apollo.enrich('p1','practice.org',True)['email']);req.assert_not_called()
 def test_wrong_employer_personal_email_and_placeholder_rejected(self):
  for changed in [dict(self.person,organization={'primary_domain':'other.org'}),dict(self.person,email='person@gmail.com'),dict(self.person,email='email_not_unlocked@domain.com'),dict(self.person,email_status='unverified')]:
   self.assertEqual('',apollo.clean_person(changed,'practice.org',True)['email'])
 def test_failed_enrichment_reserves_daily_budget(self):
  self.seed()
  with patch.dict(os.environ,{'ALLOW_APOLLO_ENRICHMENT':'true','APOLLO_DAILY_ENRICHMENT_LIMIT':'1'}),patch('gtm.apollo.request',side_effect=apollo.ApolloError('rate limit')) as req:
   with self.assertRaisesRegex(ValueError,'rate limit'):apollo.enrich('p1','practice.org',True)
   with self.assertRaisesRegex(ValueError,'cap reached'):apollo.enrich('p1','practice.org',True)
   self.assertEqual(1,req.call_count)
