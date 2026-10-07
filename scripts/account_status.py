import os,sys,json,contextlib
from pathlib import Path
source=Path(os.environ.get('HERMES_SOURCE','~/.hermes/hermes-agent')).expanduser()
sys.path.insert(0,str(source))
os.environ['HERMES_HOME']=str(Path(__file__).resolve().parents[1]/'data/hermes')
try:
 with contextlib.redirect_stdout(sys.stderr):
  from hermes_cli.auth import get_codex_auth_status
  a=get_codex_auth_status()
 print(json.dumps({k:a.get(k) for k in ('logged_in','auth_mode','rate_limited','error_code')}))
except Exception:
 print(json.dumps({'logged_in':False,'error_code':'subscription_sign_in_unavailable'}))
