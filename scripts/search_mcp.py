"""Bounded read-only DuckDuckGo MCP server. No API credentials or sending."""
import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gtm import providers,playbook,web_discovery
TOOLS=[{'name':'search_businesses','description':'Discover business website leads using no-key DuckDuckGo, an exact VJ search term and campaign city. Search snippets are not qualification evidence or GMB reviews.','inputSchema':{'type':'object','properties':{'search_term':{'type':'string'},'limit':{'type':'integer','minimum':1,'maximum':10}},'required':['search_term']}},{'name':'place_details','description':'Read the public business website for a lead returned in this search session; does not supply verified GMB phone, review count or newest reviews.','inputSchema':{'type':'object','properties':{'place_id':{'type':'string'}},'required':['place_id']}}]
class Search:
 def __init__(self,campaign):self.campaign=campaign;self.places={};self.calls=0;self.directory_budget=[3]
 def call(self,name,args):
  if self.calls>=6:return {'unavailable':True,'reason':'Per-run web discovery operation limit reached'}
  if name=='search_businesses':
   term=args.get('search_term');allowed=playbook.policy()[self.campaign['icp']]['search']+[self.campaign.get('business','')]
   if not term or term not in allowed:raise ValueError('Use an exact VJ-approved term or supplied business name')
   self.calls+=1
   found=web_discovery.discover(term,self.campaign['city'],args.get('limit',5),directory_budget=self.directory_budget)
   for p in found:self.places[p['place_id']]=p
   return {'places':found,'operations_used':self.calls,'provider':'duckduckgo','no_api_key':True}
  if name=='place_details':
   pid=args.get('place_id')
   if pid not in self.places:raise ValueError('Choose a business returned in this session')
   self.calls+=1;p=self.places[pid];page=providers.fetch_website(p['website'])
   if providers.domain(page['url'])!=providers.domain(p['website']):raise ValueError('Cross-business redirect blocked')
   return {'place':p,'website_evidence':page,'operations_used':self.calls,'missing_evidence':['Verified GMB business number','Five newest Google reviews','Google review count']}
  raise ValueError('Unknown read-only search tool')

def main():
 search=Search(json.loads(os.environ.get('GTM_SEARCH_CAMPAIGN',os.environ.get('GTM_MAPS_CAMPAIGN','{}'))))
 for line in sys.stdin:
  try:
   r=json.loads(line);method=r.get('method');rid=r.get('id')
   if rid is None:continue
   if method=='initialize':result={'protocolVersion':r['params']['protocolVersion'],'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'continere-search','version':'1.0.0'}}
   elif method=='ping':result={}
   elif method=='tools/list':result={'tools':TOOLS}
   elif method in ('resources/list','resources/templates/list','prompts/list'):result={('resourceTemplates' if method=='resources/templates/list' else method.split('/')[0]):[]}
   elif method=='tools/call':
    try:value=search.call(r['params']['name'],r['params'].get('arguments',{}));result={'content':[{'type':'text','text':json.dumps(value)}],'isError':False}
    except Exception as e:result={'content':[{'type':'text','text':json.dumps({'error':str(e) if isinstance(e,ValueError) else 'Search provider unavailable; no results invented'})}],'isError':True}
   else:print(json.dumps({'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'Method not found'}}),flush=True);continue
   print(json.dumps({'jsonrpc':'2.0','id':rid,'result':result}),flush=True)
  except Exception:print(json.dumps({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid request'}}),flush=True)
if __name__=='__main__':main()
