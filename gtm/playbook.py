"""Authoritative fixed-template manual outreach. No outbound transport exists here."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .config import ROOT
from .db import connect, now, event
from .service import LOCK

SOURCE_SHA = '03c16e24995d0f362a277377b794c81f280e92ae3e7eb17df676ce875d20321b'

def policy():
    source = ROOT / 'knowledge/GMB-Outbound-Playbook-Spa-Dietitian.pdf'
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError('Authoritative PDF changed; review with VJ before proceeding')
    content = (ROOT / 'config/playbook.json').read_bytes()
    expected = (ROOT / 'knowledge/playbook-policy.sha256').read_text().strip()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError('Playbook policy changed; review and validate against PDF with VJ')
    result=json.loads(content)
    result['spa_classification_clarification']={
      'source_pages':[1,2,4],
      'massage_search_is_allowed':True,
      'facials_are_required':False,
      'notes':[
        'Massage spa is an explicit page-1 search term; massage services alone are not a Skip reason.',
        'Search terms are discovery routes, not proof of the independent-day-spa Who criteria.',
        'Facials-led Spa Jardin is a worked example, not a facials-only eligibility requirement.',
        'Check every Who threshold and the exact Skip row. Do not invent massage-only or bathhouse exclusions.',
        'If independent-day-spa status remains unclear from profile/menu evidence, leave it unverified and ask VJ.'
      ]}
    return result

def init():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS manual_prospects (
          id TEXT PRIMARY KEY, business_key TEXT UNIQUE NOT NULL, phone TEXT UNIQUE NOT NULL,
          facts TEXT NOT NULL, draft TEXT NOT NULL, stage TEXT NOT NULL,
          approval_hash TEXT, approved_action TEXT, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS manual_contacts (
          id INTEGER PRIMARY KEY, prospect_id TEXT NOT NULL REFERENCES manual_prospects(id),
          action TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS manual_logs (
          id INTEGER PRIMARY KEY, prospect_id TEXT NOT NULL REFERENCES manual_prospects(id),
          row TEXT NOT NULL, reply TEXT NOT NULL, created TEXT NOT NULL);
        """)

def number(value):
    n = re.sub(r'[^0-9]', '', str(value))
    if len(n) < 8 or len(n) > 15:
        raise ValueError('Enter the business GMB phone with country code')
    if len(n) == 10:
        raise ValueError('Include country code to deduplicate the business number')
    return '+' + n

def clean(data):
    if not isinstance(data, dict): raise ValueError('Prospect facts must be an object')
    required = ('business','city','gmb_url','icp','facts_source','menu')
    for k in required:
        if not isinstance(data.get(k), str) or not data[k].strip() or len(data[k]) > 6000:
            raise ValueError('Supply ' + k.replace('_',' '))
    if data['icp'] not in ('spa','dietitian'): raise ValueError(policy()['escalation'])
    if not data['gmb_url'].startswith('https://'): raise ValueError('Supply the HTTPS GMB profile URL')
    if data.get('qualification_verified') is not True: raise ValueError('Human verification required: qualification_verified')
    for k in ('reviews','staff_count','locations','years_open','rdn_count'):
        if type(data.get(k)) is not int or data[k] < 0: raise ValueError('Supply nonnegative ' + k)
    for k in ('independent','owner_run','chain','franchise','hospital_employed','cash_pay','insurance_only','no_text'):
        if type(data.get(k)) is not bool: raise ValueError('Supply true/false ' + k)
    data = dict(data)
    data['business_key'] = re.sub(r'\s+', ' ', (data['business']+'|'+data['city']).lower()).strip()
    if qualification(data)[0]=='skip':
        data['gmb_phone'] = number(data['gmb_phone']) if data.get('gmb_phone') else 'unknown:'+data['business_key']
        return data
    for k in ('gmb_phone','timezone','sender','website','context'):
        if not isinstance(data.get(k), str) or not data[k].strip() or len(data[k])>6000: raise ValueError('Supply '+k)
    try: ZoneInfo(data['timezone'])
    except ZoneInfoNotFoundError: raise ValueError('Use a verified IANA prospect timezone') from None
    for k in ('gmb_number_verified','hook_verified','safe_fields_verified'):
        if data.get(k) is not True: raise ValueError('Human verification required: ' + k)
    if data.get('line_type') not in ('landline','mobile','voip') or not data.get('lookup_source'):
        raise ValueError('Run line-type lookup first and supply its source')
    data['gmb_phone'] = number(data['gmb_phone'])
    return data

