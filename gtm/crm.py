"""Small CRM and permission-based requested follow-up. Never cold sends."""
import hashlib, json, os, re, string, uuid
from datetime import datetime, timezone, timedelta
from email.utils import parseaddr
from .config import config
from .db import connect, now, event
from .service import LOCK
from . import gmail, guards

STAGES=('new','contacted','interested','booked','closed','suppressed')
STOP=re.compile(r'\b(stop|unsubscribe)\b|do not (?:email|contact)|remove me|opt.?out',re.I)

def init():
 with connect() as db:
  db.executescript("""
  CREATE TABLE IF NOT EXISTS crm_contacts (
   id TEXT PRIMARY KEY, source_key TEXT UNIQUE NOT NULL, source_kind TEXT, source_id TEXT,
   business TEXT NOT NULL, icp TEXT NOT NULL, website TEXT NOT NULL DEFAULT '',
   name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT 'new',
   consent TEXT NOT NULL DEFAULT '{}', next_action TEXT NOT NULL DEFAULT '', due TEXT NOT NULL DEFAULT '',
   notes TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, updated TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS crm_emails (
   id TEXT PRIMARY KEY, contact_id TEXT NOT NULL REFERENCES crm_contacts(id), subject TEXT NOT NULL,
   body TEXT NOT NULL, stage TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, approval_hash TEXT,
   created TEXT NOT NULL, gmail_id TEXT, gmail_thread TEXT, error TEXT, request_id TEXT, template_hash TEXT);
  CREATE TABLE IF NOT EXISTS crm_activity (
   id TEXT PRIMARY KEY, contact_id TEXT NOT NULL REFERENCES crm_contacts(id), kind TEXT NOT NULL,
   detail TEXT NOT NULL, created TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS crm_settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
  """)
  columns={row['name'] for row in db.execute('PRAGMA table_info(crm_emails)')}
  for column in ('request_id','template_hash'):
   if column not in columns:db.execute('ALTER TABLE crm_emails ADD COLUMN '+column+' TEXT')
  db.execute("UPDATE crm_emails SET stage='unknown',approval_hash=NULL,error='Restart during send. Check Gmail; do not retry.' WHERE stage='sending'")

def settings(db):
 row=db.execute('SELECT value FROM crm_settings WHERE id=1').fetchone()
 if row:return json.loads(row[0])
 s=config('settings')
 return {'sender_email':s['sender_email'],'sender_name':s['sender_name'],'postal_address':s['postal_address'],
  'domain_ready':False,'daily_limit':5,'subject_template':'','body_template':'','approved_by':'','template_source':''}

def text(data,key,limit=1000,required=False):
 v=data.get(key,'')
 if not isinstance(v,str) or len(v)>limit or (required and not v.strip()):raise ValueError('Invalid '+key.replace('_',' '))
 return v.strip()

def single(data,key,limit=200,required=False):
 v=text(data,key,limit,required)
 if '\n' in v or '\r' in v:raise ValueError('Use one line for '+key)
 return v

def activity(db,cid,kind,detail):
 db.execute('INSERT INTO crm_activity VALUES(?,?,?,?,?)',(uuid.uuid4().hex,cid,kind,detail,now()))

def get(db,cid):
 row=db.execute('SELECT * FROM crm_contacts WHERE id=?',(cid,)).fetchone()
 if not row:raise ValueError('CRM contact not found')
 p=dict(row);p['consent']=json.loads(p['consent']);return p

def domain(p):
 from .providers import domain as host
 return host(p['website']) or (p['email'].split('@')[-1].lower() if '@' in p['email'] else '')

def suppressed(db,p):
 keys=list(filter(None,[p['email'].lower(),domain(p)]))
 if p['source_kind']=='manual':
  row=db.execute('SELECT phone,business_key,stage FROM manual_prospects WHERE id=?',(p['source_id'],)).fetchone()
  if row:
   keys += [row['phone'],row['business_key']]
   if row['stage']=='suppressed':return True
 return p['stage']=='suppressed' or any(db.execute('SELECT 1 FROM suppressions WHERE key=?',(k,)).fetchone() for k in keys)

def invalidate(db,cid):
 db.execute("UPDATE crm_emails SET stage='draft',approval_hash=NULL WHERE contact_id=? AND stage='approved'",(cid,))

