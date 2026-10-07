import {timingSafeEqual,randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
export const config={api:{bodyParser:{sizeLimit:'4mb'}}};
const prefix='continere:v1:';
const reads=['/api/state','/api/playbook','/api/playbook/campaigns','/api/account','/api/entry-drafts'];
const files={'/':'index.html','/rehab':'index.html','/playbook':'index.html','/app.js':'app.js','/playbook.js':'playbook.js','/playbook-fragment.html':'playbook-fragment.html','/style.css':'style.css','/favicon.svg':'favicon.svg'};
const mime={html:'text/html; charset=utf-8',js:'text/javascript',css:'text/css',svg:'image/svg+xml'};
const equal=(a,b)=>{const x=Buffer.from(a||''),y=Buffer.from(b||'');return x.length===y.length&&timingSafeEqual(x,y)};
export function allowedAction(path){return ['/api/run','/api/config','/api/sync','/api/playbook/research','/api/playbook/mission','/api/playbook/create'].includes(path)||/^\/api\/playbook\/[a-f0-9]{32}\/(prepare-script|advance|park|retry|edit|approve|handover|outcome)$/.test(path)||/^\/api\/prospect\/[a-f0-9]{32}\/(approve|reject|edit|suppress|regenerate|reply)$/.test(path);}
export async function redis(command){
 const endpoint=process.env.UPSTASH_REDIS_REST_URL||process.env.KV_REST_API_URL;
 const token=process.env.UPSTASH_REDIS_REST_TOKEN||process.env.KV_REST_API_TOKEN;
 if(!endpoint||!token)throw Error('Queue unavailable');
 const r=await fetch(endpoint,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(command),signal:AbortSignal.timeout(10000)});
 if(!r.ok)throw Error('Queue unavailable');const v=await r.json();if(v.error)throw Error('Queue unavailable');return v.result;
}
export default async function handler(req,res){
 res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer');
 res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
 const origin=process.env.GTM_PUBLIC_ORIGIN,password=process.env.GTM_CLOUD_PASSWORD,csrf=process.env.GTM_CLOUD_CSRF;
 if(!origin||!password||!csrf)return res.status(503).json({error:'Private cloud workspace is not configured yet.'});
 const path=typeof req.query?.__path==='string'?'/'+req.query.__path:new URL(req.url,origin).pathname;
 try{
  if(path==='/api/worker'){
   if(req.method!=='POST'||!equal(req.headers.authorization,'Bearer '+process.env.GTM_WORKER_TOKEN)||!process.env.GTM_WORKER_TOKEN)return res.status(401).json({error:'Worker authentication required'});
   const body=req.body||{};
   if(body.op==='poll'){
    const script="redis.call('SET',KEYS[1],ARGV[1],'EX',90);local id=redis.call('LPOP',KEYS[2]);if not id then return false end;local raw=redis.call('GET',ARGV[2]..id);if not raw then return false end;local job=cjson.decode(raw);job.stage='claimed';job.claimed_at=ARGV[1];redis.call('SET',ARGV[2]..id,cjson.encode(job));return cjson.encode(job)";
    const raw=await redis(['EVAL',script,'2',prefix+'heartbeat',prefix+'queue',String(Date.now()),prefix+'job:']);return res.json({job:raw?JSON.parse(raw):null});
   }
   if(body.op==='sync'){
    if(!body.snapshots||Object.keys(body.snapshots).some(k=>!reads.includes(k))||reads.some(k=>!body.snapshots[k]))return res.status(400).json({error:'Invalid snapshot'});
    await redis(['SET',prefix+'snapshot',JSON.stringify({published_at:Date.now(),values:body.snapshots})]);return res.json({ok:true});
   }
   if(body.op==='complete'){
    if(!/^[a-f0-9-]{36}$/.test(body.id||''))return res.status(400).json({error:'Invalid job'});
    const script="local raw=redis.call('GET',KEYS[1]);if not raw then return false end;local old=cjson.decode(raw);if old.stage=='complete' or old.stage=='needs_review' then return true end;if old.stage~='claimed' then return false end;local result=cjson.decode(ARGV[1]);old.stage=result.stage;old.status=result.status;old.result=result.result;old.error=result.error;redis.call('SET',KEYS[1],cjson.encode(old),'EX',604800);return true";
    const ok=await redis(['EVAL',script,'1',prefix+'job:'+body.id,JSON.stringify({stage:body.stage==='needs_review'?'needs_review':'complete',status:body.status,result:body.result,error:body.error})]);return res.status(ok?200:409).json({ok:!!ok});
   }
   return res.status(400).json({error:'Unknown worker operation'});
  }
  const auth='Basic '+Buffer.from('continere:'+password).toString('base64');
  if(!equal(req.headers.authorization,auth)){res.setHeader('WWW-Authenticate','Basic realm="Outreach agent"');return res.status(401).send('Sign in to Outreach agent with your existing access details.');}
  if(req.method==='GET'&&files[path]){
   const name=files[path];let body=await readFile(resolve(process.cwd(),'assets',name));if(name==='index.html')body=Buffer.from(body.toString().replaceAll('__CSRF_TOKEN__',csrf));
   res.setHeader('Content-Type',mime[name.split('.').pop()]);return res.status(200).send(body);
  }
  if(req.method==='GET'&&reads.includes(path)){
   const raw=await redis(['GET',prefix+'snapshot']);if(!raw)return res.status(503).json({error:'Start the private WSL worker to sync your workspace.'});
   return res.json(JSON.parse(raw).values[path]);
  }
  if(req.method==='GET'&&path==='/api/cloud-status'){
   const heartbeat=await redis(['GET',prefix+'heartbeat']);return res.json({online:!!heartbeat,worker:'Private WSL · outbound polling only',model:'gpt-6-luna',sending:'Human approval required'});
  }
  if(req.method==='GET'&&/^\/api\/jobs\/[a-f0-9-]{36}$/.test(path)){
   const raw=await redis(['GET',prefix+'job:'+path.split('/').pop()]);if(!raw)return res.status(404).json({error:'Queued action not found'});const j=JSON.parse(raw);if(j.stage==='claimed'&&Date.now()-Number(j.claimed_at)>150000)return res.json({stage:'needs_review',error:'Worker delivery was interrupted. Inspect saved state before submitting again; no automatic replay.'});return res.json({stage:j.stage,status:j.status,result:j.result,error:j.error});
  }
  if(req.method==='POST'&&/\/send$/.test(path))return res.status(403).json({error:'Cloud email sending is disabled. Spa and Dietitian calls/texts remain manual.'});
  if(req.method==='POST'&&allowedAction(path)){
   if(req.headers.origin!==origin||!equal(req.headers['x-csrf-token'],csrf))return res.status(403).json({error:'Open the local dashboard to perform this action'});
   if(req.headers['content-type']!=='application/json'||!req.body||typeof req.body!=='object'||Array.isArray(req.body)||Buffer.byteLength(JSON.stringify(req.body))>100000)return res.status(400).json({error:'Use a small JSON object'});
   const heartbeat=await redis(['GET',prefix+'heartbeat']);if(!heartbeat)return res.status(503).json({error:'Private WSL worker is offline. Keep your computer awake and start the worker before submitting.'});
   const id=randomUUID(),job={id,path,data:req.body,stage:'queued',created_at:Date.now()};
   await redis(['EVAL',"redis.call('SET',KEYS[1],ARGV[1]);redis.call('RPUSH',KEYS[2],ARGV[2]);return true",'2',prefix+'job:'+id,prefix+'queue',JSON.stringify(job),id]);return res.status(202).json({cloud_job:id});
  }
  return res.status(404).json({error:'Not found'});
 }catch{return res.status(503).json({error:'Cloud queue temporarily unavailable. No action has been approved automatically.'});}
}
