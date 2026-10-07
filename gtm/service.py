import json
import os
import threading
import uuid
from email.utils import parseaddr
from pathlib import Path
from . import agents, gmail, guards, providers
from .config import ROOT, config, strategy_errors, validate_settings, validate_strategy
from .db import connect, event, get, now, prospect

LOCK = threading.RLock()

def snapshot():
    settings, strategy = config('settings'), config('strategy')
    with connect() as db:
        prospects = [prospect(r) for r in db.execute('SELECT * FROM prospects ORDER BY created DESC')]
        for p in prospects:
            p['blockers'] = guards.blockers(db, p, settings, strategy)
        runs = [dict(r) for r in db.execute('SELECT id,mode,status,geography,created,error,processed FROM runs ORDER BY created DESC LIMIT 20')]
        return {'prospects': prospects, 'runs': runs, 'settings': settings, 'strategy': strategy,
            'strategy_errors': strategy_errors(strategy),
            'events': [dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 60')],
            'replies': [dict(r) for r in db.execute('SELECT * FROM replies ORDER BY created DESC')],
            'suppressions': [dict(r) for r in db.execute('SELECT * FROM suppressions ORDER BY created DESC')],
            'integrations': {'places': bool(os.environ.get('GOOGLE_PLACES_API_KEY')), 'gmail': gmail.token_path().exists(),
                'hermes_model': os.environ.get('HERMES_MODEL', ''), 'send_enabled': os.environ.get('ALLOW_SEND', '').lower() == 'true'}}

def save_config(name, value):
    if name not in ('settings', 'strategy'):
        raise ValueError('Unknown configuration')
    (validate_settings if name == 'settings' else validate_strategy)(value)
    with LOCK, connect() as db:
        if db.execute("SELECT 1 FROM runs WHERE status='running'").fetchone():
            raise ValueError('Wait for the active run before changing campaign inputs')
        geography_changed = name == 'settings' and value['geography'] != config('settings')['geography']
        path = ROOT / 'config' / f'{name}.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(value, indent=2) + '\n')
        temp.replace(path)
        db.execute("UPDATE prospects SET status='review', approved_revision=NULL, approval_hash=NULL WHERE status='approved'")
        if geography_changed:
            db.execute("UPDATE prospects SET geography_verified=0,score=max(0,score-20) WHERE geography_verified=1 AND status IN ('review','rejected')")
        event(db, 'configuration', f'{name.title()} saved. Previous approvals invalidated.')

def start_run(mode):
    if mode not in ('demo', 'live'):
        raise ValueError('Choose demo or live')
    settings, strategy = config('settings'), config('strategy')
    if mode == 'live':
        errors = strategy_errors(strategy)
        if not os.environ.get('GOOGLE_PLACES_API_KEY'):
            errors.append('Google Places key is missing')
        if not os.environ.get('HERMES_MODEL'):
            errors.append('Hermes model is not configured')
        if errors:
            raise ValueError('; '.join(errors))
    with LOCK, connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM runs WHERE status='running'").fetchone():
            raise ValueError('A research run is already active')
        rid = uuid.uuid4().hex
        db.execute('INSERT INTO runs(id,mode,status,geography,created,settings,strategy) VALUES(?,?,?,?,?,?,?)',
            (rid, mode, 'running', settings['geography'], now(), json.dumps(settings), json.dumps(strategy)))
        event(db, 'run_started', f'{mode.title()} research started in {settings["geography"]}')
    threading.Thread(target=run, args=(rid, mode, settings, strategy), daemon=True).start()
    return rid

def run(rid, mode, settings, strategy):
    try:
        places = providers.demo_places(settings) if mode == 'demo' else providers.discover(settings)
        for place in places:
            # One provider website per mode across all campaigns; place IDs cover missing websites.
            dom = providers.domain(place['website'])
            dedupe = mode + ':' + (dom or place['place_id'])
            with connect() as db:
                if db.execute('SELECT 1 FROM prospects WHERE dedupe_key=?', (dedupe,)).fetchone():
                    event(db, 'duplicate_skipped', f'Skipped existing provider: {place["name"]}')
                    continue
            research = agents.research(place, strategy, mode)
            research['discovery_source'] = place['source']
            research['discovered_at'] = now()
            if mode == 'demo':
                selection = agents.demo_selection(research, strategy)
            elif not research['evidence'] or research['exclusions'] or research['score'] + 20 < settings['min_score']:
                selection = {'qa_pass': False, 'reason': 'Insufficient evidence or ICP mismatch; no model request made'}
            else:
                try:
                    selection = agents.hermes_selection(place, research, strategy)
                except Exception as exc:
                    selection = {'qa_pass': False, 'reason': str(exc)}
                    research['errors'].append(str(exc))
            research['agent_trace'] = selection.get('agent_trace', [])
            research['pain_hypothesis'] = selection.get('pain_hypothesis', research['pain_hypothesis'])
            draft = agents.compose(place, research, strategy, selection, settings)
            pid = uuid.uuid4().hex
            with LOCK, connect() as db:
                db.execute('''INSERT OR IGNORE INTO prospects(id,dedupe_key,run_id,mode,name,website,domain,email,email_source,address,score,status,research,draft,created)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (pid, dedupe, rid, mode, place['name'], place['website'], dom,
                    next(iter(research['emails']), ''), research['email_source'], place['address'], research['score'], 'review',
                    json.dumps(research), json.dumps(draft), now()))
                db.execute('UPDATE runs SET processed=processed+1 WHERE id=?', (rid,))
                event(db, 'researched', f'{place["name"]}: score {research["score"]}; ready for human review', pid)
        with connect() as db:
            db.execute("UPDATE runs SET status='completed' WHERE id=?", (rid,))
            event(db, 'run_completed', 'Research finished. No messages sent.')
    except Exception as exc:
        with connect() as db:
            db.execute("UPDATE runs SET status='failed',error=? WHERE id=?", (safe_error(exc), rid))
            event(db, 'run_failed', safe_error(exc))

def safe_error(exc):
    # Upstream HTTP errors may contain sensitive URLs. Store only a class for unexpected errors.
    return str(exc)[:500] if isinstance(exc, ValueError) else f'{type(exc).__name__}: provider operation failed; check configuration and connection'

def edit(pid, data):
    with LOCK, connect() as db:
        p = get(db, pid)
        if p['status'] in ('sending', 'sent', 'send_unknown', 'suppressed', 'replied'):
            raise ValueError('This record cannot be edited in its current state')
        if data.get('revision') != p['revision']:
            raise ValueError('This draft changed. Refresh before editing')
        subject, body = data.get('subject', ''), data.get('body', '')
        email, source = data.get('email', '').strip().lower(), data.get('email_source', '').strip()
        if not subject.strip() or len(subject) > 200 or '\r' in subject or '\n' in subject or not body.strip() or len(body) > 6000:
            raise ValueError('Provide a short subject and a body under 6,000 characters')
        if email and not guards.valid_email(email):
            raise ValueError('Invalid business email')
        verified = data.get('contact_verified') is True
        geo = data.get('geography_verified') is True
        if verified and (not source.startswith('https://') or not email):
            raise ValueError('A verified contact needs its HTTPS source and business email')
        draft = {**p['draft'], 'subject': subject, 'body': body, 'edited': True}
        score = max(0, min(100, p['research']['score'] + (20 if geo else 0)))
        db.execute('''UPDATE prospects SET draft=?,email=?,email_source=?,contact_verified=?,geography_verified=?,score=?,
            revision=revision+1,approved_revision=NULL,approval_hash=NULL,status='review' WHERE id=?''',
            (json.dumps(draft), email, source, int(verified), int(geo), score, pid))
        event(db, 'edited', 'Draft/contact updated; approval cleared', pid)

def approve(pid, data):
    if data.get('claims_verified') is not True:
        raise ValueError('Confirm you verified all claims against sources')
    with LOCK, connect() as db:
        p = get(db, pid)
        if p['status'] != 'review' or data.get('revision') != p['revision']:
            raise ValueError('Only the current review revision can be approved')
        s, strategy = config('settings'), config('strategy')
        reasons = guards.blockers(db, p, s, strategy)
        if reasons:
            raise ValueError('; '.join(reasons))
        db.execute("UPDATE prospects SET status='approved',approved_revision=revision,approval_hash=?,approved_at=? WHERE id=?",
            (guards.fingerprint(p, s, strategy), now(), pid))
        event(db, 'approved', f'Human approved revision {p["revision"]}; sending remains a separate action', pid)

def reject(pid):
    with LOCK, connect() as db:
        p = get(db, pid)
        if p['status'] not in ('review', 'approved'):
            raise ValueError('Only unsent review records can be rejected')
        db.execute("UPDATE prospects SET status='rejected',approval_hash=NULL,approved_revision=NULL WHERE id=?", (pid,))
        event(db, 'rejected', 'Human rejected draft', pid)

def regenerate(pid, data):
    with LOCK, connect() as db:
        p = get(db, pid)
        if p['status'] not in ('review', 'rejected', 'approved') or p['revision'] != data.get('revision'):
            raise ValueError('Refresh is only available for the current unsent draft')
        settings, strategy = config('settings'), config('strategy')
        if p['mode'] == 'live' and strategy_errors(strategy):
            raise ValueError('; '.join(strategy_errors(strategy)))
    place = {'name':p['name'], 'website':p['website']}
    research = agents.research(place, strategy, p['mode'])
    research['discovery_source'] = p['research'].get('discovery_source', '')
    research['discovered_at'] = p['research'].get('discovered_at', now())
    if p['mode'] == 'demo':
        selection = agents.demo_selection(research, strategy)
    elif research['score'] + 20 >= settings['min_score'] and research['evidence'] and not research['exclusions']:
        selection = agents.hermes_selection(place, research, strategy)
    else:
        selection = {'qa_pass':False, 'reason':'Insufficient current evidence or ICP mismatch'}
    research['agent_trace'] = selection.get('agent_trace', [])
    research['pain_hypothesis'] = selection.get('pain_hypothesis', research['pain_hypothesis'])
    draft = agents.compose(place, research, strategy, selection, settings)
    with LOCK, connect() as db:
        latest = get(db, pid)
        if latest['revision'] != p['revision'] or latest['status'] != p['status']:
            raise ValueError('Record changed during research. Refresh was discarded')
        if config('settings') != settings or config('strategy') != strategy:
            raise ValueError('Campaign inputs changed during research. Refresh was discarded')
        db.execute("""UPDATE prospects SET research=?,draft=?,score=?,status='review',revision=revision+1,
            contact_verified=0,geography_verified=0,approval_hash=NULL,approved_revision=NULL WHERE id=?""",
            (json.dumps(research),json.dumps(draft),research['score'],pid))
        event(db,'regenerated','Research and draft refreshed; verification and approval cleared',pid)

def suppress(db, p, reason):
    for key in {p['email'].lower(), p['domain'], p['email'].split('@')[-1].lower()} - {''}:
        db.execute('INSERT OR IGNORE INTO suppressions(key,reason,created) VALUES(?,?,?)', (key, reason, now()))
    db.execute("UPDATE prospects SET status='suppressed', approval_hash=NULL,approved_revision=NULL WHERE email=? OR domain=?",
        (p['email'], p['domain']))
    event(db, 'suppressed', reason, p['id'])

def reply(pid, text, source='manual', reply_id=None):
    if not isinstance(text, str) or not text.strip() or len(text) > 12000:
        raise ValueError('Reply must contain 1–12,000 characters')
    category, confidence = agents.classify(text)
    with LOCK, connect() as db:
        p = get(db, pid)
        reply_id = reply_id or uuid.uuid4().hex
        if db.execute('SELECT 1 FROM replies WHERE id=?', (reply_id,)).fetchone():
            return
        db.execute('INSERT INTO replies VALUES(?,?,?,?,?,?,?)', (reply_id, pid, text, category, confidence, source, now()))
        if category in ('opt_out', 'bounce'):
            suppress(db, p, f'{category} received via {source}')
        elif p['status'] == 'sent':
            db.execute("UPDATE prospects SET status='replied' WHERE id=?", (pid,))
        event(db, 'reply', f'Reply classified {category} ({confidence:.0%}); no automatic reply', pid)

def sync_replies():
    settings = config('settings')
    if gmail.profile().lower() != settings['sender_email'].lower():
        raise ValueError('Connected Gmail account does not match the official sender')
    with connect() as db:
        ps = [prospect(r) for r in db.execute('SELECT * FROM prospects WHERE gmail_thread IS NOT NULL')]
    count = 0
    for p in ps:
        thread = gmail.request('threads/' + p['gmail_thread'] + '?format=full')
        for message in thread.get('messages', []):
            if message['id'] == p['gmail_id'] or 'SENT' in message.get('labelIds', []):
                continue
            payload = message.get('payload', {})
            headers = {h['name'].lower(): h['value'] for h in payload.get('headers', [])}
            sender = parseaddr(headers.get('from', ''))[1].lower()
            if sender == settings['sender_email'].lower():
                continue
            text = gmail.body_text(payload) or message.get('snippet', '')
            if text.strip():
                reply(p['id'], text, 'gmail', message['id'])
                count += 1
    return count

def send(pid, data):
    if os.environ.get('ALLOW_SEND', '').lower() != 'true':
        raise ValueError('Sending is disabled. Enable ALLOW_SEND only after reviewing setup')
    if data.get('confirm_send') is not True:
        raise ValueError('Explicit send confirmation is required')
    # Fresh replies/opt-outs are processed before sending. Failure blocks sending.
    sync_replies()
    with LOCK:
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = get(db, pid)
            s, strategy = config('settings'), config('strategy')
            if p['status'] != 'approved' or data.get('revision') != p['revision'] or p['approved_revision'] != p['revision']:
                raise ValueError('Approve the current draft revision first')
            if p['approval_hash'] != guards.fingerprint(p, s, strategy):
                raise ValueError('Inputs changed after approval. Edit and reapprove the draft')
            reasons = guards.blockers(db, p, s, strategy, live=True)
            if reasons:
                raise ValueError('; '.join(reasons))
            did = uuid.uuid4().hex
            db.execute('INSERT INTO deliveries(id,prospect_id,recipient,domain,status,created) VALUES(?,?,?,?,?,?)',
                (did, pid, p['email'].lower(), p['domain'], 'sending', now()))
            db.execute("UPDATE prospects SET status='sending' WHERE id=?", (pid,))
            event(db, 'send_reserved', 'Single send attempt reserved; retries disabled', pid)
        try:
            result = gmail.send(p, s, did)
            if not result.get('id') or not result.get('threadId'):
                raise ValueError('Gmail response was incomplete')
            with connect() as db:
                db.execute("UPDATE deliveries SET status='sent',message_id=? WHERE id=?", (result['id'], did))
                db.execute("UPDATE prospects SET status='sent',gmail_id=?,gmail_thread=? WHERE id=?", (result['id'], result['threadId'], pid))
                event(db, 'sent', 'Approved email sent through Gmail', pid)
        except Exception:
            with connect() as db:
                db.execute("UPDATE deliveries SET status='unknown',error='Check Gmail manually before any further action' WHERE id=?", (did,))
                db.execute("UPDATE prospects SET status='send_unknown' WHERE id=?", (pid,))
                event(db, 'send_unknown', 'Delivery outcome uncertain. No retry will be attempted.', pid)
            raise ValueError('Send outcome uncertain. Check Gmail manually; automatic retries are blocked') from None
