import os,json,subprocess,time
from pathlib import Path
from .config import ROOT
_cached=None
_checked=0
def status():
 global _cached,_checked
 if _cached is not None and time.monotonic()-_checked<60:return dict(_cached,model=os.environ.get('HERMES_MODEL',''),provider='openai-codex')
 python=Path(os.environ.get('HERMES_PYTHON','~/.hermes/hermes-agent/venv/bin/python')).expanduser()
 try:
  env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','SSL_CERT_FILE','HERMES_SOURCE')}
  p=subprocess.run([str(python),str(ROOT/'scripts/account_status.py')],env=env,capture_output=True,text=True,timeout=25)
  a=json.loads(p.stdout)
  _cached={k:a.get(k) for k in ('logged_in','auth_mode','rate_limited','error_code')}
 except Exception:_cached={'logged_in':False,'error_code':'subscription_sign_in_unavailable'}
 _checked=time.monotonic()
 return dict(_cached,model=os.environ.get('HERMES_MODEL',''),provider='openai-codex')