def qualification(f):
    p = policy()[f['icp']]
    if f['icp'] == 'spa':
        if f['chain'] or f['franchise'] or re.search(r'\bbotox\b|\bfiller\b|\bmed\s*spa\b|\baesthetics\b', f['menu'], re.I):
            return 'skip', p['skip']
        ok = f['independent'] and f['owner_run'] and f['locations']==1 and f['staff_count']>=3 and f['reviews']>=50 and f['years_open']>=2
    else:
        if f['rdn_count']==1 or f['hospital_employed'] or (f['insurance_only'] and not f['cash_pay']):
            return 'skip', p['skip']
        ok = f['rdn_count']>=3 and f['cash_pay'] and f['reviews']>=50
    return ('qualified','Verified Who criteria') if ok else ('skip','Does not satisfy Who: ' + p['who'])

def hooks(f):
    reviews = f.get('newest_reviews')
    if not isinstance(reviews,list) or len(reviews)!=5: raise ValueError('Paste the five newest reviews in newest-first order')
    for r in reviews:
        if not isinstance(r,dict) or not all(k in r for k in ('stars','text','date','source')):
            raise ValueError('Each review needs stars, verbatim text, ISO date and source')
        datetime.fromisoformat(r['date'])
    dates = [datetime.fromisoformat(r['date']).date() for r in reviews]
    if dates != sorted(dates,reverse=True): raise ValueError('Reviews must be newest first')
    hook = f.get('hook','')
    staff = f.get('staff','')
    if not isinstance(hook,str) or not 0<len(hook.split())<15: raise ValueError('Use an exact review line under 15 words')
    if not isinstance(staff,str) or not staff.strip(): raise ValueError('Select a named staff/dietitian hook; unsafe result hooks require VJ')
    matches = [r for r in reviews if r['stars']==5 and hook in r['text'] and staff in r['text']]
    if not matches: raise ValueError('Hook and named staff must occur verbatim in the same recent 5-star review')
    # No arbitrary drug blacklist can prove compliance: exact fields plus explicit human claim review.
    if re.search(r'\b(lost|lbs?|pounds?|kg|cured|results?|botox|filler|peels?)\b', hook, re.I):
        raise ValueError('Results/treatment hook is unsafe; choose a staff/relationship hook or ask VJ')
    for value in (f['business'],f['sender'],staff,hook):
        if any(x in value for x in ('[',']','\n','\r','http://','https://','continerehealth.com')):
            raise ValueError('Template fields must be plain single-line verified text')
    return hook,staff

def compose(f):
    hook,staff=hooks(f)
    return template_scripts(f,hook,staff)

def template_scripts(f,hook,staff):
    book=policy();p=book[f['icp']]
    def fill(s):
        # Separate adjacent PDF placeholders without changing either sourced value.
        s=s.replace('[Staff][review line]','[Staff] [review line]')
        for k,v in {'Name':f['sender'],'Staff':staff,'review line':hook,'Spa':f['business'],'Practice':f['business']}.items():
            s=s.replace('['+k+']',v)
        return s
    channel = 'call' if f.get('line_type')=='landline' or f.get('no_text') else 'text'
    return {'channel':channel, 'call':'\n\n'.join([fill(book['gatekeeper']),fill(book['review_open']),p['opener'],'Stop. Let them answer. Their answer is the pitch.',fill(p['pitch']),book['ask']]),
      'voicemail':fill(book['voicemail']), 'text1':fill(p['text1']), 'text2':fill(p['text2']),
      'money_line':book['money_line'], 'objections':p['objections'], 'question_call_only':p['reply'],
      'link':p['link'], 'programs':p['programs'], 'pain_hypothesis':p['pain'],
      'context_note':'Never name the rival med spa on the call.' if f['icp']=='spa' else 'Use verified insurance/cash-pay context.',
      'policy_digest':hashlib.sha256((ROOT/'config/playbook.json').read_bytes()).hexdigest()}

