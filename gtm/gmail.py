import base64
import json
import os
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from .config import ROOT
from .providers import api_json

SCOPES = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly']

def token_path():
    return ROOT / os.environ.get('GMAIL_TOKEN_FILE', 'data/gmail-token.json')

def token():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        raise ValueError('Install requirements-gmail.txt before connecting Gmail') from None
    if not token_path().exists():
        raise ValueError('Connect Gmail with scripts/connect_gmail.py after approving a live draft')
    c = Credentials.from_authorized_user_file(str(token_path()), SCOPES)
    if not c.valid:
        if not c.refresh_token:
            raise ValueError('Reconnect Gmail')
        c.refresh(Request())
        token_path().write_text(c.to_json())
        token_path().chmod(0o600)
    return c.token

def request(path, body=None, method=None):
    return api_json('https://gmail.googleapis.com/gmail/v1/users/me/' + path, body,
        {'Authorization': 'Bearer ' + token()}, method)

def profile():
    return request('profile')['emailAddress']

def send(p, settings, delivery_id):
    if profile().lower() != settings['sender_email'].lower():
        raise ValueError('Connected Gmail account must match the configured Continere sender')
    message = EmailMessage()
    message['To'] = p['email']
    message['From'] = formataddr((settings['sender_name'], settings['sender_email']))
    message['Subject'] = p['draft']['subject']
    message['Message-ID'] = f'<continere-{delivery_id}@{settings["sender_email"].split("@")[1]}>'
    message['List-Unsubscribe'] = f'<mailto:{settings["sender_email"]}?subject=unsubscribe>'
    message.set_content(p['draft']['body'])
    return request('messages/send', {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()})

def body_text(payload):
    if payload.get('mimeType') == 'text/plain' and payload.get('body', {}).get('data'):
        data = payload['body']['data']
        return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode(errors='replace')[:12000]
    return '\n'.join(body_text(p) for p in payload.get('parts', []))[:12000]
