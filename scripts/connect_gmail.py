"""Explicit, user-run Gmail connection; unavailable until a live draft is approved."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gtm.config import ROOT, load_env, config
from gtm.db import connect, get
from gtm.gmail import SCOPES, token_path
from gtm.guards import fingerprint

def main():
    load_env()
    with connect() as db:
        approved = db.execute("SELECT id FROM prospects WHERE mode='live' AND status='approved'").fetchall()
        if not any((p := get(db, row['id']))['approval_hash'] == fingerprint(p, config('settings'), config('strategy')) for row in approved):
            raise SystemExit('Approve a current live draft in the dashboard before connecting Gmail.')
    from google_auth_oauthlib.flow import InstalledAppFlow
    client = ROOT / os.environ.get('GMAIL_CLIENT_FILE', 'data/google-client.json')
    flow = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES)
    credentials = flow.run_local_server(port=0, access_type='offline', prompt='consent', login_hint=config('settings')['sender_email'])
    token_path().parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token_path().write_text(credentials.to_json())
    token_path().chmod(0o600)
    print('Gmail connected. Sending still requires ALLOW_SEND=true, approval and an explicit Send click.')

if __name__ == '__main__':
    main()