def research_preview(f,research,analysis):
    from .web_discovery import directory_source
    if directory_source(f.get('website','')):return {'available':False,'release_allowed':False,'reason':'Directory source, not an identified practice. Discovery must resolve a real practice website before drafting.'}
    if analysis.get('qualification_notice'):return {'available':False,'reason':'Excluded prospect: no outreach script.'}
    if analysis.get('qa_pass') is not True:return {'available':False,'reason':'Agent QA must pass before a draft is shown.'}
    hook=f.get('hook') or '';staff=f.get('staff') or ''
    if not hook or not staff:return {'available':False,'partial':True,'release_allowed':False,'reason':'Incomplete draft: an exact safe staff hook from a five-star GMB review is missing. No contact is authorized.','draft':template_scripts(f,'[review line]','[Staff]')}
    if not 0<len(hook.split())<15 or not any(v.get('stars')==5 and hook in v.get('text','') and staff in v.get('text','') for v in research.get('reviews',[])):return {'available':False,'reason':'Hook does not match a supplied five-star review.'}
    if re.search(r'\b(lost|lbs?|pounds?|kg|cured|results?|botox|filler|peels?)\b',hook,re.I):return {'available':False,'reason':'Unsafe hook: ask VJ or select a staff/relationship excerpt.'}
    for text in (f.get('business',''),f.get('sender',''),hook,staff):
        if any(x in text for x in ('[',']','\n','\r','http://','https://','continerehealth.com')):return {'available':False,'reason':'Template fields must be plain single-line text.'}
    draft=template_scripts(f,hook,staff)
    return {'available':True,'hook':hook,'staff':staff,'draft':draft,'release_allowed':False,'warning':'PREVIEW ONLY. Qualification, newest-review verification, GMB number, line type, local time and human approval remain required. Both channel templates are shown until line lookup is confirmed.'}

def get(db,pid):
    row=db.execute('SELECT * FROM manual_prospects WHERE id=?',(pid,)).fetchone()
    if not row: raise ValueError('Manual prospect not found')
    p=dict(row);p['facts']=json.loads(p['facts']);p['draft']=json.loads(p['draft']);return p

def digest(p,action):
    return hashlib.sha256(json.dumps({'facts':p['facts'],'draft':p['draft'],'action':action,'policy':policy()},sort_keys=True).encode()).hexdigest()

def suppressed(db,p):
    from urllib.parse import urlsplit
    domain=(urlsplit(p['facts'].get('website','')).hostname or '').lower().removeprefix('www.')
    if domain and db.execute('SELECT 1 FROM suppressions WHERE key=?',(domain,)).fetchone(): return True
    return db.execute('SELECT 1 FROM suppressions WHERE key IN (?,?)',(p['phone'],p['business_key'])).fetchone() is not None

def create(data):
    f=clean(data);state,reason=qualification(f)
    with LOCK,connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM manual_prospects WHERE stage IN ('review','approved','awaiting_outcome')").fetchone():
            raise ValueError('Finish or park the current prospect first: one prospect at a time')
        if db.execute('SELECT 1 FROM manual_prospects WHERE business_key=? OR phone=?',(f['business_key'],f['gmb_phone'])).fetchone():
            raise ValueError('Business or number already exists; use its saved record to retain lifetime history')
        d=compose(f) if state=='qualified' else {'reason':reason,'channel':'skip'}
        pid=uuid.uuid4().hex
        db.execute('INSERT INTO manual_prospects VALUES(?,?,?,?,?,?,?,?,?)',(pid,f['business_key'],f['gmb_phone'],json.dumps(f),json.dumps(d),'review' if state=='qualified' else 'skip',None,None,now()))
        event(db,'playbook_qualified',reason,pid)
        return pid

def edit(pid,data):
    f=clean(data);state,reason=qualification(f)
    d=compose(f) if state=='qualified' else {'reason':reason,'channel':'skip'}
    with LOCK,connect() as db:
        p=get(db,pid)
        if suppressed(db,p) or p['stage']=='suppressed': raise ValueError('Suppressed business cannot be edited back into outreach')
        if contacts(db,pid): raise ValueError('Contact history exists; retain original facts and ask VJ about any correction')
        if db.execute("SELECT 1 FROM manual_prospects WHERE id!=? AND stage IN ('review','approved','awaiting_outcome')",(pid,)).fetchone(): raise ValueError('Finish the other prospect first')
        if db.execute('SELECT 1 FROM manual_prospects WHERE id!=? AND (business_key=? OR phone=?)',(pid,f['business_key'],f['gmb_phone'])).fetchone(): raise ValueError('Business/number already recorded')
        db.execute('UPDATE manual_prospects SET business_key=?,phone=?,facts=?,draft=?,stage=?,approval_hash=NULL,approved_action=NULL WHERE id=?',(f['business_key'],f['gmb_phone'],json.dumps(f),json.dumps(d),'review' if state=='qualified' else 'skip',pid))
        event(db,'playbook_edited','Facts corrected; previous approval invalidated',pid)


def contacts(db,pid):
    return [dict(r) for r in db.execute('SELECT * FROM manual_contacts WHERE prospect_id=? ORDER BY id',(pid,))]

