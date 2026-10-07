import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from .config import strategy_errors
from .agents import strategy_digest

def fingerprint(p, settings, strategy):
    return hashlib.sha256(json.dumps({'draft': p['draft'], 'email': p['email'], 'revision': p['revision'],
        'contact_verified': p['contact_verified'], 'geography_verified': p['geography_verified'],
        'settings': settings, 'strategy': strategy}, sort_keys=True).encode()).hexdigest()

def valid_email(email):
    return bool(re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+', email)) and len(email) <= 254

def blockers(db, p, settings, strategy, live=False):
    out = []
    if p['mode'] == 'live':
        out += strategy_errors(strategy)
        if p['draft'].get('strategy_digest') != strategy_digest(strategy):
            out.append('Strategy changed; refresh research and draft before approval')
    if not valid_email(p['email']):
        out.append('A valid public business email is required')
    if not p['contact_verified']:
        out.append('Verify the business email and its source')
    if not p['geography_verified']:
        out.append('Confirm this provider serves the chosen geography')
    if p['score'] < settings['min_score']:
        out.append('Below the configured ICP fit threshold')
    if p['research'].get('exclusions'):
        out.append('Matches an ICP exclusion')
    if not p['draft'].get('qa_pass'):
        out.append('Agent QA has not passed')
    if not p['research']['evidence']:
        out.append('No retrieved website evidence')
    else:
        try:
            oldest = min(datetime.fromisoformat(e['retrieved_at']) for e in p['research']['evidence'])
            if datetime.now(timezone.utc) - oldest > timedelta(days=30):
                out.append('Evidence is over 30 days old; refresh research before approval')
        except (ValueError, KeyError, TypeError):
            out.append('Evidence timestamp is invalid; refresh research')
    text = p['draft']['subject'] + '\n' + p['draft']['body']
    if '\r' in p['draft']['subject'] or '\n' in p['draft']['subject']:
        out.append('Invalid subject header')
    if p['mode'] == 'live' and ('[' in text or ']' in text):
        out.append('Replace all draft placeholders')
    if any(x.lower() in text.lower() for x in strategy.get('prohibited_claims', []) if x):
        out.append('Draft contains a prohibited claim')
    if 'reply “no thanks”' not in p['draft']['body']:
        out.append('Keep the opt-out line in the draft')
    if p['mode'] == 'live':
        ids = {c['id'] for c in strategy['approved_claims']}
        if p['draft'].get('claim_id') not in ids:
            out.append('Draft claim no longer exists in approved strategy')
        claim = next((c for c in strategy['approved_claims'] if c['id'] == p['draft'].get('claim_id')), None)
        if claim and claim['text'] not in p['draft']['body']:
            out.append('Keep the selected approved claim verbatim in the draft')
        if strategy.get('cta') and strategy['cta'] not in p['draft']['body']:
            out.append('Keep the current approved call to action in the draft')
    keys = [p['email'].lower(), p['domain']]
    if '@' in p['email']:
        keys.append(p['email'].split('@')[1].lower())
    if any(db.execute('SELECT 1 FROM suppressions WHERE key=?', (key,)).fetchone() for key in keys if key):
        out.append('Contact or domain is suppressed')
    existing = db.execute("SELECT 1 FROM deliveries WHERE recipient=? OR prospect_id=?", (p['email'].lower(), p['id'])).fetchone()
    if existing:
        out.append('An outreach attempt already exists; never automatically retry')
    cutoff = (datetime.now(timezone.utc) - timedelta(days=settings['domain_cooldown_days'])).isoformat()
    if db.execute('SELECT 1 FROM deliveries WHERE domain=? AND created>=?', (p['domain'], cutoff)).fetchone():
        out.append('Domain cooldown is active')
    if '@' in p['email'] and db.execute('SELECT 1 FROM deliveries WHERE recipient LIKE ? AND created>=?', ('%@' + p['email'].split('@')[1], cutoff)).fetchone():
        out.append('Recipient domain cooldown is active')
    if live:
        if p['mode'] != 'live' or p['domain'].endswith('.example') or p['email'].endswith('.example'):
            out.append('Demo records cannot be sent')
        if not settings['domain_readiness_confirmed']:
            out.append('Confirm SPF, DKIM, DMARC and campaign readiness in Settings')
        if not valid_email(settings['sender_email']) or not settings['sender_name'] or not settings['postal_address']:
            out.append('Configure the official sender name, email and postal address')
        today = datetime.now(timezone.utc).date().isoformat()
        count = db.execute('SELECT count(*) FROM deliveries WHERE created>=?', (today,)).fetchone()[0]
        if count >= settings['daily_send_limit']:
            out.append('Daily send cap reached')
        if db.execute("SELECT 1 FROM replies r JOIN prospects p ON p.id=r.prospect_id WHERE r.category='bounce' AND p.mode='live'").fetchone():
            out.append('Bounce circuit breaker: review delivery health before further sending')
    return out
