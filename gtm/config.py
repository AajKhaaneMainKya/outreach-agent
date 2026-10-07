import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('GTM_DATA_DIR', ROOT / 'data'))

def load_env():
    path = Path(os.environ.get('GTM_ENV_FILE', str(Path.home()/'.config/outreach-agent/runtime.env'))).expanduser()
    if not path.exists():path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def config(name):
    path = ROOT / 'config' / f'{name}.json'
    if not path.exists():
        path = ROOT / 'config' / f'{name}.example.json'
    return json.loads(path.read_text())

def strategy_errors(s):
    errors = []
    for key in ('positioning', 'confirmed_by', 'cta'):
        if not isinstance(s.get(key), str) or not s[key].strip():
            errors.append(f'Strategy needs {key.replace("_", " ")}')
    if not s.get('icp', {}).get('description'):
        errors.append('Define which rehab providers qualify')
    claims = s.get('approved_claims', [])
    if not claims:
        errors.append('Add at least one approved claim with its source')
    if any(not all(isinstance(c.get(k), str) and c[k].strip() for k in ('id', 'text', 'source')) for c in claims):
        errors.append('Every claim needs an id, text and source')
    if len({c.get('id') for c in claims}) != len(claims):
        errors.append('Claim IDs must be unique')
    return errors

def validate_settings(s):
    if not isinstance(s, dict):
        raise ValueError('Settings must be an object')
    base = config('settings')
    if set(s) != set(base):
        raise ValueError('Keep all settings fields; unknown fields are not allowed')
    for key, low, high in [('limit', 1, 25), ('min_score', 0, 100), ('daily_send_limit', 1, 20), ('domain_cooldown_days', 1, 365)]:
        if type(s[key]) is not int or not low <= s[key] <= high:
            raise ValueError(f'{key} must be {low}–{high}')
    for key in ('geography', 'query', 'sender_email', 'sender_name', 'postal_address'):
        if not isinstance(s[key], str) or len(s[key]) > 500 or '\r' in s[key] or '\n' in s[key]:
            raise ValueError(f'Invalid {key}')
    if not s['geography'].strip() or not s['query'].strip():
        raise ValueError('Geography and query are required')
    if type(s['domain_readiness_confirmed']) is not bool:
        raise ValueError('Domain readiness must be true or false')

def validate_strategy(s):
    if not isinstance(s, dict) or s.get('company') != 'Continere':
        raise ValueError('Company must be Continere')
    for k in ('version', 'confirmed_by', 'positioning', 'cta'):
        if not isinstance(s.get(k), str) or len(s[k]) > 3000:
            raise ValueError(f'Invalid strategy {k}')
    icp = s.get('icp', {})
    if icp.get('id') != 'rehab-providers' or not isinstance(icp.get('description'), str):
        raise ValueError('This POC supports the rehab-providers ICP')
    for obj, keys in [(s, ('pain_hypotheses', 'prohibited_claims')), (icp, ('include_terms', 'exclude_terms', 'buyer_roles'))]:
        for k in keys:
            if not isinstance(obj.get(k), list) or any(not isinstance(v, str) or len(v) > 1000 for v in obj[k]):
                raise ValueError(f'{k} must be a list of short strings')
    if not isinstance(s.get('approved_claims'), list) or len(s['approved_claims']) > 30:
        raise ValueError('Provide at most 30 approved claims')
    for c in s['approved_claims']:
        if not isinstance(c, dict) or any(not isinstance(c.get(k), str) for k in ('id', 'text', 'source')):
            raise ValueError('Claims need id, text, source strings')