def create(data):
 source_kind=data.get('source_kind','manual_entry');source_id=data.get('source_id','')
 if source_kind not in ('candidate','manual','rehab','manual_entry'):raise ValueError('Unknown CRM source')
 business=single(data,'business',200,source_kind=='manual_entry');icp=data.get('icp','spa');website=single(data,'website',1000)
 with LOCK,connect() as db:
  if source_kind=='candidate':
   row=db.execute('SELECT c.place,r.settings FROM playbook_candidates c JOIN playbook_runs r ON r.id=c.run_id WHERE c.id=?',(source_id,)).fetchone()
   if not row:raise ValueError('Research prospect not found')
   place=json.loads(row['place']);business=place.get('name','');website=place.get('website','');icp=json.loads(row['settings'])['icp']
  elif source_kind=='manual':
   row=db.execute('SELECT facts FROM manual_prospects WHERE id=?',(source_id,)).fetchone()
   if not row:raise ValueError('Manual prospect not found')
   f=json.loads(row['facts']);business=f['business'];website=f.get('website','');icp=f['icp']
  elif source_kind=='rehab':
   row=db.execute("SELECT name,website FROM prospects WHERE id=? AND mode='live'",(source_id,)).fetchone()
   if not row:raise ValueError('Choose a live Rehab prospect')
   business=row['name'];website=row['website'];icp='rehab'
  if icp not in ('spa','dietitian','rehab'):raise ValueError('Use an existing audience; ask VJ for new ICPs')
  if website:
   from urllib.parse import urlsplit
   u=urlsplit(website)
   if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:raise ValueError('Use a business HTTP(S) website')
  from .providers import domain as host
  key=host(website) or (source_kind+':'+source_id if source_id else icp+':'+business.lower())
  existing=db.execute('SELECT id FROM crm_contacts WHERE source_key=?',(key,)).fetchone()
  if existing:return {'id':existing['id'],'existing':True}
  cid=uuid.uuid4().hex
  db.execute('INSERT INTO crm_contacts(id,source_key,source_kind,source_id,business,icp,website,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
   (cid,key,source_kind,source_id,business,icp,website,now(),now()))
  activity(db,cid,'created','Added to CRM; no email permission inferred from research')
  return {'id':cid,'existing':False}

def update(cid,data):
 with LOCK,connect() as db:
  p=get(db,cid)
  if data.get('revision')!=p['revision']:raise ValueError('Contact changed; reload before saving')
  name=single(data,'name');email=single(data,'email',254).lower()
  if email and not guards.valid_email(email):raise ValueError('Use a valid email address')
  stage=data.get('stage',p['stage'])
  if stage not in STAGES:raise ValueError('Unknown CRM stage')
  if p['stage']=='suppressed' and stage!='suppressed':raise ValueError('Suppressed contacts cannot be reactivated here')
  action=single(data,'next_action',500);due=single(data,'due',40);notes=text(data,'notes',5000) if 'notes' in data else p['notes']
  if due:
   try:datetime.fromisoformat(due)
   except ValueError:raise ValueError('Use a dated next action') from None
  consent=p['consent']
  if email!=p['email']:consent={}
  if data.get('revoke_consent') is True:consent={}
  if data.get('record_consent') is True:
   if not email or data.get('email_verified') is not True:raise ValueError('Confirm the requested email address before recording permission')
   proof=text(data,'consent_evidence',2000,True)
   method=data.get('consent_method')
   if method not in ('call','signup','requested_reply'):raise ValueError('Record how the recipient requested this follow-up')
   consent={'request_id':uuid.uuid4().hex,'email':email,'purpose':'one_requested_followup','method':method,'evidence':proof,'recorded_at':now(),'email_verified':True}
   activity(db,cid,'permission','Recipient requested one follow-up email; permission recorded by the operator')
  db.execute('UPDATE crm_contacts SET name=?,email=?,stage=?,consent=?,next_action=?,due=?,notes=?,revision=revision+1,updated=? WHERE id=?',
   (name,email,stage,json.dumps(consent),action,due,notes,now(),cid));invalidate(db,cid)
  activity(db,cid,'updated','Contact and next action updated; prior email approval cleared')
  if stage=='suppressed':suppress(db,get(db,cid),'Operator marked do not contact')
 return {'ok':True}

