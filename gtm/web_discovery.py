"""No-key search discovery with bounded provider fallbacks. Search snippets are leads, never verified facts."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit,urljoin
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gtm import providers

BLOCKED = {'facebook.com','instagram.com','linkedin.com','youtube.com','yelp.com','tripadvisor.com','google.com','maps.google.com','duckduckgo.com','bing.com','yellowpages.com','mapquest.com','reddit.com','wikipedia.org','massagecentersnearme.com','bestdayspas.com','austinstaysweird.com','theaustinthings.com'}

# Travel publishers and directories are evidence sources, not businesses.
PUBLISHERS={'visitflorida.com','floridatrippers.com','travelandleisure.com','tripstodiscover.com','timeout.com','cntraveler.com','fodors.com','lonelyplanet.com'}

DIRECTORIES={'healthgrades.com','healthprofs.com','zocdoc.com','psychologytoday.com','doximity.com','webmd.com','findatopdoc.com','npidb.org','npiprofile.com','vitadox.com','dietitiansondemand.com'}
def directory_source(url):
 host=providers.domain(url)
 path=urlsplit(url).path.lower()
 return any(host==d or host.endswith('.'+d) for d in DIRECTORIES) or bool(re.search(r'/(?:[^/]*directory|find-(?:a-)?(?:dietitian|nutritionist)|search|listing)(?:/|$)',path))

def resolve_directory(row,city,budget):
 """Follow actual listing -> profile -> external practice links, never save listing."""
 source=row.get('href','');host=providers.domain(source)
 if host not in DIRECTORIES or budget[0]<=0:return []
 fetch_page=providers.fetch_website
 def read(url):
  if budget[0]<=0:raise ValueError('Directory page budget reached')
  budget[0]-=1
  return fetch_page(url)
 try:listing=read(source)
 except (ValueError,OSError):return []
 profiles=[]
 for link in listing.get('links',[]):
  url=urljoin(listing.get('url',source),link)
  if providers.domain(url)!=host:continue
  path=urlsplit(url).path
  if (host=='healthprofs.com' and re.search(r'/nutritionists-dietitians/[^/]+/\d+',path)) or (host=='healthgrades.com' and re.search(r'/(?:providers|provider)/[^/]+',path)):
   if url not in profiles:profiles.append(url)
 out=[]
 for url in profiles[:2]:
  if budget[0]<=0:break
  try:profile=read(url)
  except (ValueError,OSError):continue
  for link in profile.get('links',[]):
   target=urljoin(profile.get('url',url),link);targethost=providers.domain(target)
   if targethost==host or urlsplit(target).scheme not in ('http','https'):continue
   # Listing/profile advertising, social and booking infrastructure are not practices.
   if not business_lead('Practice website',target) or any(x in targethost for x in ('google','amazon','doubleclick','cloudflare','healthgrades','healthprofs')):continue
   if any(x in urlsplit(target).path.lower() for x in ('privacy','terms','advertis','login','signin')):continue
   try:providers.public_target(target)
   except (ValueError,OSError):continue
   out.append({'href':target,'title':targethost+' · practice website linked from provider profile','body':'External practice website linked by '+url,'search_backend':row.get('search_backend','duckduckgo'),'search_attempts':row.get('search_attempts',[]),'discovery_provenance':{'directory_url':source,'profile_url':url,'website_url':target,'verification':'Provider-profile link only; business identity, location and ICP criteria still require research'}})
   break
 return out

def business_lead(title,url):
    """Reject clear directories/editorial roundups without deciding ICP fit."""
    host=providers.domain(url)
    if not host or directory_source(url) or any(host==d or host.endswith('.'+d) for d in BLOCKED|PUBLISHERS):return False
    title=str(title or '').strip().lower()
    if not title:return False
    if any(s in title for s in ('top 10','best spas','best day spa in','best day spas in','expert picks','directory','near me')):return False
    path=urlsplit(url).path.lower()
    if re.search(r'/(?:articles?|travel-ideas|directories|directory|roundups?)(?:/|$)',path):return False
    if re.search(r'/(?:best|top)-[^/]*(?:spas|spa-resorts|wellness-centers|dietitians)(?:-|/|$)',path):return False
    # Numeric listicles describe several businesses, even without "best".
    if re.match(r'^(?:the\s+)?\d+\s+',title) and re.search(r'\b(?:spas|resorts|wellness centers|dietitians)\b',title):return False
    if re.search(r'\b(?:florida|united states|usa)\s+spas\s+and\s+wellness centers\b',title):return False
    return True

SEARCH_BACKENDS = ('duckduckgo', 'brave', 'mojeek')

def _search_backends(ddgs, query, limit):
    attempts = []
    for backend in SEARCH_BACKENDS:
        try:
            rows = list(ddgs(timeout=12).text(query, max_results=limit, backend=backend))
        except Exception:
            attempts.append({'backend': backend, 'outcome': 'unavailable'})
            continue
        rows = [row for row in rows if isinstance(row, dict) and row.get('href')]
        attempts.append({'backend': backend, 'outcome': 'results' if rows else 'empty'})
        if rows:
            return [dict(row, search_backend=backend, search_attempts=list(attempts)) for row in rows]
    if any(item['outcome'] == 'unavailable' for item in attempts):
        raise ValueError('Search providers are unavailable or returned no results; no prospects invented')
    return []

def search(query, limit=10):
    """Use DDGS in-process, or the isolated Hermes interpreter when absent."""
    try:
        from ddgs import DDGS
    except ImportError:
        interpreter = Path(os.environ.get('GTM_SEARCH_PYTHON', str(Path.home()/'.hermes/hermes-agent/venv/bin/python')))
        if not interpreter.is_file():
            raise ValueError('Search dependency is not installed in the Hermes environment')
        result = subprocess.run([str(interpreter), str(Path(__file__).resolve()), '--search'], input=json.dumps({'query':query,'limit':limit}), text=True, capture_output=True, timeout=45)
        if result.returncode:
            raise ValueError('Search is unavailable; no prospects invented')
        return json.loads(result.stdout)
    return _search_backends(DDGS, query, limit)

def discover(term, city, limit=5, directory_budget=None):
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Search limit must be 1–10')
    if not isinstance(city,str) or not city.strip() or len(city)>160:
        raise ValueError('A campaign city is required')
    query = f'{term} in {city}'
    rows = search(query, min(30,max(10,limit*3)))
    # Direct business pages first; directories only seed linked individual profiles.
    direct=[r for r in rows if not directory_source(r.get('href',''))]
    budget=directory_budget if directory_budget is not None else [3]
    for directory in [r for r in rows if directory_source(r.get('href',''))][:1]:
        direct.extend(resolve_directory(directory,city,budget))
    if not any(business_lead(r.get('title',''),r.get('href','')) for r in direct):
        query_direct=query+' '+ ' '.join('-site:'+host for host in sorted(DIRECTORIES)[:8])
        try:direct.extend(search(query_direct,min(20,max(10,limit*2))))
        except (ValueError,OSError):pass
    rows=direct
    places=[]; seen=set()
    for row in rows:
        url=row.get('href',''); host=providers.domain(url)
        title=str(row.get('title',''))[:300]
        if host in seen or not business_lead(title,url):continue
        try:providers.public_target(url)
        except (ValueError,OSError):continue
        seen.add(host)
        places.append({'place_id':'web-'+hashlib.sha256(host.encode()).hexdigest()[:24], 'name':title, 'website':url,'address':'','search_city':city,'source':url,'discovery_source':row.get('search_backend','duckduckgo'),'search_attempts':row.get('search_attempts',[]),'search_query':query,'search_snippet':str(row.get('body',''))[:1500], 'discovery_provenance':row.get('discovery_provenance',{'search_url':url,'query':query}), 'evidence_status':'Search result only; qualification, address, GMB number and reviews are unverified'})
        if len(places)>=limit:break
    return places

if __name__=='__main__':
    # Subprocess entry must also work when invoked outside project cwd.
    request=json.load(sys.stdin)
    print(json.dumps(search(request['query'],request['limit'])))
