"""Apollo contact leads only. No approval, outbound, personal email or phone reveal."""
import datetime
from contextlib import contextmanager
import ipaddress
import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from .config import DATA

BASE = 'https://api.apollo.io/api/v1/'
class ApolloError(ValueError):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApolloError('Apollo redirect refused; credentials were not forwarded')

def business_domain(value):
    if not isinstance(value, str): raise ApolloError('Provide a business website or domain')
    u = urllib.parse.urlsplit(value if '://' in value else 'https://' + value)
    host = (u.hostname or '').lower().removeprefix('www.')
    if u.scheme not in ('http', 'https') or u.username or u.password or u.port not in (None, 80, 443):
        raise ApolloError('Use a business domain on a standard HTTP(S) port')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}', host) or '..' in host:
        raise ApolloError('Use a valid public business domain')
    if host.endswith(('.local', '.localhost', '.example', '.test', '.invalid')):
        raise ApolloError('Use a real public business domain')
    try: ipaddress.ip_address(host)
    except ValueError: return host
    raise ApolloError('IP addresses are not business domains')

def request(endpoint, body=None):
    if endpoint not in ('auth/health', 'mixed_people/api_search', 'people/match'):
        raise ApolloError('Unsupported Apollo operation')
    key = os.environ.get('APOLLO_API_KEY', '').strip()
    if not key: raise ApolloError('Save APOLLO_API_KEY in the private WSL runtime.env')
    req = urllib.request.Request(BASE + endpoint,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'x-api-key': key, 'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST' if body is not None else 'GET')
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=25) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000: raise ApolloError('Apollo response exceeded the size limit')
        result = json.loads(raw)
        if not isinstance(result, dict): raise ApolloError('Apollo returned an unexpected response')
        return result
    except urllib.error.HTTPError as exc:
        messages = {401:'Apollo rejected the key',403:'Apollo endpoint is unavailable for this key or account',
                    429:'Apollo rate limit reached; no automatic retry'}
        raise ApolloError(messages.get(exc.code, 'Apollo request failed (HTTP %s)' % exc.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        if isinstance(exc, ApolloError): raise
        raise ApolloError('Apollo connection or response failed; no automatic retry') from None

@contextmanager
def store():
    directory = DATA / 'apollo'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = directory / 'contacts.sqlite3'
    db = sqlite3.connect(path, timeout=20)
    path.chmod(0o600)
    db.execute('CREATE TABLE IF NOT EXISTS contacts (id TEXT, domain TEXT, data TEXT, PRIMARY KEY(id,domain))')
    db.execute('CREATE TABLE IF NOT EXISTS attempts (day TEXT, person_id TEXT, domain TEXT)')
    try:
        with db:
            yield db
    finally:
        db.close()

def clean_person(person, domain, enriched=False):
    org = person.get('organization') or {}
    raw_domain = org.get('primary_domain') or org.get('website_url') or ''
    try: matched = business_domain(raw_domain) == domain
    except ValueError: matched = False
    item = {'person_id': str(person.get('id') or person.get('person_id') or '')[:100],
            'name': str(person.get('name') or ' '.join(filter(None, [person.get('first_name'), person.get('last_name') or person.get('last_name_obfuscated')])) or 'Name unavailable')[:200],
            'title': str(person.get('title') or '')[:200], 'organization': str(org.get('name') or '')[:200],
            'business_domain': domain, 'organization_domain': raw_domain[:300],
            'current_employer_domain_matches': matched, 'has_email': bool(person.get('has_email')),
            'email': '', 'email_status': '', 'source': 'Apollo',
            'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'no_approval': True, 'no_contact': True,
            'verification': 'Apollo lead; verify current employment and role. Not ICP, GMB or review proof.'}
    if enriched:
        email = person.get('email') or ''
        # Never publish placeholder, personal-domain or mismatched-company addresses.
        if matched and person.get('email_status') == 'verified' and re.fullmatch(r'[^\s@<>]+@[^\s@<>]+', email) and email.split('@')[1].lower() == domain:
            item['email'] = email
            item['email_status'] = 'Apollo verified; human outreach approval still required'
    return item

def search(website, titles=None, limit=5):
    domain = business_domain(website)
    if type(limit) is not int or not 1 <= limit <= 10: raise ApolloError('Search limit must be 1–10')
    titles = titles or ['owner', 'founder', 'practice manager']
    if not isinstance(titles, list) or not 1 <= len(titles) <= 8 or any(not isinstance(t,str) or not t.strip() or len(t)>100 for t in titles):
        raise ApolloError('Provide up to eight short role titles')
    result = request('mixed_people/api_search', {'q_organization_domains_list':[domain],
        'person_titles': titles, 'include_similar_titles':False, 'page':1, 'per_page':limit})
    people = result.get('people', [])
    if not isinstance(people, list): raise ApolloError('Apollo returned an unexpected people list')
    items = [clean_person(p, domain) for p in people[:limit] if isinstance(p,dict)]
    with store() as db:
        for item in items:
            if item['person_id']:
                db.execute("INSERT INTO contacts VALUES(?,?,?) ON CONFLICT(id,domain) DO UPDATE SET data=excluded.data WHERE coalesce(json_extract(contacts.data, '$.email'),'')=''" ,
                    (item['person_id'], domain, json.dumps(item)))
    return {'contacts':items, 'source':'Apollo People API Search', 'business_domain':domain,
            'credit_usage':'Search endpoint documented as zero credits; account eligibility applies',
            'no_approval':True, 'no_contact':True, 'note':'Search omits emails and phones; name may be obscured. Domain filter can include former employers.'}

def enrich(person_id, website, confirm_credit_use=False):
    domain = business_domain(website)
    if confirm_credit_use is not True or os.environ.get('ALLOW_APOLLO_ENRICHMENT','false').lower()!='true':
        raise ApolloError('Email enrichment is off. Enable ALLOW_APOLLO_ENRICHMENT privately and explicitly confirm credit use')
    try: limit = int(os.environ.get('APOLLO_DAILY_ENRICHMENT_LIMIT','5'))
    except ValueError: raise ApolloError('Daily enrichment limit must be an integer') from None
    if not 1 <= limit <= 20: raise ApolloError('Daily enrichment limit must be 1–20')
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    with store() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT data FROM contacts WHERE id=? AND domain=?',(person_id,domain)).fetchone()
        if not row: raise ApolloError('Choose a person ID returned by a saved Apollo search for this business')
        previous=json.loads(row[0])
        if previous.get('email'): return previous
        if db.execute('SELECT count(*) FROM attempts WHERE day=?',(today,)).fetchone()[0]>=limit:
            raise ApolloError('Local daily enrichment attempt cap reached')
        # Reserve before network request, including failures, to avoid overspending across teams.
        db.execute('INSERT INTO attempts VALUES(?,?,?)',(today,person_id,domain))
    result=request('people/match', {'id':person_id,'domain':domain,'reveal_personal_emails':False,
        'reveal_phone_number':False,'run_waterfall_email':False,'run_waterfall_phone':False})
    person=result.get('person')
    if not isinstance(person,dict): raise ApolloError('Apollo returned no matching person')
    item=clean_person(person,domain,enriched=True)
    if item['person_id']!=person_id: raise ApolloError('Apollo returned a different person; result not saved')
    with store() as db: db.execute('UPDATE contacts SET data=? WHERE id=? AND domain=?',(json.dumps(item),person_id,domain))
    return item

def health():
    result=request('auth/health')
    return {'configured':True, 'healthy':result.get('healthy') is True,
            'authenticated':result.get('is_logged_in') is True, 'no_contact':True}