def save_settings(data):
 s={k:single(data,k,500,k in ('sender_email','sender_name','postal_address')) for k in ('sender_email','sender_name','postal_address','approved_by','template_source')}
 if not guards.valid_email(s['sender_email']):raise ValueError('Use a valid sender email')
 s['domain_ready']=data.get('domain_ready') is True;s['daily_limit']=data.get('daily_limit',5)
 if type(s['daily_limit']) is not int or not 1<=s['daily_limit']<=20:raise ValueError('Daily send cap must be 1–20')
 s['subject_template']=single(data,'subject_template',200);s['body_template']=text(data,'body_template',10000)
 if s['subject_template'] or s['body_template']:
  if not s['subject_template'] or not s['body_template'] or s['approved_by'].strip().lower() not in ('vj','vijai') or not s['template_source'] or data.get('template_approved') is not True:
   raise ValueError('VJ-approved subject/body, source reference and approval confirmation are required')
  for template in (s['subject_template'],s['body_template']):
   try:
    identifiers=string.Template(template).get_identifiers()
    if not string.Template(template).is_valid() or set(identifiers)-{'business','contact_name','sender_name','website'}:raise ValueError()
   except ValueError:raise ValueError('Use only $business, $contact_name, $sender_name and $website placeholders') from None
 with LOCK,connect() as db:
  db.execute('INSERT INTO crm_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',(json.dumps(s),))
  db.execute("UPDATE crm_emails SET stage='draft',approval_hash=NULL WHERE stage='approved'")
 return {'ok':True}

def has_permission(db,p):
 c=p['consent']
 if suppressed(db,p):return 'Do not contact: suppression applies'
 if not guards.valid_email(p['email']) or c.get('email')!=p['email'] or c.get('purpose')!='one_requested_followup' or c.get('email_verified') is not True:return 'Record the recipient request and verify their email address first'
 if db.execute("SELECT 1 FROM crm_emails WHERE contact_id=? AND (stage IN ('sending','unknown') OR (stage='sent' AND request_id=?))",(p['id'],c.get('request_id'))).fetchone():return 'Requested follow-up already attempted or uncertain; no automatic repeat'
 if db.execute("SELECT 1 FROM crm_activity WHERE contact_id=? AND kind='reply' AND created>=?",(p['id'],c.get('recorded_at',''))).fetchone():return 'A reply arrived after this request; review it and record fresh permission before another email'
 return ''

def prepare(cid):
 with LOCK,connect() as db:
  p=get(db,cid);s=settings(db);bad=has_permission(db,p)
  if bad:raise ValueError(bad)
  if not s['subject_template'] or not s['body_template'] or s['approved_by'].lower() not in ('vj','vijai'):raise ValueError('Configure the VJ-approved requested-follow-up email template first')
  values={'business':p['business'],'contact_name':p['name'] or p['business'],'sender_name':s['sender_name'],'website':p['website']}
  subject=string.Template(s['subject_template']).substitute(values);body=string.Template(s['body_template']).substitute(values)
  body+='\n\n'+s['sender_name']+' | '+s['postal_address']+'\nTo stop receiving emails from us, reply unsubscribe.'
  existing=db.execute("SELECT id FROM crm_emails WHERE contact_id=? AND stage IN ('draft','approved')",(cid,)).fetchone()
  eid=existing['id'] if existing else uuid.uuid4().hex
  template_hash=hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest()
  if existing:db.execute("UPDATE crm_emails SET subject=?,body=?,stage='draft',approval_hash=NULL,revision=revision+1,request_id=?,template_hash=? WHERE id=?",(subject,body,p['consent']['request_id'],template_hash,eid))
  else:db.execute('INSERT INTO crm_emails(id,contact_id,subject,body,stage,created,request_id,template_hash) VALUES(?,?,?,?,?,?,?,?)',(eid,cid,subject,body,'draft',now(),p['consent']['request_id'],template_hash))
  activity(db,cid,'draft','Prepared from the approved template; no approval or send')
  return {'id':eid,'no_approval':True,'no_contact':True}

def email(db,eid):
 row=db.execute('SELECT * FROM crm_emails WHERE id=?',(eid,)).fetchone()
 if not row:raise ValueError('Follow-up email not found')
 return dict(row)

def digest(p,e,s):
 return hashlib.sha256(json.dumps({'contact':p,'email':{k:e[k] for k in ('id','subject','body','revision')},'settings':s},sort_keys=True).encode()).hexdigest()