def blockers(db,p,action,at=None):
    reasons=[];f=p['facts'];d=p['draft'];policy()
    if suppressed(db,p): reasons.append('STOP / do-not-contact suppression: never contact again')
    if p['stage'] in ('skip','suppressed'): reasons.append('Prospect cannot be contacted')
    if f['icp']=='spa':
        dial_count=db.execute("SELECT count(*) FROM manual_contacts c JOIN manual_prospects p ON p.id=c.prospect_id WHERE json_extract(p.facts,'$.icp')='spa' AND c.action IN ('call','voicemail')").fetchone()[0]
        booked=db.execute("SELECT count(DISTINCT prospect_id) FROM manual_logs WHERE json_extract(row,'$.ICP')='spa' AND lower(json_extract(row,'$.Outcome'))='booked call'").fetchone()[0]
        if dial_count>=50 and booked<5: reasons.append('Spa scale/kill rule: under 5 bookings from 50 dials; park spas')
    if action not in ('call','voicemail','text1','text2'): return reasons+['Only prescribed call, voicemail, Text 1 or Text 2 are allowed. Question texts: ask VJ.']
    if action.startswith('text') and d['channel']!='text': reasons.append('Landline/no-text number: call only')
    if action in ('call','voicemail') and d['channel']!='call': reasons.append('Mobile/VoIP: manual text workflow')
    if qualification(f)[0]!='qualified': reasons.append('Qualification no longer passes')
    if d!=compose(f): reasons.append('Template changed: no alternatives or edited scripts allowed')
    at=at or datetime.now(timezone.utc)
    local=at.astimezone(ZoneInfo(f['timezone']))
    if not 8<=local.hour<20: reasons.append('Outside 8am–8pm prospect-local window')
    sent=contacts(db,p['id']);texts=[r for r in sent if r['action'].startswith('text')]
    if action.startswith('text'):
        if len(texts)>=2: reasons.append('Two texts maximum per business, ever')
        if any(r['action']==action for r in texts): reasons.append('This text was already handed over; never retry blindly')
        if action=='text1' and texts: reasons.append('Initial text already used')
        if action=='text2':
            if len(texts)!=1 or texts[0]['action']!='text1': reasons.append('Text 2 requires exactly one initial text')
            elif local.date() < datetime.fromisoformat(texts[0]['created']).astimezone(ZoneInfo(f['timezone'])).date()+timedelta(days=2):
                reasons.append('Follow up on day 3, counting initial contact as day 1')
            if db.execute("SELECT 1 FROM manual_logs WHERE prospect_id=? AND reply!=''",(p['id'],)).fetchone(): reasons.append('Any reply cancels the no-reply follow-up')
    return reasons

def approve(pid,data):
    if data.get('claims_reviewed') is not True: raise ValueError('Human must review all fields for drug names, results claims and in-clinic claims')
    action=data.get('action')
    with LOCK,connect() as db:
        p=get(db,pid)
        if p['stage']=='awaiting_outcome': raise ValueError('Record what happened before another contact')
        if db.execute("SELECT 1 FROM manual_prospects WHERE id!=? AND stage IN ('review','approved','awaiting_outcome')",(pid,)).fetchone():
            raise ValueError('Finish or park the other prospect first')
        bad=blockers(db,p,action)
        if bad: raise ValueError('; '.join(bad))
        db.execute("UPDATE manual_prospects SET stage='approved',approval_hash=?,approved_action=? WHERE id=?",(digest(p,action),action,pid))
        event(db,'playbook_approved','Human approved exact '+action+' template',pid)

def handover(pid,data):
    if data.get('manual_only') is not True: raise ValueError('Confirm manual phone contact; this server never sends texts or places calls')
    with LOCK,connect() as db:
        db.execute('BEGIN IMMEDIATE');p=get(db,pid);action=data.get('action')
        if p['stage']!='approved' or p['approved_action']!=action or p['approval_hash']!=digest(p,action): raise ValueError('Approve this exact action first')
        bad=blockers(db,p,action)
        if bad: raise ValueError('; '.join(bad))
        # Count release conservatively, even if human ultimately does not send. Never automatically retry.
        db.execute('INSERT INTO manual_contacts(prospect_id,action,created) VALUES(?,?,?)',(pid,action,now()))
        db.execute("UPDATE manual_prospects SET stage='awaiting_outcome',approval_hash=NULL WHERE id=?",(pid,))
        event(db,'manual_handover',action+' released for human contact; no network send',pid)
        return {'script':p['draft'][action], 'next':'Type/send by hand now within local window, then record what happened.'}

