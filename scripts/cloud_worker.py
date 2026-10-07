"""Private outbound-only worker. Never listens on a port or exports auth files."""
import argparse,fcntl,hashlib,json,re,sqlite3,time,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
READS=('/api/state','/api/playbook','/api/playbook/campaigns','/api/account','/api/entry-drafts','/api/crm')
LOCAL='http://127.0.0.1:8765'
def allowed(path):
    return path in ('/api/crm/create','/api/crm/settings','/api/run','/api/config','/api/sync','/api/playbook/research','/api/playbook/mission','/api/playbook/create') or bool(re.fullmatch(r'/api/playbook/[a-f0-9]{32}/(prepare-script|advance|park|retry|edit|approve|handover|outcome)',path)) or bool(re.fullmatch(r'/api/crm/[a-f0-9]{32}/(update|prepare|approve)',path)) or bool(re.fullmatch(r'/api/prospect/[a-f0-9]{32}/(approve|reject|edit|suppress|regenerate|reply)',path))
def cloud(config,body):
    req=urllib.request.Request(config['origin']+'/api/worker',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+config['worker_token'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
def snapshots():
    out={}
    for path in READS:
        with urllib.request.urlopen(LOCAL+path,timeout=20) as r:out[path]=json.load(r)
    # Only approved workspace records. Email reply bodies remain solely in WSL.
    out['/api/state']['replies']=[]
    out['/api/state']['integrations']['send_enabled']=False
    crm=out['/api/crm'];crm['send_enabled']=False
    for contact in crm.get('contacts',[]):
        contact['notes']=''
        contact.get('consent',{}).pop('evidence',None)
        for activity in contact.get('activity',[]):
            if activity.get('kind') in ('reply','opt_out'):activity['detail']='Reply stored privately in WSL'
        for email in contact.get('emails',[]):
            email.pop('gmail_thread',None);email.pop('gmail_id',None)
    return out

def execute(job):
    if not allowed(job.get('path','')):return 403,{'error':'Action not permitted by private worker; cloud email sending disabled'}
    if not isinstance(job.get('data'),dict):return 400,{'error':'Invalid queued action'}
    with urllib.request.urlopen(LOCAL,timeout=10) as r:html=r.read().decode()
    token=re.search(r'<meta name="csrf-token" content="([^"]+)"',html).group(1)
    req=urllib.request.Request(LOCAL+job['path'],data=json.dumps(job['data']).encode(),headers={'Content-Type':'application/json','Origin':LOCAL,'X-CSRF-Token':token})
    try:
        with urllib.request.urlopen(req,timeout=25) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:return e.code,json.load(e)

def process(job,db,config,sync):
    row=db.execute('SELECT stage,status,result FROM cloud_jobs WHERE id=?',(job['id'],)).fetchone()
    if row and row[0]=='running':
        body={'op':'complete','id':job['id'],'stage':'needs_review','status':409,'error':'Private worker interrupted. Inspect saved state before retrying; action was not replayed.'}
    elif row:
        body={'op':'complete','id':job['id'],'stage':'complete','status':row[1],'result':json.loads(row[2])}
    else:
        db.execute('INSERT INTO cloud_jobs(id,stage) VALUES (?,?)',(job['id'],'running'));db.commit()
        try:status,result=execute(job)
        except Exception:
            error={'error':'Local action response was interrupted. Inspect saved state; no automatic retry.'}
            db.execute('UPDATE cloud_jobs SET stage=?,status=?,result=? WHERE id=?',('needs_review',409,json.dumps(error),job['id']));db.commit()
            cloud(config,{'op':'complete','id':job['id'],'stage':'needs_review','status':409,'error':error['error']});return
        db.execute('UPDATE cloud_jobs SET stage=?,status=?,result=? WHERE id=?',('complete',status,json.dumps(result),job['id']));db.commit()
        sync(force=True)
        body={'op':'complete','id':job['id'],'stage':'complete','status':status,'result':result}
    cloud(config,body)
    db.execute("UPDATE cloud_jobs SET stage='acknowledged' WHERE id=?",(job['id'],));db.commit()

def acknowledge_results(db,config):
    # Retry only a receipt, never a local action or outbound contact.
    for jid,stage,status,result in db.execute("SELECT id,stage,status,result FROM cloud_jobs WHERE stage IN ('complete','needs_review')").fetchall():
        value=json.loads(result)
        cloud(config,{'op':'complete','id':jid,'stage':stage,'status':status,'result':value,'error':value.get('error') if stage=='needs_review' else None})
        db.execute("UPDATE cloud_jobs SET stage='acknowledged' WHERE id=?",(jid,));db.commit()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    config=json.loads((ROOT/'data/cloud-worker.json').read_text())
    if not config['origin'].startswith('https://') or len(config['worker_token'])<32:raise ValueError('Invalid private worker configuration')
    lock=open(ROOT/'data/cloud-worker.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    db=sqlite3.connect(ROOT/'data/cloud-worker.sqlite3');db.execute('CREATE TABLE IF NOT EXISTS cloud_jobs(id TEXT PRIMARY KEY,stage TEXT,status INTEGER,result TEXT)');db.commit()
    digest=None
    def sync(force=False):
        nonlocal digest
        state=snapshots();value=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
        if force or value!=digest:cloud(config,{'op':'sync','snapshots':state});digest=value
    print('Private cloud worker: outbound polling only; no tunnel; cloud email sending disabled.',flush=True)
    while True:
        try:
            acknowledge_results(db,config)
            sync();job=cloud(config,{'op':'poll'}).get('job')
            if job:process(job,db,config,sync)
            if args.once:break
        except Exception:
            print('Cloud connection unavailable; no action automatically replayed.',flush=True)
            if args.once:raise
        time.sleep(15)
if __name__=='__main__':main()