def approve(eid,data):
 with LOCK,connect() as db:
  e=email(db,eid);p=get(db,e['contact_id']);s=settings(db);bad=has_permission(db,p)
  if bad:raise ValueError(bad)
  if e.get('template_hash')!=hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest() or e.get('request_id')!=p['consent'].get('request_id'):raise ValueError('Template or permission changed; prepare a fresh draft')
  if e['stage']!='draft' or data.get('revision')!=e['revision'] or data.get('reviewed') is not True:raise ValueError('Review and approve the current draft revision')
  db.execute("UPDATE crm_emails SET stage='approved',approval_hash=? WHERE id=?",(digest(p,e,s),eid))
  activity(db,p['id'],'approved','Human approved this email revision; Send remains separate')
 return {'ok':True}

def suppress(db,p,reason):
 for key in filter(None,(p['email'].lower(),domain(p))):
  db.execute('INSERT OR IGNORE INTO suppressions VALUES(?,?,?)',(key,reason,now()))
  db.execute("UPDATE crm_contacts SET stage='suppressed',consent='{}',revision=revision+1 WHERE lower(email)=? OR source_key=?",(key,key))
  db.execute("UPDATE prospects SET status='suppressed',approval_hash=NULL,approved_revision=NULL WHERE lower(email)=? OR domain=?",(key,key))
 db.execute("UPDATE crm_contacts SET stage='suppressed',consent='{}',revision=revision+1 WHERE id=?",(p['id'],))
 db.execute("UPDATE crm_emails SET stage='cancelled',approval_hash=NULL WHERE stage IN ('draft','approved') AND contact_id IN (SELECT id FROM crm_contacts WHERE stage='suppressed')")
 activity(db,p['id'],'suppressed',reason)

def record_reply(cid,data,reply_id=None):
 reply=text(data,'text',12000,True)
 # Quoted previous messages, including our own unsubscribe footer, are not new intent.
 fresh=re.split(r'(?m)^On .+wrote:|^From:|^-{2,}\s*Original Message',reply)[0]
 fresh='\n'.join(line for line in fresh.splitlines() if not line.lstrip().startswith('>') and line.strip()!='To stop receiving emails from us, reply unsubscribe.')
 kind='opt_out' if STOP.search(fresh) else 'reply'
 with LOCK,connect() as db:
  p=get(db,cid);rid=reply_id or uuid.uuid4().hex
  if db.execute('SELECT 1 FROM crm_activity WHERE id=?',(rid,)).fetchone():return {'ok':True}
  db.execute('INSERT INTO crm_activity VALUES(?,?,?,?,?)',(rid,cid,kind,reply,now()))
  if kind=='opt_out':suppress(db,p,'Recipient opt-out; no further contact')
  else:
   invalidate(db,cid)
   db.execute("UPDATE crm_contacts SET next_action='Review reply',updated=? WHERE id=?",(now(),cid))
 return {'ok':True,'suppressed':kind=='opt_out'}

def sync():
 with LOCK,connect() as db:
  s=settings(db);rows=[dict(row) for row in db.execute("SELECT id,contact_id,gmail_id,gmail_thread FROM crm_emails WHERE stage='sent'")]
 if not rows:return {'processed':0}
 if gmail.profile().lower()!=s['sender_email'].lower():raise ValueError('Connected Gmail must match the CRM sender')
 count=0
 for e in rows:
  thread=gmail.request('threads/'+e['gmail_thread']+'?format=full')
  with connect() as db:p=get(db,e['contact_id'])
  for m in thread.get('messages',[]):
   if m.get('id')==e['gmail_id'] or 'SENT' in m.get('labelIds',[]):continue
   payload=m.get('payload',{});headers={h['name'].lower():h['value'] for h in payload.get('headers',[])}
   sender=parseaddr(headers.get('from',''))[1].lower();body=gmail.body_text(payload)
   bounce=sender.startswith(('mailer-daemon@','postmaster@')) and ('delivery' in headers.get('subject','').lower() or 'failed' in headers.get('subject','').lower())
   if sender==p['email'] and body.strip():record_reply(p['id'],{'text':body},'gmail:'+m['id']);count+=1
   elif bounce:
    with LOCK,connect() as db:
     if not db.execute('SELECT 1 FROM crm_activity WHERE id=?',('gmail:'+m['id'],)).fetchone():
      db.execute('INSERT INTO crm_activity VALUES(?,?,?,?,?)',('gmail:'+m['id'],p['id'],'bounce','Delivery failure received; recipient suppressed',now()));suppress(db,p,'Gmail delivery failure')
 return {'processed':count}

