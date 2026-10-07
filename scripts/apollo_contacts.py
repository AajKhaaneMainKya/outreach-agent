"""Private WSL contact lookup; never sends or approves outreach."""
import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gtm.config import load_env
from gtm import apollo

def configure():
    path=Path(os.environ.get('GTM_ENV_FILE','~/.config/outreach-agent/runtime.env')).expanduser()
    key=getpass.getpass('Apollo API key (hidden): ').strip()
    if not key or not re.fullmatch(r'[A-Za-z0-9_.-]+',key):raise ValueError('Invalid key format; no configuration written')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    text=path.read_text() if path.exists() else ''
    lines=[line for line in text.splitlines() if not line.strip().startswith('APOLLO_API_KEY=')]
    lines.append('APOLLO_API_KEY='+key)
    temporary=path.with_name(path.name+'.apollo.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write('\n'.join(lines)+'\n')
    os.replace(temporary,path);path.chmod(0o600)
    print('Apollo key saved privately. Restart the local app to load it. No API request made.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='command',required=True)
    subs.add_parser('configure');subs.add_parser('check')
    search=subs.add_parser('search');search.add_argument('--website',required=True)
    search.add_argument('--title',action='append');search.add_argument('--limit',type=int,default=5)
    enrich=subs.add_parser('enrich');enrich.add_argument('--website',required=True)
    enrich.add_argument('--person-id',required=True);enrich.add_argument('--confirm-credit-use',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='configure':configure();return
        load_env()
        if args.command=='check':value=apollo.health()
        elif args.command=='search':value=apollo.search(args.website,args.title,args.limit)
        else:value=apollo.enrich(args.person_id,args.website,args.confirm_credit_use)
        print(json.dumps(value,indent=2))
    except (ValueError,OSError) as exc:
        print(str(exc) if isinstance(exc,ValueError) else 'Private configuration unavailable',file=sys.stderr)
        raise SystemExit(1)
if __name__=='__main__':main()
