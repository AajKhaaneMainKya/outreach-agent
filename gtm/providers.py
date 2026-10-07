"""Provider boundary: Places REST discovery and bounded public-website retrieval."""
import html
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.parse
import urllib.request
from html.parser import HTMLParser

def api_json(url, body=None, headers=None, method=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json', **(headers or {})}, method=method)
    with urllib.request.urlopen(req, timeout=35) as response:
        return json.load(response)

def discover(settings):
    key = os.environ.get('GOOGLE_PLACES_API_KEY')
    if not key:
        raise ValueError('Set GOOGLE_PLACES_API_KEY in .env before live discovery')
    places, token = [], None
    while len(places) < settings['limit']:
        body = {'textQuery': f"{settings['query']} in {settings['geography']}", 'pageSize': min(20, settings['limit'] - len(places))}
        if token:
            body['pageToken'] = token
        result = api_json('https://places.googleapis.com/v1/places:searchText', body, {
            'X-Goog-Api-Key': key,
            'X-Goog-FieldMask': 'places.id,places.displayName,places.formattedAddress,places.websiteUri,places.googleMapsUri,places.businessStatus,nextPageToken'})
        for p in result.get('places', []):
            if p.get('businessStatus') == 'CLOSED_PERMANENTLY':
                continue
            places.append({'place_id': p['id'], 'name': p.get('displayName', {}).get('text', ''),
                'address': p.get('formattedAddress', ''), 'website': p.get('websiteUri', ''),
                'source': p.get('googleMapsUri', 'https://maps.google.com/?q=place_id:' + p['id'])})
        token = result.get('nextPageToken')
        if not token:
            break
    return places[:settings['limit']]

def domain(url):
    return (urllib.parse.urlsplit(url).hostname or '').lower().removeprefix('www.')

def public_target(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.port not in (None, 80, 443):
        raise ValueError('Only public HTTP(S) websites on standard ports are supported')
    port = u.port or (443 if u.scheme == 'https' else 80)
    addresses = socket.getaddrinfo(u.hostname, port, type=socket.SOCK_STREAM)
    ips = [a[4][0] for a in addresses]
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError('Private or non-public website blocked')
    return u, port, ips[0]

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip):
        super().__init__(host, port, timeout=12)
        self.ip = ip
    def connect(self):
        sock = socket.create_connection((self.ip, self.port), self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)

class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.links, self.skip = [], [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if tag == 'a':
            self.links.extend(v for k, v in attrs if k == 'href' and v)
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)
    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(re.sub(r'\s+', ' ', data).strip())

def fetch_website(url):
    for _ in range(4):
        u, port, ip = public_target(url)
        if u.scheme == 'https':
            conn = PinnedHTTPS(u.hostname, port, ip)
        else:
            conn = http.client.HTTPConnection(ip, port, timeout=12)
        try:
            path = urllib.parse.urlunsplit(('', '', u.path or '/', u.query, ''))
            conn.request('GET', path, headers={'Host': u.hostname, 'User-Agent': 'ContinereResearchPOC/0.1', 'Accept': 'text/html'})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                url = urllib.parse.urljoin(url, r.getheader('Location', ''))
                continue
            if r.status != 200 or 'text/html' not in r.getheader('Content-Type', ''):
                raise ValueError(f'Website unavailable (HTTP {r.status})')
            raw = r.read(500_001)
            if len(raw) > 500_000:
                raise ValueError('Website too large for bounded research')
            p = Text()
            p.feed(raw.decode('utf-8', errors='replace'))
            text = '\n'.join(p.parts)[:24000]
            emails = set(re.findall(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', text))
            emails.update(urllib.parse.unquote(link[7:].split('?')[0]) for link in p.links if link.lower().startswith('mailto:'))
            own = domain(url)
            emails = sorted(e for e in emails if re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[a-zA-Z]{2,}', e) and e.split('@')[1].lower() == own)
            return {'url': url, 'text': html.unescape(text), 'emails': emails, 'links': p.links[:150]}
        finally:
            conn.close()
    raise ValueError('Too many website redirects')

def demo_places(settings):
    names = ['Juniper Rehabilitation', 'Northstar Physical Therapy', 'Willow Recovery Center', 'Cedar Mobility Clinic', 'Harbor Rehabilitation', 'Meadow Therapy Group']
    return [{'place_id': f'demo-{i}', 'name': name, 'address': settings['geography'] + ' · fictional address',
        'website': f'https://clinic-{i}.example', 'source': 'https://example.com/demo'} for i, name in enumerate(names[:settings['limit']])]
