import base64
import json
import os
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .config import ROOT, load_env
from . import db, service, playbook, playbook_campaigns

TOKEN = secrets.token_urlsafe(32)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def respond(self, status, data, content_type='application/json'):
        raw = json.dumps(data).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(raw)

    def remote_origin(self):
        origin = os.environ.get('GTM_PUBLIC_ORIGIN', '').rstrip('/')
        if not origin:
            return ''
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('GTM_PUBLIC_ORIGIN must be one HTTPS origin')
        if len(os.environ.get('GTM_REMOTE_PASSWORD', '')) < 32:
            raise ValueError('Remote mode requires GTM_REMOTE_PASSWORD with at least 32 characters')
        return origin

    def authenticated(self):
        if not self.remote_origin():
            return True
        header = self.headers.get('Authorization', '')
        expected = 'Basic ' + base64.b64encode(('continere:' + os.environ['GTM_REMOTE_PASSWORD']).encode()).decode()
        if secrets.compare_digest(header, expected):
            return True
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Continere private workspace"')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return False

    def valid_host(self):
        hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        origin = self.remote_origin()
        if origin: hosts.add(urllib.parse.urlsplit(origin).netloc)
        return self.headers.get('Host') in hosts

    def do_GET(self):
        if not self.authenticated(): return
        if not self.valid_host():
            return self.respond(403, {'error': 'Local access only'})
        path = urllib.parse.urlsplit(self.path).path
        if path == '/api/playbook/campaigns':
            return self.respond(200, playbook_campaigns.snapshot())
        if path == '/api/playbook':
            return self.respond(200, playbook.snapshot())
        if path == '/api/entry-drafts':
            draft=ROOT/'data/entry-drafts.json'
            return self.respond(200,json.loads(draft.read_text()) if draft.exists() else {})
        if path == '/api/account':
            from .account import status
            return self.respond(200, status())
        if path == '/api/state':
            with service.LOCK:
                return self.respond(200, service.snapshot())
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/rehab': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'),
            '/style.css': ('style.css', 'text/css'), '/playbook': ('index.html', 'text/html; charset=utf-8'), '/playbook.js': ('playbook.js', 'text/javascript'), '/playbook-fragment.html': ('playbook-fragment.html','text/html; charset=utf-8'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
        if path not in files:
            return self.respond(404, {'error': 'Not found'})
        file, mime = files[path]
        body = (ROOT / 'static' / file).read_bytes().replace(b'__CSRF_TOKEN__', TOKEN.encode())
        self.respond(200, body, mime)

    def do_POST(self):
        if not self.authenticated(): return
        expected = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if self.remote_origin(): expected.add(self.remote_origin())
        if not self.valid_host() or self.headers.get('Origin') not in expected or not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), TOKEN):
            return self.respond(403, {'error': 'Open the local dashboard to perform this action'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 100_000 or self.headers.get('Content-Type') != 'application/json':
                raise ValueError('Use a small JSON request')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Request must be an object')
            path = urllib.parse.urlsplit(self.path).path
            if path == '/api/playbook/mission':
                from .mission import geography,intent,research_batch
                goal=data.get('goal','');scope=geography(goal)
                with db.connect() as conn:
                    rows=conn.execute("SELECT c.id,c.analysis,r.settings FROM playbook_candidates c JOIN playbook_runs r ON r.id=c.run_id WHERE c.stage='needs_verification' ORDER BY c.created DESC").fetchall()
                candidate=next((c for c in rows if json.loads(c['settings'])['icp']==data.get('icp') and not json.loads(c['analysis']).get('qualification_notice')),None)
                if candidate and intent(goal)=='continue':
                    existing=json.loads(candidate['settings'])
                    if scope['source']=='prompt' and scope['city'].lower()!=existing['city'].lower() and scope['scope']!='national':raise ValueError('This task names a different geography from the saved prospect. Ask to find a new prospect, or continue without changing its location.')
                    playbook_campaigns.prepare_script(candidate['id'],goal);result={'ok':True,'action':'continue','geography':existing['city']}
                else:
                    result={'run_id':playbook_campaigns.start({'icp':data.get('icp'),'source':'web','city':scope['city'],'sender':data.get('sender') or 'Continere','timezone':'',**research_batch(goal),'business':'','agent_goal':goal,'prompt_scope':True}),'action':'discover','geography':scope['city'],**research_batch(goal)}
            elif path == '/api/playbook/research':
                result = {'run_id': playbook_campaigns.start(data)}
            elif path == '/api/playbook/create':
                cid = data.pop('source_candidate', None)
                result = {'id': playbook_campaigns.accept(cid, data) if cid else playbook.create(data)}
            elif path.startswith('/api/playbook/'):
                parts = path.strip('/').split('/')
                if len(parts) != 4:
                    raise ValueError('Unknown playbook endpoint')
                pid, action = parts[2:]
                if action == 'prepare-script':
                    playbook_campaigns.prepare_script(pid,data.get("goal",""));result={'ok':True}
                elif action == 'advance':
                    playbook_campaigns.advance(pid); result = {'ok': True}
                elif action == 'park':
                    playbook_campaigns.park(pid); result = {'ok': True}
                elif action == 'retry':
                    playbook_campaigns.retry(pid); result = {'ok': True}
                elif action == 'edit':
                    playbook.edit(pid, data); result = {'ok': True}
                elif action == 'approve':
                    playbook.approve(pid, data); result = {'ok': True}
                elif action == 'handover': result = playbook.handover(pid, data)
                elif action == 'outcome': result = playbook.outcome(pid, data)
                else: raise ValueError('Unknown playbook action')
            elif path == '/api/run':
                result = {'run_id': service.start_run(data.get('mode'))}
            elif path == '/api/config':
                service.save_config(data.get('name'), data.get('value'))
                result = {'ok': True}
            elif path == '/api/sync':
                result = {'processed': service.sync_replies()}
            else:
                parts = path.strip('/').split('/')
                if len(parts) != 4 or parts[:2] != ['api', 'prospect']:
                    return self.respond(404, {'error': 'Not found'})
                pid, action = parts[2:]
                if action == 'edit': service.edit(pid, data)
                elif action == 'regenerate': service.regenerate(pid, data)
                elif action == 'approve': service.approve(pid, data)
                elif action == 'reject': service.reject(pid)
                elif action == 'send': service.send(pid, data)
                elif action == 'reply': service.reply(pid, data.get('text'))
                elif action == 'suppress':
                    with service.LOCK, db.connect() as conn:
                        service.suppress(conn, db.get(conn, pid), 'Human marked do not contact')
                else: return self.respond(404, {'error': 'Unknown action'})
                result = {'ok': True}
            self.respond(200, result)
        except (ValueError, KeyError, TypeError) as exc:
            self.respond(400, {'error': str(exc)[:1000]})
        except Exception as exc:
            self.respond(500, {'error': service.safe_error(exc)})

def main():
    load_env()
    origin = os.environ.get('GTM_PUBLIC_ORIGIN', '').rstrip('/')
    if origin:
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password or len(os.environ.get('GTM_REMOTE_PASSWORD', '')) < 32:
            raise ValueError('Remote access requires a valid HTTPS origin and private 32+ character password')
    os.umask(0o077)
    db.init()
    playbook.init()
    playbook_campaigns.init()
    port = int(os.environ.get('PORT', '8765'))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'Continere GTM: http://127.0.0.1:{port} — sending disabled by default', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()

if __name__ == '__main__':
    main()
