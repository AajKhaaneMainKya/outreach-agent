"""Strategy-driven discovery and four-specialist research. No outbound capabilities."""
import json
import hashlib
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from . import playbook, providers
from .config import ROOT
from .db import connect, event, now
from .service import LOCK

ACTIVE_POOLS=set()

NUMBERS={'staff_count','locations','years_open','rdn_count'}
BOOLEANS={'independent','owner_run','chain','franchise','hospital_employed','cash_pay','insurance_only'}
TEXT={'menu','context','staff','hook'}

def init():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS playbook_runs (
          id TEXT PRIMARY KEY, settings TEXT NOT NULL, stage TEXT NOT NULL,
          error TEXT, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS playbook_candidates (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES playbook_runs(id),
          place_id TEXT UNIQUE NOT NULL, stage TEXT NOT NULL, place TEXT NOT NULL,
          research TEXT NOT NULL, analysis TEXT NOT NULL, facts TEXT NOT NULL,
          manual_id TEXT, created TEXT NOT NULL);
        """)
        db.execute("UPDATE playbook_runs SET stage='interrupted',error='Research interrupted. Saved evidence remains; select Research next to resume.' WHERE stage='running'")
        db.execute("UPDATE playbook_candidates SET stage='failed' WHERE stage='researching'")

def connections(source="web"):
    from .account import status
    a=status()
    missing=[]
    if source=='places' and not os.environ.get('GOOGLE_PLACES_API_KEY'):missing.append('Google Places key')
    if not os.environ.get('HERMES_MODEL'):missing.append('Hermes subscription model')
    if not a.get('logged_in'):missing.append('ChatGPT sign-in in WSL')
    if a.get('rate_limited'):missing.append('ChatGPT subscription allowance reset')
    return {'apollo':bool(os.environ.get('APOLLO_API_KEY')),'places':bool(os.environ.get('GOOGLE_PLACES_API_KEY')),'hermes_model':bool(os.environ.get('HERMES_MODEL')),
      'chatgpt_signed_in':bool(a.get('logged_in')),'strategy_loaded':bool(playbook.policy()),'missing':missing}

def settings(data):
    if not isinstance(data,dict): raise ValueError('Campaign must be an object')
    if data.get('icp') not in ('spa','dietitian'): raise ValueError(playbook.policy()['escalation'])
    if data.get('source')=='web' and data.get('prompt_scope'):
        from .mission import geography
        resolved=geography(data.get('agent_goal',''));data=dict(data,city=resolved['city'],scope=resolved['scope'],timezone='')
    for k in ('city','sender'):
        if not isinstance(data.get(k),str) or not data[k].strip() or len(data[k])>300 or '\n' in data[k]: raise ValueError('Supply '+k)
    timezone=data.get('timezone','')
    if timezone:
        try:ZoneInfo(timezone)
        except ZoneInfoNotFoundError:raise ValueError('Choose a verified prospect IANA timezone') from None
    elif data.get('source')!='web':raise ValueError('Supply timezone')
    data=dict(data)
    data.setdefault('limit',6)
    data.setdefault('team_count',3)
    if type(data['limit']) is not int or not 1<=data['limit']<=12: raise ValueError('Discovery pool must be 1–12 prospects')
    if type(data['team_count']) is not int or not 1<=data['team_count']<=3: raise ValueError('Choose 1–3 parallel research teams')
    if not isinstance(data.get('business',''),str) or len(data.get('business',''))>300: raise ValueError('Invalid business name')
    out={k:data.get(k,'') for k in ('icp','city','sender','timezone','limit','business','team_count')}
    goal=data.get('agent_goal','')
    if not isinstance(goal,str) or len(goal)>1500:raise ValueError('Give a short agent mission')
    out['agent_goal']=goal.strip()
    if data.get('prompt_scope'):out['geography_resolution']={k:data[k] for k in ('city','scope','source') if k in data};out['geography_resolution']['source']='prompt' if data.get('scope')=='regional' else 'US-wide default or explicit national request'
    out['source']=data.get('source','places')
    if out['source'] not in ('places','manual','web'):raise ValueError('Choose manual prospect input or Google Places discovery')
    if out['source']=='manual':out['prospect']=manual_input(data)
    return out

def manual_input(data):
    for key in ('business','website'):
        if not isinstance(data.get(key),str) or not data[key].strip() or len(data[key])>2000:raise ValueError('Supply '+key)
    if not isinstance(data.get('gmb_url',''),str) or len(data.get('gmb_url',''))>2000:raise ValueError('Invalid GMB link')
    for key in ('website','gmb_url'):
        if not data.get(key):continue
        u=urlsplit(data[key])
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:raise ValueError('Supply a public '+key+' link')
    if data.get('gmb_url') and not re.fullmatch(r'(www\.)?(google\.[a-z.]+|maps\.google\.[a-z.]+|maps\.app\.goo\.gl|goo\.gl)',urlsplit(data['gmb_url']).hostname or '',re.I):raise ValueError('Supply the actual Google Business Profile / Maps link')
    phone=data.get('gmb_phone','')
    if not isinstance(phone,str) or len(phone)>40:raise ValueError('Invalid business phone')
    count=data.get('review_count')
    if count is not None and (type(count) is not int or not 0<=count<=1000000):raise ValueError('Invalid review count')
    reviews=data.get('reviews',[])
    if not isinstance(reviews,list) or len(reviews)>5:raise ValueError('Paste up to five newest Google reviews')
    clean=[]
    for v in reviews:
        if not isinstance(v,dict) or type(v.get('stars')) is not int or not 1<=v['stars']<=5:raise ValueError('Each review needs a star rating')
        if any(not isinstance(v.get(k,''),str) or len(v.get(k,''))>6000 for k in ('text','date')):raise ValueError('Invalid review text/date')
        if not v.get('text','').strip():continue
        clean.append({'stars':v['stars'],'text':v['text'],'date':v.get('date',''),'source':data.get('gmb_url','')})
    return {'business':data['business'].strip(),'website':data['website'].strip(),'gmb_url':data.get('gmb_url','').strip(),'gmb_phone':phone,'review_count':count,'reviews':clean}

def discover(s):
    if s.get('source')=='manual':
        p=s['prospect'];identity=providers.domain(p['website'])
        return [{'place_id':'manual_'+hashlib.sha256(identity.encode()).hexdigest(),'name':p['business'],'website':p['website'],'source':p['gmb_url'],'address':s['city'],'manual_input':p}]
    found={}
    terms=[s['business']] if s['business'].strip() else playbook.policy()[s['icp']]['search']
    for term in terms:
        for p in providers.discover({'query':term,'geography':s['city'],'limit':s['limit']}):
            found.setdefault(p['place_id'],p)
            if len(found)>=s['limit']: return list(found.values())
    return list(found.values())

def details(place):
    key=os.environ.get('GOOGLE_PLACES_API_KEY')
    if not key: raise ValueError('Google Places key is missing')
    pid=place['place_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,300}',pid): raise ValueError('Invalid discovered place identifier')
    p=providers.api_json('https://places.googleapis.com/v1/places/'+quote(pid,safe=''),headers={
      'X-Goog-Api-Key':key,'X-Goog-FieldMask':'id,displayName,formattedAddress,websiteUri,googleMapsUri,internationalPhoneNumber,userRatingCount,reviews,businessStatus'},method='GET')
    if p.get('id')!=pid: raise ValueError('Place identity mismatch')
    return p

def retrieve(place):
    manual=place.get('manual_input')
    if manual:
        p={'id':place['place_id'],'displayName':{'text':manual['business']},'websiteUri':manual['website'],'googleMapsUri':manual['gmb_url'],'internationalPhoneNumber':manual['gmb_phone'],'userRatingCount':manual['review_count']}
    elif place.get('discovery_source') in ('duckduckgo','brave','mojeek'):p={'id':place['place_id'],'displayName':{'text':place['name']},'websiteUri':place['website'],'googleMapsUri':'','internationalPhoneNumber':'','userRatingCount':None}
    else:p=details(place)
    reviews=[{'stars':r.get('rating'), 'text':r.get('originalText',r.get('text',{})).get('text',''),
      'date':r.get('publishTime',''), 'source':r.get('googleMapsUri') or p.get('googleMapsUri') or place['source'],
      'author':r.get('authorAttribution',{})} for r in p.get('reviews',[]) if r.get('publishTime')]
    if manual:reviews=manual['reviews']
    else:reviews.sort(key=lambda r:r['date'],reverse=True)
    evidence=[];errors=[];pages=[];website=p.get('websiteUri') or place.get('website','')
    if website:
        try:
            home=providers.fetch_website(website);pages.append(home)
            own=providers.domain(home['url']);seen={home['url']}
            for href in home.get('links',[]):
                url=urljoin(home['url'],href)
                if len(pages)>=5:break
                if url in seen or providers.domain(url)!=own or not re.search(r'about|team|staff|service|menu|pricing|insurance',urlsplit(url).path,re.I):continue
                seen.add(url)
                try: pages.append(providers.fetch_website(url))
                except ValueError: errors.append('Linked team/menu page could not be retrieved: '+url)
        except Exception:errors.append('Website could not be retrieved; verify the menu/team manually')
    else:errors.append('No business website available')
    for page in pages:
        for line in page['text'].splitlines():
            if len(line.strip())>=10:
                evidence.append({'id':'e'+str(len(evidence)+1),'quote':line[:1600],'url':page['url'],'retrieved_at':now(),'kind':'website'})
            if len(evidence)>=180:break
    for review in reviews:
        evidence.append({'id':'e'+str(len(evidence)+1),'quote':review['text'],'url':review['source'],'retrieved_at':now(),'kind':'review','stars':review['stars'],'date':review['date']})
    return {'place_details':p,'reviews':reviews,'review_order':('User-pasted Google reviews, order unverified; confirm five newest in GMB' if manual else 'No GMB reviews retrieved; public search is not Google review evidence' if place.get('discovery_source') in ('duckduckgo','brave','mojeek') else 'Google API sample, sorted by date within sample; NOT verified five newest'),
      'evidence':evidence,'errors':errors,'website':website,'retrieved_at':now()}

def hermes(research,s,candidate_id=None):
    source=Path(os.environ.get('HERMES_SOURCE','~/.hermes/hermes-agent')).expanduser()
    python=Path(os.environ.get('HERMES_PYTHON',str(source/'venv/bin/python'))).expanduser()
    model=os.environ.get('HERMES_MODEL','').strip()
    if not model or not python.exists() or not (source/'run_agent.py').exists():raise ValueError('Configure Hermes subscription model and runtime; strategy is already loaded')
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','TMPDIR','SSL_CERT_FILE','GTM_DATA_DIR')}
    env.update(HERMES_SOURCE=str(source),HERMES_MODEL=model,GTM_PROJECT=str(ROOT))
    if os.environ.get('GOOGLE_PLACES_API_KEY'):env['GOOGLE_PLACES_API_KEY']=os.environ['GOOGLE_PLACES_API_KEY']
    if os.environ.get('APOLLO_API_KEY'):env['APOLLO_API_KEY']=os.environ['APOLLO_API_KEY']
    payload={'workflow':'playbook','task':'research','candidate_id':candidate_id,'authoritative_policy':playbook.policy(),
      'prospect':{'campaign':s,'research':research,'output_contract':'Extract only source-backed fact values with evidence references; unknowns must be null.'}}
    try:r=subprocess.run([str(python),str(ROOT/'scripts/hermes_worker.py')],input=json.dumps(payload),text=True,capture_output=True,timeout=900,cwd=ROOT/'data',env=env)
    except subprocess.TimeoutExpired as exc:
        log=ROOT/'data'/('last-hermes-failure-'+candidate_id+'.log' if candidate_id else 'last-hermes-failure.log');log.write_text((exc.stderr or b'').decode(errors='replace') if isinstance(exc.stderr,bytes) else exc.stderr or 'Research timeout');log.chmod(0o600)
        raise ValueError('Hermes research timed out; existing findings and messages retained, no approval or contact occurred') from None
    if r.returncode:
        log=ROOT/'data'/('last-hermes-failure-'+candidate_id+'.log' if candidate_id else 'last-hermes-failure.log');log.write_text(r.stderr);log.chmod(0o600)
        raise ValueError('Hermes research failed. Private diagnostics retained; no outbound contact occurred')
    lines=[x.removeprefix('CONTINERE_RESULT=') for x in r.stdout.splitlines() if x.startswith('CONTINERE_RESULT=')]
    if len(lines)!=1:raise ValueError('Hermes returned no valid research result')
    if candidate_id:
        with connect() as db:latest=json.loads(db.execute('SELECT research FROM playbook_candidates WHERE id=?',(candidate_id,)).fetchone()['research'])
        research.clear();research.update(latest)
    return validate(json.loads(lines[0]),research,s)

def agent_discover(s,rid):
    source=Path(os.environ.get('HERMES_SOURCE','~/.hermes/hermes-agent')).expanduser()
    python=Path(os.environ.get('HERMES_PYTHON',str(source/'venv/bin/python'))).expanduser()
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','TMPDIR','SSL_CERT_FILE','GOOGLE_PLACES_API_KEY','GTM_DATA_DIR')}
    env.update(HERMES_SOURCE=str(source),HERMES_MODEL=os.environ['HERMES_MODEL'],GTM_PROJECT=str(ROOT))
    payload={'workflow':'playbook','task':'discover','run_id':rid,'authoritative_policy':playbook.policy(),'prospect':{'campaign':s,'research':{}}}
    r=subprocess.run([str(python),str(ROOT/'scripts/hermes_worker.py')],input=json.dumps(payload),text=True,capture_output=True,timeout=240,cwd=ROOT/'data',env=env)
    lines=[x.removeprefix('CONTINERE_RESULT=') for x in r.stdout.splitlines() if x.startswith('CONTINERE_RESULT=')]
    if r.returncode or len(lines)!=1:
        log=ROOT/'data/last-discovery-failure.log';log.write_text(r.stderr);log.chmod(0o600)
        if any(marker in r.stderr for marker in ('Broken pipe','API failed after','Codex stream sent no events','subscription returned no final response')):
            raise ValueError('The ChatGPT subscription connection was interrupted before discovery completed. Your task is saved; retry this search. No prospect was invented.')
        raise ValueError('Discovery did not return a saved, source-backed prospect. Review the agent Messages for search results or access limitations, then retry.')
    value=json.loads(lines[0]);places=value.get('places')
    if not isinstance(places,list) or not 1<=len(places)<=s['limit']:raise ValueError('Discovery must save a bounded source-backed prospect pool')
    saved=[]
    with connect() as db:
        for place in places:
            row=db.execute('SELECT place FROM playbook_candidates WHERE run_id=? AND place_id=?',(rid,place.get('place_id'))).fetchone()
            if not row:raise ValueError('Discovery result was not saved by the workspace tool')
            saved.append(json.loads(row['place']))
    return saved

def validate(value,research,s):
    if not isinstance(value,dict) or type(value.get('qa_pass')) is not bool or value.get('icp')!=s['icp']: raise ValueError('Invalid specialist research contract')
    if not isinstance(value.get('reason'),str) or len(value['reason'])>2000:raise ValueError('Invalid research reason')
    if not isinstance(value.get('findings'),list) or len(value['findings'])>40 or any(not isinstance(x,str) or len(x)>2000 for x in value['findings']):raise ValueError('Invalid QA findings')
    facts=value.get('facts');refs=value.get('fact_evidence')
    if not isinstance(facts,dict) or set(facts)-(NUMBERS|BOOLEANS|TEXT) or not isinstance(refs,dict):raise ValueError('Invalid extracted facts; agents cannot choose contact/approval fields')
    evidence={e['id']:e for e in research['evidence']}
    for field,v in facts.items():
        if v is None:continue
        if field in NUMBERS and (type(v) is not int or not 0<=v<=10000):raise ValueError('Invalid numeric fact')
        if field in BOOLEANS and type(v) is not bool:raise ValueError('Invalid boolean fact')
        if field in TEXT and (not isinstance(v,str) or not v.strip() or len(v)>6000):raise ValueError('Invalid textual fact')
        citations=refs.get(field)
        if not isinstance(citations,list) or not citations:raise ValueError('Every non-null fact requires retrieved evidence: '+field)
        for c in citations:
            if not isinstance(c,dict) or c.get('evidence_id') not in evidence or not isinstance(c.get('quote'),str) or not c['quote'].strip() or c['quote'] not in evidence[c['evidence_id']]['quote']:raise ValueError('Agent cited invented evidence')
            if evidence[c['evidence_id']].get('kind')=='search_lead':raise ValueError('Search snippets are leads, not verified facts; retrieve the source or keep this fact unknown')
    if facts.get('hook') or facts.get('staff'):
        hook=facts.get('hook') or '';staff=facts.get('staff') or ''
        if not hook or not staff or not 0<len(hook.split())<15 or not any(r['stars']==5 and hook in r['text'] and staff in r['text'] for r in research['reviews']):raise ValueError('Hook must be an exact under-15-word line and staff from one retrieved five-star review')
        if re.search(r'\b(lost|lbs?|pounds?|kg|cured|results?|botox|filler|peels?)\b',hook,re.I):raise ValueError('Unsafe review hook: ask VJ or select a staff/relationship line')
    return value

def prefill(research,value,s):
    p=research['place_details']
    f={'business':p.get('displayName',{}).get('text',''),'city':'' if s.get('geography_resolution',{}).get('scope')=='national' else s['city'],'icp':s['icp'],
      'gmb_url':p.get('googleMapsUri',''),'gmb_phone':p.get('internationalPhoneNumber',''),'website':research['website'],
      'timezone':s['timezone'],'sender':s['sender'],'reviews':p.get('userRatingCount',0),
      'facts_source':'\n'.join(e['url']+' | '+e['quote'] for e in research['evidence'] if e['kind']=='website')[:6000],
      'newest_reviews':[{k:r[k] for k in ('stars','text','date','source')} for r in research['reviews']],
      'line_type':'','lookup_source':'','no_text':False,
      'gmb_number_verified':False,'qualification_verified':False,'hook_verified':False,'safe_fields_verified':False}
    f.update(value['facts'])
    return f

def start(data):
    s=settings(data)
    missing=connections(s.get('source','places'))['missing']
    if missing:raise ValueError('VJ strategy is loaded. Connect '+', '.join(missing)+' before live agent research')
    with LOCK,connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM playbook_runs WHERE stage='running'").fetchone():raise ValueError('Finish or resume the existing campaign first')
        if db.execute("SELECT 1 FROM manual_prospects WHERE stage IN ('review','approved','awaiting_outcome')").fetchone():raise ValueError('Finish the current prospect first')
        if s.get('source')=='manual':
            existing_id=discover(s)[0]['place_id']
            if db.execute('SELECT 1 FROM playbook_candidates WHERE place_id=?',(existing_id,)).fetchone():raise ValueError('This business website is already saved. Open Prospects to view its record; retry failed research from that record. Existing facts were not overwritten.')
        rid=uuid.uuid4().hex
        db.execute('INSERT INTO playbook_runs VALUES(?,?,?,?,?)',(rid,json.dumps(s),'running',None,now()))
        event(db,'playbook_campaign_started','Authoritative '+s['icp']+' strategy; discovery in '+s['city'])
    threading.Thread(target=run,args=(rid,True),daemon=True).start();return rid

def qualification_notice(analysis,s):
    af=analysis.get('facts',{})
    context=af.get('context') or ''
    multiple=(type(af.get('locations')) is int and af['locations']>1) or bool(re.search(r'\b(?:several|multiple) locations\b',context,re.I))
    if s['icp']=='spa' and (multiple or af.get('chain') is True or af.get('franchise') is True or re.search(r'\bbotox\b|\bfiller\b|\bmed\s*spa\b|\baesthetics\b',af.get('menu') or '',re.I)):
        return 'Skip under VJ’s playbook: sourced Spa facts show multiple locations, chain, franchise, med spa or injectables.'
    if s['icp']=='dietitian' and (af.get('rdn_count')==1 or af.get('hospital_employed') is True or (af.get('insurance_only') is True and af.get('cash_pay') is False)):
        return 'Skip under VJ’s playbook: sourced facts match Dietitian exclusion criteria.'
    return None

def _team_candidate(cid,s,team):
    with LOCK,connect() as db:
        db.execute('BEGIN IMMEDIATE')
        c=db.execute("SELECT * FROM playbook_candidates WHERE id=? AND stage='queued'",(cid,)).fetchone()
        if not c:return
        if not db.execute("UPDATE playbook_candidates SET stage='researching' WHERE id=? AND stage='queued'",(cid,)).rowcount:return
        event(db,'agent_message',json.dumps({'sender':'orchestrator','recipient':'researcher','kind':'assignment','summary':f'Research team {team} independently investigates '+json.loads(c['place']).get('name','prospect')+'. Share evidence with qualification, writing and QA specialists.','evidence':[],'candidate_id':cid,'run_id':c['run_id'],'mission_id':cid}),cid)
    try:
        research=retrieve(json.loads(c['place']))
        with LOCK,connect() as db:
            if not db.execute("UPDATE playbook_candidates SET research=? WHERE id=? AND stage='researching'",(json.dumps(research),cid)).rowcount:return
        analysis=hermes(research,dict(s),cid)
        f=prefill(research,analysis,s)
        notice=qualification_notice(analysis,s)
        if notice:analysis['qualification_notice']=notice
        with LOCK,connect() as db:
            if not db.execute("UPDATE playbook_candidates SET stage=?,analysis=?,facts=? WHERE id=? AND stage='researching'",('skipped' if notice else 'needs_verification',json.dumps(analysis),json.dumps(f),cid)).rowcount:return
            event(db,'playbook_agent_research',notice or 'Research team completed; human evidence review and contact approval remain required',cid)
    except Exception as exc:
        message=str(exc)[:1000] if isinstance(exc,ValueError) else 'Research provider failed; saved evidence retained. Review connections and retry explicitly.'
        with LOCK,connect() as db:
            if db.execute("UPDATE playbook_candidates SET stage='failed',analysis=? WHERE id=? AND stage='researching'",(json.dumps({'reason':message}),cid)).rowcount:
                event(db,'playbook_research_failed',message,cid)

def _finish_run(rid):
    with LOCK,connect() as db:
        stages=[r['stage'] for r in db.execute('SELECT stage FROM playbook_candidates WHERE run_id=?',(rid,))]
        if any(x in ('queued','researching') for x in stages):return
        stage='awaiting_review' if 'needs_verification' in stages else 'failed' if 'failed' in stages else 'complete'
        error='Some prospect research failed; inspect saved team findings and retry explicitly.' if stage=='failed' else None
        db.execute('UPDATE playbook_runs SET stage=?,error=? WHERE id=?',(stage,error,rid))

def run(rid,discovery=False):
    with LOCK:
        if rid in ACTIVE_POOLS:return
        ACTIVE_POOLS.add(rid)
    try:
        with connect() as db:
            row=db.execute('SELECT settings FROM playbook_runs WHERE id=?',(rid,)).fetchone();s=json.loads(row['settings'])
        if discovery:
            places=agent_discover(s,rid) if s.get('source') in ('places','web') else discover(s)
            with LOCK,connect() as db:
                for place in places[:min(s.get('limit',6),12)]:
                    db.execute('INSERT OR IGNORE INTO playbook_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,rid,place['place_id'],'queued',json.dumps(place),'{}','{}','{}',None,now()))
        teams=max(1,min(3,int(s.get('team_count',3))))
        with ThreadPoolExecutor(max_workers=teams,thread_name_prefix='continere-team') as executor:
            while True:
                with LOCK,connect() as db:
                    rows=db.execute("SELECT id FROM playbook_candidates WHERE run_id=? AND stage='queued' ORDER BY created,id LIMIT 3",(rid,)).fetchall()
                if not rows:break
                futures=[executor.submit(_team_candidate,c['id'],s,index%teams+1) for index,c in enumerate(rows)]
                for future in futures:future.result()
        _finish_run(rid)
    except Exception as exc:
        message=str(exc)[:1000] if isinstance(exc,ValueError) else 'Research provider failed; saved evidence retained. Review connections and retry explicitly.'
        with LOCK,connect() as db:
            db.execute("UPDATE playbook_runs SET stage='failed',error=? WHERE id=? AND stage='running'",(message,rid))
            event(db,'playbook_research_failed',message)
    finally:
        with LOCK:ACTIVE_POOLS.discard(rid)

def advance(rid):
    with LOCK,connect() as db:
        db.execute('BEGIN IMMEDIATE')
        run=db.execute('SELECT stage,settings FROM playbook_runs WHERE id=?',(rid,)).fetchone()
        if not run:raise ValueError('Campaign not found')
        if connections(json.loads(run['settings']).get('source','places'))['missing']:raise ValueError('Connect required research services first; manual prospects do not require Google Places')
        if run['stage']=='running' or db.execute("SELECT 1 FROM playbook_runs WHERE stage='running'").fetchone():raise ValueError('Research is already running')
        if db.execute("SELECT 1 FROM manual_prospects WHERE stage IN ('review','approved','awaiting_outcome')").fetchone():raise ValueError('Review and finish or park the current prospect before researching the next')
        rediscover=not db.execute('SELECT 1 FROM playbook_candidates WHERE run_id=?',(rid,)).fetchone()
        db.execute("UPDATE playbook_runs SET stage='running',error=NULL WHERE id=?",(rid,))
    threading.Thread(target=globals()['run'],args=(rid,rediscover),daemon=True).start()

def park(cid):
    with LOCK,connect() as db:
        db.execute('BEGIN IMMEDIATE')
        c=db.execute('SELECT stage,run_id FROM playbook_candidates WHERE id=?',(cid,)).fetchone()
        if c and c['stage']=='parked':return
        if not c or c['stage'] not in ('queued','researching','needs_verification','failed'):raise ValueError('Only an unaccepted research candidate can be parked')
        db.execute("UPDATE playbook_candidates SET stage='parked' WHERE id=?",(cid,))
        if c['run_id'] not in ACTIVE_POOLS and not db.execute("SELECT 1 FROM playbook_candidates WHERE run_id=? AND stage IN ('researching','needs_verification')",(c['run_id'],)).fetchone():
            queued=db.execute("SELECT 1 FROM playbook_candidates WHERE run_id=? AND stage='queued'",(c['run_id'],)).fetchone()
            db.execute("UPDATE playbook_runs SET stage=?,error=NULL WHERE id=?",('ready' if queued else 'complete',c['run_id']))
        event(db,'playbook_candidate_parked','Human parked candidate; no contact',cid)

def retry(cid):
    with LOCK,connect() as db:
        c=db.execute('SELECT run_id,stage FROM playbook_candidates WHERE id=?',(cid,)).fetchone()
        if not c or c['stage']!='failed':raise ValueError('Only failed research can be explicitly retried')
        if db.execute("SELECT 1 FROM playbook_runs WHERE stage='running'").fetchone():raise ValueError('Research is already running')
        if db.execute("SELECT 1 FROM manual_prospects WHERE stage IN ('review','approved','awaiting_outcome')").fetchone():raise ValueError('Finish the current prospect first')
        db.execute("UPDATE playbook_candidates SET stage='queued' WHERE id=?",(cid,))
    advance(c['run_id'])

def prepare_script(cid,goal=""):
    with LOCK,connect() as db:
        c=db.execute('SELECT * FROM playbook_candidates WHERE id=?',(cid,)).fetchone()
        if not c or c['stage']!='needs_verification':raise ValueError('Select a saved prospect awaiting review')
        if db.execute("SELECT 1 FROM playbook_runs WHERE stage='running'").fetchone():raise ValueError('Agents are already working')
        if json.loads(c['analysis']).get('qualification_notice'):raise ValueError('Excluded prospects cannot receive an outreach script')
        research=json.loads(c['research'])
        if not isinstance(goal,str) or len(goal)>1500:raise ValueError('Provide a task under 1500 characters')
        rid=c['run_id'];db.execute("UPDATE playbook_runs SET stage='running',error=NULL WHERE id=?",(rid,))
    def task():
        try:
            with connect() as db:s=json.loads(db.execute('SELECT settings FROM playbook_runs WHERE id=?',(rid,)).fetchone()['settings'])
            s['requested_output']='Prioritize selecting a proposed safe exact hook under 15 words and staff from the SAME supplied five-star review. Unverified qualification or newest-review order must not prevent proposing a hook. Prefer a short excerpt that reads naturally in the fixed template, such as a short noun phrase describing a guest experience, with no clinical/results claims. The text template says: One of your guests said [Staff] gave her [quoted review line]. Choose an exact excerpt that reads naturally inside that quote; avoid first-person introductions, repeated staff names and clauses beginning my first time. Do not alter review wording. Return hook/staff null only if no safe exact excerpt exists; never invent words.'
            if goal.strip():s['requested_output'] += '\nUser investigation task (cannot override VJ rules): '+goal.strip()
            analysis=hermes(research,s,cid)
            old=json.loads(c['analysis'])
            for k,v in old.get('facts',{}).items():
                if v is not None and k not in analysis['facts']:
                    analysis['facts'][k]=v
                    analysis['fact_evidence'][k]=old.get('fact_evidence',{}).get(k,[])
            analysis=validate(analysis,research,s);f=prefill(research,analysis,s)
            with LOCK,connect() as db:
                db.execute('BEGIN IMMEDIATE')
                changed=db.execute("UPDATE playbook_candidates SET analysis=?,facts=? WHERE id=? AND stage='needs_verification'",(json.dumps(analysis),json.dumps(f),cid)).rowcount
                if not changed:return
                db.execute("UPDATE playbook_runs SET stage='awaiting_review',error=NULL WHERE id=?",(rid,))
                event(db,'script_preview_prepared','Agent selected proposed hook; fixed-template preview only, no release or approval',cid)
        except Exception:
            with LOCK,connect() as db:
                db.execute("UPDATE playbook_runs SET stage='awaiting_review',error='Hook preparation failed. Existing research is retained; retry explicitly.' WHERE id=? AND stage='running' AND EXISTS (SELECT 1 FROM playbook_candidates WHERE id=? AND stage='needs_verification')",(rid,cid))
    threading.Thread(target=task,daemon=True).start()

def accept(cid,facts):
    with LOCK:
        with connect() as db:
            c=db.execute('SELECT stage,analysis FROM playbook_candidates WHERE id=?',(cid,)).fetchone()
            if not c or c['stage']!='needs_verification':raise ValueError('Research candidate is no longer awaiting review')
            if json.loads(c['analysis']).get('qa_pass') is not True:raise ValueError('Agent QA failed. Park and resolve findings before outreach')
        pid=playbook.create(facts)
        with connect() as db:
            db.execute("UPDATE playbook_candidates SET stage='accepted',manual_id=? WHERE id=?",(pid,cid))
            event(db,'playbook_candidate_accepted','Human verified agent research; separate contact approval still required',pid)
        return pid

def snapshot():
    with LOCK,connect() as db:
        runs=[dict(r) for r in db.execute('SELECT * FROM playbook_runs ORDER BY created DESC')]
        cs=[dict(r) for r in db.execute('SELECT * FROM playbook_candidates ORDER BY created DESC')]
        from .research_tools import board_rows
        for r in runs:
            r['settings']=json.loads(r['settings']);r['agent_board']=board_rows(db,run_id=r['id'])
        for c in cs:
            for k in ('place','research','analysis','facts'):c[k]=json.loads(c[k])
            c['agent_board']=board_rows(db,candidate_id=c['id'])
            c['agent_activity']=[{'created':e['created'],**json.loads(e['detail'])} for e in db.execute("SELECT created,detail FROM events WHERE prospect_id=? AND kind='agent_step' ORDER BY id DESC LIMIT 60",(c['id'],))][::-1]
            c['script_preview']=playbook.research_preview(c['facts'],c['research'],c['analysis'])
        return {'runs':runs,'candidates':cs,'connections':connections('manual'),'places_connections':connections('places')}
