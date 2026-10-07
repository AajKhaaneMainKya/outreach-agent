"""Optional Hermes four-specialist QA; never approves or sends."""
import json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gtm.config import load_env
from gtm import playbook, agents
from gtm.db import connect
load_env()
with connect() as db: p=playbook.get(db,sys.argv[1])
payload={'workflow':'playbook','authoritative_policy':playbook.policy(),'prospect':p}
# Use the same isolated worker/environment contract, but validate playbook QA rather than rehab claim IDs.
import os, subprocess
source=Path(os.environ.get('HERMES_SOURCE','~/.hermes/hermes-agent')).expanduser()
python=Path(os.environ.get('HERMES_PYTHON',str(source/'venv/bin/python'))).expanduser()
model=os.environ.get('HERMES_MODEL','').strip()
if not model: raise SystemExit('Set HERMES_MODEL after subscription sign-in')
env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','TMPDIR','SSL_CERT_FILE')}
env.update(HERMES_SOURCE=str(source),HERMES_MODEL=model,GTM_PROJECT=str(playbook.ROOT))
r=subprocess.run([str(python),str(playbook.ROOT/'scripts/hermes_worker.py')],input=json.dumps(payload),text=True,capture_output=True,timeout=240,cwd=playbook.ROOT/'data',env=env)
if r.returncode: raise SystemExit('Hermes QA failed; no approval or contact occurred. Check setup.')
lines=[s.removeprefix('CONTINERE_RESULT=') for s in r.stdout.splitlines() if s.startswith('CONTINERE_RESULT=')]
if len(lines)!=1: raise SystemExit('Invalid Hermes result')
v=json.loads(lines[0])
if type(v.get('qa_pass')) is not bool or v.get('icp')!=p['facts']['icp'] or not isinstance(v.get('reason'),str) or not isinstance(v.get('findings'),list) or any(not isinstance(x,str) for x in v['findings']): raise SystemExit('Invalid specialist QA contract')
print(json.dumps(v,indent=2))
print('Advisory QA only. Review and approve exact template in dashboard before manual contact.')
