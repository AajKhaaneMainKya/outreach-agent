import json
import hashlib
import os
import re
import subprocess
from pathlib import Path
from .config import ROOT
from .db import now
from .providers import fetch_website

def research(place, strategy, mode):
    errors = []
    if mode == 'demo':
        page = {'url': place['website'], 'text': 'Our rehabilitation team offers physical therapy and outpatient rehabilitation.\nContact our clinic to learn about our services.', 'emails': [f"hello@{place['website'].split('//')[1]}"]}
    elif place['website']:
        try:
            page = fetch_website(place['website'])
        except Exception as exc:
            errors.append(str(exc)[:200])
            page = {'url': place['website'], 'text': '', 'emails': []}
    else:
        page = {'url': '', 'text': '', 'emails': []}
        errors.append('No website supplied by discovery provider')
    evidence = [{'id': f'e{i+1}', 'quote': line[:260], 'url': page['url'], 'retrieved_at': now()}
        for i, line in enumerate(page['text'].splitlines()) if len(line.strip()) >= 20][:45]
    corpus = page['text'].lower()
    matches = [t for t in strategy['icp']['include_terms'] if t.lower() in corpus]
    exclusions = [t for t in strategy['icp']['exclude_terms'] if t.lower() in corpus]
    # A discovery query is not proof of geography, budget, intent, or pain.
    parts = {'rehab_service_evidence': 50 if matches else 0, 'website_retrieved': 20 if page['text'] else 0,
        'public_business_email': 10 if page['emails'] else 0, 'geography_human_verified': 0, 'excluded': -100 if exclusions else 0}
    score = max(0, min(100, sum(parts.values())))
    return {'evidence': evidence, 'matches': matches, 'exclusions': exclusions, 'score_parts': parts,
        'score': score, 'emails': page['emails'], 'email_source': page['url'], 'errors': errors,
        'confidence': 'medium' if matches else 'low', 'pain_hypothesis': 'Unknown; requires discovery conversation',
        'qualification': 'candidate' if matches and not exclusions else 'needs_review'}

def demo_selection(research, strategy):
    evidence = next((e for e in research['evidence'] if 'rehab' in e['quote'].lower()), None)
    claims = strategy.get('approved_claims', [])
    return {'evidence_id': evidence['id'] if evidence else '', 'claim_id': claims[0]['id'] if claims else '',
        'reason': 'Demo selection only. Live mode uses Hermes specialist delegation.', 'qa_pass': True,
        'pain_hypothesis': 'Unknown; requires discovery conversation', 'agent_trace': ['Research fixture', 'Qualification fixture', 'Draft fixture', 'QA fixture']}

def hermes_selection(place, research, strategy):
    source = Path(os.path.expanduser(os.environ.get('HERMES_SOURCE', '~/.hermes/hermes-agent')))
    python = Path(os.path.expanduser(os.environ.get('HERMES_PYTHON', str(source / 'venv/bin/python'))))
    if not python.exists() or not (source / 'run_agent.py').exists():
        raise ValueError('Configure HERMES_SOURCE and HERMES_PYTHON to your Hermes installation')
    model = os.environ.get('HERMES_MODEL', '').strip()
    if not model:
        raise ValueError('Set HERMES_MODEL to a model available in your Hermes subscription provider')
    payload = {'place': place, 'research': research, 'strategy': strategy}
    # Credentials for Places/Gmail and dashboard approval tokens never enter the worker environment.
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'LANG', 'TMPDIR', 'SSL_CERT_FILE')}
    env.update({'HERMES_SOURCE': str(source), 'HERMES_MODEL': model, 'GTM_PROJECT': str(ROOT)})
    try:
        result = subprocess.run([str(python), str(ROOT / 'scripts/hermes_worker.py')], input=json.dumps(payload),
            text=True, capture_output=True, timeout=240, cwd=ROOT / 'data', env=env)
    except subprocess.TimeoutExpired:
        raise ValueError('Hermes timed out; no draft approved or sent') from None
    if result.returncode:
        # Avoid copying provider diagnostics/tokens into dashboard or audit logs.
        raise ValueError('Hermes failed. Verify subscription login and model; see the local setup guide')
    lines = [line[len('CONTINERE_RESULT='):] for line in result.stdout.splitlines() if line.startswith('CONTINERE_RESULT=')]
    if len(lines) != 1:
        raise ValueError('Hermes returned no valid structured result')
    out = json.loads(lines[0])
    validate_selection(out, research, strategy)
    return out

def validate_selection(out, research, strategy):
    if not isinstance(out, dict) or type(out.get('qa_pass')) is not bool:
        raise ValueError('Invalid agent QA result')
    if out.get('evidence_id') not in {e['id'] for e in research['evidence']}:
        raise ValueError('Agent cited evidence that was not retrieved')
    if out.get('claim_id') not in {c['id'] for c in strategy['approved_claims']}:
        raise ValueError('Agent selected an unapproved claim')
    for key in ('reason', 'pain_hypothesis'):
        if not isinstance(out.get(key), str) or len(out[key]) > 1500:
            raise ValueError(f'Invalid agent {key}')

def compose(place, research, strategy, selection, settings):
    ev = next((e for e in research['evidence'] if e['id'] == selection.get('evidence_id')), None)
    claim = next((c for c in strategy['approved_claims'] if c['id'] == selection.get('claim_id')), None)
    # Deliberately constrained assembly: model prose never becomes an outbound factual claim.
    observation = f'I noticed this on your website: “{ev["quote"]}”' if ev else '[Select verified provider evidence]'
    body = '\n\n'.join(['Hello,', observation, claim['text'] if claim else '[Add a user-approved Continere proposition]',
        strategy.get('cta') or '[Add an approved call to action]',
        settings.get('sender_name') or '[Sender name]', 'Continere', settings.get('postal_address') or '[Postal address]',
        'If this is not relevant, reply “no thanks” and I will not contact you again.'])
    return {'subject': f'A question for {place["name"]}', 'body': body, 'evidence_id': ev['id'] if ev else '',
        'claim_id': claim['id'] if claim else '', 'qa_pass': selection.get('qa_pass', False),
        'reason': selection.get('reason', ''), 'edited': False,
        'strategy_digest': strategy_digest(strategy)}

def strategy_digest(strategy):
    return hashlib.sha256(json.dumps(strategy, sort_keys=True).encode()).hexdigest()

def classify(text):
    # Ignore common quoted history so our own opt-out footer is not treated as a reply.
    current = re.split(r'(?im)^\s*(?:on .{5,200}wrote:|from:|[-]{2,}\s*original message)', text)[0]
    current = '\n'.join(line for line in current.splitlines() if not line.lstrip().startswith('>'))
    t = re.sub(r'\s+', ' ', current.lower()).strip()
    # Conservative suppression wins over every positive signal; false positives can be reviewed.
    if re.search(r'\bstop\b', t):
        return 'opt_out', 1.0
    if any(x in t for x in ('unsubscribe', 'remove me', 'remove us', 'stop emailing', 'stop contacting', 'do not contact', "don't contact", 'no thanks', 'not interested', 'opt out', 'opt-out')):
        return 'opt_out', 1.0
    if any(x in t for x in ('undeliverable', 'delivery failed', 'address not found', 'mailbox unavailable', 'delivery status notification')):
        return 'bounce', .95
    if any(x in t for x in ('out of office', 'automatic reply', 'on leave', 'auto-reply')):
        return 'out_of_office', .9
    if any(x in t for x in ('sounds interesting', 'send more', 'learn more', 'schedule a call', 'let’s talk', "let's talk", 'interested')):
        return 'interested', .7
    return 'needs_review', .3
