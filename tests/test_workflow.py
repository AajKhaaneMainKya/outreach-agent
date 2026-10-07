import concurrent.futures
import json
import os
import shutil
import socket
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from gtm import agents, config, db, guards, providers, service

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        shutil.copytree(config.ROOT / 'config', root / 'config')
        self.patches = [patch.object(config, 'ROOT', root), patch.object(service, 'ROOT', root), patch.object(db, 'DATA', root / 'data')]
        for p in self.patches: p.start()
        db.init()
        self.settings = config.config('settings')
        self.settings.update(sender_email='owner@continere.test', sender_name='Test Owner', postal_address='Test business address', domain_readiness_confirmed=True)
        self.strategy = config.config('strategy')
        self.strategy.update(positioning='TEST ONLY', confirmed_by='Test reviewer', cta='Would a short conversation be useful?',
            approved_claims=[{'id': 'test-claim', 'text': 'Test-only approved proposition.', 'source': 'Test fixture, not Continere knowledge'}])
        self.strategy['icp']['description'] = 'Test physical rehabilitation providers'
        service.save_config('settings', self.settings)
        service.save_config('strategy', self.strategy)
        rid = uuid.uuid4().hex
        with db.connect() as conn:
            conn.execute('INSERT INTO runs(id,mode,status,geography,created,settings,strategy) VALUES(?,?,?,?,?,?,?)',
                (rid, 'demo', 'running', 'Texas', db.now(), '{}', '{}'))
        service.run(rid, 'demo', self.settings, self.strategy)
        with db.connect() as conn:
            self.pid = conn.execute('SELECT id FROM prospects ORDER BY name LIMIT 1').fetchone()[0]

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def prospect(self):
        with db.connect() as conn: return db.get(conn, self.pid)

    def verify(self, live=False):
        if live:
            with db.connect() as conn:
                conn.execute("UPDATE prospects SET mode='live', domain='rehab.test',website='https://rehab.test' WHERE id=?", (self.pid,))
        p = self.prospect()
        service.edit(self.pid, {'revision': p['revision'], 'email': 'office@rehab.test' if live else p['email'],
            'email_source': 'https://rehab.test/contact', 'subject': p['draft']['subject'], 'body': p['draft']['body'],
            'contact_verified': True, 'geography_verified': True})

    def approve(self):
        service.approve(self.pid, {'revision': self.prospect()['revision'], 'claims_verified': True})

    def test_demo_run_persists_and_deduplicates(self):
        with db.connect() as conn:
            before = conn.execute('SELECT count(*) FROM prospects').fetchone()[0]
            rid = conn.execute('SELECT id FROM runs').fetchone()[0]
        service.run(rid, 'demo', self.settings, self.strategy)
        db.init()
        with db.connect() as conn:
            self.assertEqual(before, conn.execute('SELECT count(*) FROM prospects').fetchone()[0])
            self.assertEqual(before, 6)

    def test_missing_strategy_blocks_live(self):
        s = dict(self.strategy, approved_claims=[])
        service.save_config('strategy', s)
        with self.assertRaisesRegex(ValueError, 'approved claim'):
            service.start_run('live')

    def test_approval_requires_verified_contact_geography_and_attestation(self):
        with self.assertRaisesRegex(ValueError, 'Verify the business email'):
            self.approve()
        self.verify()
        with self.assertRaisesRegex(ValueError, 'Confirm'):
            service.approve(self.pid, {'revision': self.prospect()['revision']})
        self.approve()
        self.assertEqual('approved', self.prospect()['status'])

    def test_edit_invalidates_approval_and_stale_revision_fails(self):
        self.verify(); self.approve()
        old = self.prospect()['revision']
        self.verify()
        self.assertEqual('review', self.prospect()['status'])
        self.assertIsNone(self.prospect()['approval_hash'])
        with self.assertRaises(ValueError):
            service.approve(self.pid, {'revision': old, 'claims_verified': True})

    def test_strategy_change_invalidates_and_changed_claim_blocks(self):
        self.verify(live=True); self.approve()
        self.strategy['approved_claims'][0]['text'] = 'Changed approved proposition.'
        service.save_config('strategy', self.strategy)
        self.assertEqual('review', self.prospect()['status'])
        with self.assertRaisesRegex(ValueError, 'verbatim'):
            self.approve()

    def test_opt_out_wins_and_duplicate_reply_is_idempotent(self):
        self.verify(live=True); self.approve()
        service.reply(self.pid, 'Interesting, but no thanks. Remove me.', reply_id='reply-1')
        service.reply(self.pid, 'Interesting, but no thanks. Remove me.', reply_id='reply-1')
        self.assertEqual('suppressed', self.prospect()['status'])
        with db.connect() as conn:
            self.assertEqual(1, conn.execute('SELECT count(*) FROM replies').fetchone()[0])
            self.assertTrue(conn.execute("SELECT 1 FROM suppressions WHERE key='rehab.test'").fetchone())

    def test_default_send_switch_is_closed(self):
        self.verify(live=True); self.approve()
        with patch.dict(os.environ, {'ALLOW_SEND':'false'}), patch.object(service.gmail, 'send') as sender:
            with self.assertRaisesRegex(ValueError, 'disabled'):
                service.send(self.pid, {'revision':self.prospect()['revision'], 'confirm_send':True})
            sender.assert_not_called()

    def test_demo_can_never_send_even_with_switch_on(self):
        self.verify(); self.approve()
        with patch.dict(os.environ, {'ALLOW_SEND':'true'}), patch.object(service, 'sync_replies'), patch.object(service.gmail, 'send') as sender:
            with self.assertRaisesRegex(ValueError, 'Demo records'):
                service.send(self.pid, {'revision':self.prospect()['revision'], 'confirm_send':True})
            sender.assert_not_called()

    def test_concurrent_send_clicks_dispatch_exactly_once(self):
        self.verify(live=True); self.approve()
        data = {'revision':self.prospect()['revision'], 'confirm_send':True}
        def attempt():
            try: service.send(self.pid, data); return 'sent'
            except ValueError: return 'blocked'
        with patch.dict(os.environ, {'ALLOW_SEND':'true'}), patch.object(service, 'sync_replies'), patch.object(service.gmail, 'send', return_value={'id':'message-1','threadId':'thread-1'}) as sender:
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda _:attempt(), range(2)))
            self.assertEqual(['blocked','sent'], sorted(results))
            self.assertEqual(sender.call_count, 1)

    def test_uncertain_send_never_retries(self):
        self.verify(live=True); self.approve()
        data = {'revision':self.prospect()['revision'], 'confirm_send':True}
        with patch.dict(os.environ, {'ALLOW_SEND':'true'}), patch.object(service, 'sync_replies'), patch.object(service.gmail, 'send', side_effect=TimeoutError) as sender:
            for _ in range(2):
                with self.assertRaises(ValueError): service.send(self.pid, data)
            self.assertEqual(1, sender.call_count)
            self.assertEqual('send_unknown', self.prospect()['status'])

    def test_changed_config_file_blocks_stale_approval(self):
        self.verify(live=True); self.approve()
        self.settings['sender_name'] = 'Changed'
        (config.ROOT/'config/settings.json').write_text(json.dumps(self.settings))
        with patch.dict(os.environ, {'ALLOW_SEND':'true'}), patch.object(service, 'sync_replies'), patch.object(service.gmail, 'send') as sender:
            with self.assertRaisesRegex(ValueError, 'changed after approval'):
                service.send(self.pid, {'revision':self.prospect()['revision'], 'confirm_send':True})
            sender.assert_not_called()

    def test_limits_and_bounce_circuit_breaker(self):
        self.verify(live=True)
        with db.connect() as conn:
            conn.execute('INSERT INTO deliveries(id,prospect_id,recipient,domain,status,created) VALUES(?,?,?,?,?,?)',
                ('delivery',self.pid,'other@different.test','different.test','sent',db.now()))
            s=dict(self.settings,daily_send_limit=1)
            self.assertIn('Daily send cap reached', guards.blockers(conn,self.prospect(),s,self.strategy,live=True))
        service.reply(self.pid,'Delivery failed: mailbox unavailable.')
        with db.connect() as conn:
            self.assertTrue(any('Bounce circuit breaker' in b for b in guards.blockers(conn,self.prospect(),self.settings,self.strategy,live=True)))

    def test_agent_cannot_invent_source_or_claim(self):
        r=self.prospect()['research']
        out={'qa_pass':True,'evidence_id':'fabricated','claim_id':'test-claim','reason':'test','pain_hypothesis':'Unknown'}
        with self.assertRaisesRegex(ValueError,'not retrieved'):
            agents.validate_selection(out,r,self.strategy)
        out['evidence_id']=r['evidence'][0]['id'];out['claim_id']='invented'
        with self.assertRaisesRegex(ValueError,'unapproved'):
            agents.validate_selection(out,r,self.strategy)

    def test_ssrf_private_dns_and_credentials_blocked(self):
        with patch.object(socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',80))]):
            with self.assertRaisesRegex(ValueError,'non-public'):
                providers.public_target('http://internal.test')
        for url in ('file:///etc/passwd','http://user:password@example.com','http://example.com:8000'):
            with self.assertRaises(ValueError): providers.public_target(url)

    def test_places_pagination_and_field_mask(self):
        settings=dict(self.settings,limit=25)
        with patch.dict(os.environ,{'GOOGLE_PLACES_API_KEY':'fixture'}),patch.object(providers,'api_json',side_effect=[{'places':[{'id':str(i)} for i in range(20)],'nextPageToken':'next'},{'places':[{'id':str(i)} for i in range(20,25)]}]) as api:
            results=providers.discover(settings)
            self.assertEqual(25,len(results))
            self.assertEqual('next',api.call_args_list[1].args[1]['pageToken'])
            self.assertIn('nextPageToken',api.call_args_list[0].args[2]['X-Goog-FieldMask'])

    def test_crash_recovery_marks_ambiguous_delivery(self):
        with db.connect() as conn:
            conn.execute("UPDATE prospects SET status='sending' WHERE id=?",(self.pid,))
            conn.execute('INSERT INTO deliveries(id,prospect_id,recipient,domain,status,created) VALUES(?,?,?,?,?,?)',
                ('delivery',self.pid,'x@rehab.test','rehab.test','sending',db.now()))
        db.init()
        self.assertEqual('send_unknown',self.prospect()['status'])
        with db.connect() as conn:self.assertEqual('unknown',conn.execute('SELECT status FROM deliveries').fetchone()[0])

    def test_refresh_replaces_draft_and_resets_verification(self):
        self.verify(); self.approve()
        rev=self.prospect()['revision']
        service.regenerate(self.pid, {'revision':rev})
        p=self.prospect()
        self.assertEqual(rev+1,p['revision'])
        self.assertEqual('review',p['status'])
        self.assertEqual(0,p['contact_verified'])
        self.assertEqual(0,p['geography_verified'])

    def test_geography_change_clears_existing_verification(self):
        self.verify(); self.approve()
        service.save_config('settings',dict(self.settings,geography='Ontario, Canada'))
        self.assertEqual(0,self.prospect()['geography_verified'])
        self.assertEqual(80,self.prospect()['score'])

    def test_quoted_opt_out_footer_is_not_a_new_opt_out(self):
        category,_=agents.classify('Sounds interesting.\n\nOn Monday, Owner wrote:\nReply no thanks to opt out.')
        self.assertEqual('interested',category)

    def test_stale_research_blocks_approval(self):
        self.verify()
        p=self.prospect()
        for e in p['research']['evidence']:e['retrieved_at']='2020-01-01T00:00:00+00:00'
        with db.connect() as conn:
            conn.execute('UPDATE prospects SET research=? WHERE id=?',(json.dumps(p['research']),self.pid))
        with self.assertRaisesRegex(ValueError,'30 days old'):self.approve()

if __name__=='__main__':unittest.main()