def send(eid,data):
 if os.environ.get('ALLOW_FOLLOWUP_SEND','').lower()!='true':raise ValueError('Requested-follow-up sending is disabled in private WSL configuration')
 # Check existing threads for withdrawal first. A sync failure blocks new sends.
 sync()
 with LOCK:
  with connect() as db:
   e=email(db,eid);p=get(db,e['contact_id']);s=settings(db);bad=has_permission(db,p)
   if bad:raise ValueError(bad)
   if e['stage']!='approved' or data.get('revision')!=e['revision'] or e['approval_hash']!=digest(p,e,s):raise ValueError('Approve the current email and contact details before sending')
   if not s['domain_ready'] or not s['postal_address'] or not guards.valid_email(s['sender_email']):raise ValueError('Confirm sender identity, postal address and domain authentication')
   cutoff=datetime.now(timezone.utc).date().isoformat()
   if db.execute("SELECT count(*) FROM crm_emails WHERE stage IN ('sent','sending','unknown') AND created>=?",(cutoff,)).fetchone()[0]>=s['daily_limit']:raise ValueError('Daily requested-follow-up send cap reached')
   if not gmail.token_path().exists():raise ValueError('Connect the CRM sender Gmail account privately in WSL')
   db.execute("UPDATE crm_emails SET stage='sending',created=? WHERE id=?",(now(),eid))
   activity(db,p['id'],'send_reserved','One network attempt reserved; no automatic retry')
  try:
   result=gmail.send({'email':p['email'],'draft':{'subject':e['subject'],'body':e['body']}},s,eid)
   if not result.get('id') or not result.get('threadId'):raise ValueError('Incomplete provider response')
   with connect() as db:
    db.execute("UPDATE crm_emails SET stage='sent',gmail_id=?,gmail_thread=?,approval_hash=NULL WHERE id=?",(result['id'],result['threadId'],eid))
    db.execute("UPDATE crm_contacts SET consent='{}',next_action='Await reply',updated=? WHERE id=?",(now(),p['id']))
    activity(db,p['id'],'sent','Requested email sent through the configured Gmail account')
  except Exception:
   with connect() as db:
    db.execute("UPDATE crm_emails SET stage='unknown',approval_hash=NULL,error='Check Gmail manually; do not retry' WHERE id=?",(eid,))
    activity(db,p['id'],'unknown','Delivery uncertain; retries blocked')
   raise ValueError('Delivery outcome uncertain. Check Gmail; do not retry') from None
 return {'ok':True,'sent':True}

def snapshot():
 with LOCK,connect() as db:
  contacts=[]
  for row in db.execute('SELECT id FROM crm_contacts ORDER BY updated DESC'):
   p=get(db,row['id']);p['suppressed']=suppressed(db,p)
   p['emails']=[dict(e) for e in db.execute('SELECT * FROM crm_emails WHERE contact_id=? ORDER BY created DESC',(p['id'],))]
   for e in p['emails']:e.pop('approval_hash',None)
   p['activity']=[dict(a) for a in db.execute('SELECT kind,detail,created FROM crm_activity WHERE contact_id=? ORDER BY created DESC LIMIT 30',(p['id'],))]
   contacts.append(p)
  sources=[]
  for row in db.execute('SELECT c.id,c.place,r.settings FROM playbook_candidates c JOIN playbook_runs r ON r.id=c.run_id ORDER BY c.created DESC LIMIT 100'):
   place=json.loads(row['place']);sources.append({'source_kind':'candidate','source_id':row['id'],'business':place.get('name',''),'icp':json.loads(row['settings'])['icp']})
  for row in db.execute("SELECT id,name FROM prospects WHERE mode='live' ORDER BY created DESC LIMIT 100"):
   sources.append({'source_kind':'rehab','source_id':row['id'],'business':row['name'],'icp':'rehab'})
  return {'contacts':contacts,'sources':sources,'settings':settings(db),'gmail_configured':gmail.token_path().exists(),
   'send_enabled':os.environ.get('ALLOW_FOLLOWUP_SEND','').lower()=='true','local_only_send':True}