def outcome(pid,data):
    if isinstance(data.get('reply',''),str) and re.search(r'\bstop\b|do not contact|remove me|opt.out|unsubscribe',data.get('reply','')+' '+str(data.get('outcome','')),re.I):
        data=dict(data,outcome='STOP',next_step='Never contact again',due='None')
    for k in ('outcome','next_step','due'):
        if not isinstance(data.get(k),str) or not data[k].strip() or len(data[k])>2000: raise ValueError('Supply '+k)
    if data['outcome'].lower()=='booked call':
        try: datetime.fromisoformat(data['due'])
        except ValueError: raise ValueError('Booked call needs an ISO dated calendar slot; confirm 15 minutes in next step') from None
        if '15' not in data['next_step']: raise ValueError('Confirm the 15-minute calendar slot in next step')
    reply=data.get('reply','')
    if not isinstance(reply,str) or len(reply)>10000: raise ValueError('Invalid reply')
    with LOCK,connect() as db:
        p=get(db,pid);f=p['facts'];cs=contacts(db,pid)
        local=datetime.now(timezone.utc).astimezone(ZoneInfo(f.get('timezone') or 'UTC'))
        row={'Date':local.date().isoformat(),'Business':f['business'],'ICP':f['icp'],'Owner':data.get('owner','Unknown'), 'Review line':f.get('hook',''), 'Channel':p['draft']['channel'],'Outcome':data['outcome'],'Next step':data['next_step'],'Due':data['due']}
        stop=bool(re.search(r'\bstop\b|do not contact|remove me|opt.out|unsubscribe',reply+' '+data['outcome'],re.I))
        stage='suppressed' if stop else 'parked'
        if stop:
            from urllib.parse import urlsplit
            domain=(urlsplit(f.get('website','')).hostname or '').lower().removeprefix('www.')
            for key in filter(None,(p['phone'],p['business_key'],domain)): db.execute('INSERT OR IGNORE INTO suppressions VALUES(?,?,?)',(key,'Playbook STOP / do not contact',now()))
            row['Next step']='Never contact again';row['Due']='None'
            db.execute("UPDATE manual_prospects SET stage='suppressed',approval_hash=NULL WHERE phone=? OR business_key=?",(p['phone'],p['business_key']))
        elif cs and cs[-1]['action']=='text1' and not reply and data['outcome'].lower()=='no reply':
            due=datetime.fromisoformat(cs[-1]['created']).astimezone(ZoneInfo(f['timezone'])).date()+timedelta(days=2)
            row['Next step']='Manual Text 2 on day 3, only if still no reply; then stop';row['Due']=due.isoformat()
        db.execute('INSERT INTO manual_logs(prospect_id,row,reply,created) VALUES(?,?,?,?)',(pid,json.dumps(row),reply,now()))
        db.execute('UPDATE manual_prospects SET stage=?,approval_hash=NULL,approved_action=NULL WHERE id=?',(stage,pid))
        event(db,'playbook_outcome','STOP honored immediately' if stop else data['outcome'],pid)
        return row

def snapshot():
    with LOCK,connect() as db:
        ps=[get(db,r['id']) for r in db.execute('SELECT id FROM manual_prospects ORDER BY created DESC')]
        for p in ps:
            p['contacts']=contacts(db,p['id'])
            p['blockers']={a:blockers(db,p,a) for a in ('call','voicemail','text1','text2')} if p['stage']!='skip' else {}
        logs=[json.loads(r['row']) for r in db.execute('SELECT row FROM manual_logs ORDER BY id DESC')]
        answers=[r['reply'].strip().lower() for r in db.execute("SELECT l.reply FROM manual_logs l JOIN manual_prospects p ON p.id=l.prospect_id WHERE l.reply!='' AND json_extract(p.facts,'$.icp')='dietitian' AND l.id=(SELECT max(id) FROM manual_logs WHERE prospect_id=p.id AND reply!='') AND EXISTS(SELECT 1 FROM manual_contacts WHERE prospect_id=p.id AND action='call')")]
        repeated=sorted({a for a in answers if answers.count(a)>=3})
        spa_dials=sum(len([c for c in p['contacts'] if c['action'] in ('call','voicemail')]) for p in ps if p['facts']['icp']=='spa')
        spa_booked=db.execute("SELECT count(DISTINCT prospect_id) FROM manual_logs WHERE json_extract(row,'$.ICP')='spa' AND lower(json_extract(row,'$.Outcome'))='booked call'").fetchone()[0]
        return {'prospects':ps,'logs':logs,'policy':policy(),'signals':{'spa_dials':spa_dials,'spa_booked':spa_booked,'spa_park':spa_dials>=50 and spa_booked<5,'dietitian_repeated_answers':repeated,'dietitian':'Review logged between-visits answers; repeated answer on 3 calls becomes headline. Never change fixed outbound templates.'}}
