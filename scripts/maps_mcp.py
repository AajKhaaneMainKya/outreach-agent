"""Read-only Google Places MCP server (stdio JSON-RPC). No sending or workspace writes."""
import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gtm import providers,playbook,playbook_campaigns as pc
TOOLS=[
 {'name':'search_businesses','description':'Search VJ-approved Google Maps/Places terms in the campaign city. Requires a user-configured Places key. Read-only; bounded to six provider operations per run.','inputSchema':{'type':'object','properties':{'search_term':{'type':'string'},'limit':{'type':'integer','minimum':1,'maximum':10}},'required':['search_term']}},
 {'name':'place_details','description':'Read profile, GMB business number, review count and API review sample for a place returned by search_businesses. Sample is NOT certified five newest reviews.','inputSchema':{'type':'object','properties':{'place_id':{'type':'string'}},'required':['place_id']}}
]
class Maps:
 def __init__(self,campaign):self.campaign=campaign;self.places={};self.calls=0
 def call(self,name,args):
  if not os.environ.get('GOOGLE_PLACES_API_KEY'):return {'unavailable':True,'reason':'Google Places key not configured. Do not invent Maps results or enable billing.','next_step':'Configure GOOGLE_PLACES_API_KEY privately in the WSL project .env and set Google-side quotas.'}
  if self.calls>=6:return {'unavailable':True,'reason':'Per-run Maps operation limit reached; ask for further research.'}
  if name=='search_businesses':
   term=args.get('search_term');allowed=playbook.policy()[self.campaign['icp']]['search']+[self.campaign.get('business','')]
   if not term or term not in allowed:raise ValueError('Use an exact approved search term or supplied business name')
   limit=args.get('limit',5)
   if type(limit) is not int or not 1<=limit<=10:raise ValueError('Search limit must be 1–10')
   self.calls+=1;found=providers.discover({'query':term,'geography':self.campaign['city'],'limit':limit})
   for p in found:self.places[p['place_id']]=p
   return {'places':found,'operations_used':self.calls}
  if name=='place_details':
   pid=args.get('place_id')
   if pid not in self.places:raise ValueError('Choose a place returned in this session')
   self.calls+=1;return {'place':pc.details(self.places[pid]),'review_order':'Google API sample, NOT verified five newest','operations_used':self.calls}
  raise ValueError('Unknown read-only Maps tool')

def main():
 campaign=json.loads(os.environ.get('GTM_MAPS_CAMPAIGN','{}'));maps=Maps(campaign)
 for line in sys.stdin:
  try:
   request=json.loads(line);method=request.get('method');rid=request.get('id')
   if rid is None:continue
   if method=='initialize':result={'protocolVersion':request['params']['protocolVersion'],'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'continere-maps','version':'1.0.0'}}
   elif method=='ping':result={}
   elif method=='tools/list':result={'tools':TOOLS}
   elif method in ('resources/list','resources/templates/list','prompts/list'):result={('resourceTemplates' if method=='resources/templates/list' else method.split('/')[0]):[]}
   elif method=='tools/call':
    try:value=maps.call(request['params']['name'],request['params'].get('arguments',{}));result={'content':[{'type':'text','text':json.dumps(value)}],'isError':False}
    except Exception as e:result={'content':[{'type':'text','text':json.dumps({'error':str(e) if isinstance(e,ValueError) else 'Maps provider failed; no results invented'})}],'isError':True}
   else:print(json.dumps({'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'Method not found'}}),flush=True);continue
   print(json.dumps({'jsonrpc':'2.0','id':rid,'result':result}),flush=True)
  except Exception:print(json.dumps({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid request'}}),flush=True)
if __name__=='__main__':main()
