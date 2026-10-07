"""Isolated, read-only Chromium reader; every request uses pinned public IPs."""
import datetime
import html
import http.client
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.parse
from . import providers

RUNTIME = Path(__file__).resolve().parents[1] / 'data/browser-venv/bin/python'
MAX_REQUESTS = 60
MAX_BYTES = 12_000_000

def _request(url):
    u, port, ip = providers.public_target(url)
    conn = providers.PinnedHTTPS(u.hostname, port, ip) if u.scheme == 'https' else http.client.HTTPConnection(ip, port, timeout=5)
    conn.timeout = 5
    try:
        path = urllib.parse.urlunsplit(('', '', u.path or '/', u.query, ''))
        conn.request('GET', path, headers={'Host': u.hostname, 'User-Agent': 'ContinereResearch/0.1', 'Accept': '*/*'})
        response = conn.getresponse()
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError('Browser resource exceeded size budget')
        headers = {k.lower(): v for k,v in response.getheaders() if k.lower() in ('content-type','location','content-encoding')}
        return response.status, headers, body
    finally:
        conn.close()

def _read(url, interaction):
    from playwright.sync_api import sync_playwright
    providers.public_target(url)
    started = time.monotonic()
    count = total = blocked = 0
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, args=['--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-quic', '--disable-webrtc', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
        try:
            context = browser.new_context(service_workers='block', accept_downloads=False, java_script_enabled=True)
            def route_request(route):
                nonlocal count, total, blocked
                request = route.request
                count += 1
                if count > MAX_REQUESTS or total >= MAX_BYTES or time.monotonic()-started > 25 or request.method != 'GET' or request.resource_type in ('image','media','font'):
                    blocked += 1
                    route.abort()
                    return
                try:
                    status, headers, body = _request(request.url)
                    total += len(body)
                    if total > MAX_BYTES:
                        raise ValueError('Browser exceeded transfer budget')
                    route.fulfill(status=status, headers=headers, body=body)
                except Exception:
                    blocked += 1
                    route.abort()
            context.route('**/*', route_request)
            context.route_web_socket('**/*', lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(3000)
            response = page.goto(url, wait_until='domcontentloaded', timeout=20000)
            if not response or response.status >= 400:
                raise ValueError('Public browser page unavailable')
            page.wait_for_timeout(500)
            actions = []
            if interaction == 'reviews':
                # Read-only tabs: never broad text matches on contact/login/submit buttons.
                tabs = page.get_by_role('tab', name=re.compile(r'^reviews(?:\s*\(\d+\))?$', re.I))
                if tabs.count() == 1:
                    tabs.click(timeout=2000)
                    actions.append('opened Reviews tab')
                    page.wait_for_timeout(300)
                page.evaluate('window.scrollBy(0, Math.min(window.innerHeight, 900))')
                actions.append('scrolled one viewport')
            final = page.url
            providers.public_target(final)
            text = page.locator('body').inner_text(timeout=3000)[:24000]
            links = page.locator('a[href]').evaluate_all('(nodes) => nodes.slice(0,150).map(n => n.href)')
            own = providers.domain(final)
            emails = sorted(set(e for e in re.findall(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', text) if e.split('@')[1].lower() == own))
            return {'url': final, 'text': html.unescape(text), 'links': links, 'emails': emails, 'metadata': {'reader': 'playwright-chromium', 'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'actions': actions, 'request_count': count, 'blocked_requests': blocked, 'bytes': total, 'elapsed_seconds': round(time.monotonic()-started,2), 'rating_verified': False}}
        finally:
            browser.close()

def _invoke(argv, **kwargs):
    timeout = kwargs.pop('timeout')
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True, cwd=kwargs['cwd'], env=kwargs['env'])
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)

def read_page(url, *, interaction='none'):
    if interaction not in ('none', 'reviews'):
        raise ValueError('Only read-only review interaction is supported')
    providers.public_target(url)
    if not RUNTIME.exists():
        raise ValueError('Local browser runtime is not installed')
    try:
        result = _invoke([str(RUNTIME), '-m', 'scripts.headless_reader', url, interaction], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=38, env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Headless page reached its time budget') from exc
    if result.returncode:
        raise ValueError('Headless page could not be read: '+result.stdout.strip()[:300])
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise ValueError('Invalid browser reader response') from exc
