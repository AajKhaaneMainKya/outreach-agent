import {timingSafeEqual} from 'node:crypto';
export default async function handler(req,res){
 const password=process.env.GTM_REMOTE_PASSWORD;
 const origin=process.env.GTM_PUBLIC_ORIGIN;
 const backend=process.env.GTM_BACKEND_URL;
 res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');
 if(!password||!origin||!backend)return res.status(503).send('Workspace deployment configuration is incomplete.');
 const expected=Buffer.from('Basic '+Buffer.from('continere:'+password).toString('base64'));
 const supplied=Buffer.from(req.headers.authorization||'');
 if(supplied.length!==expected.length||!timingSafeEqual(supplied,expected)){
  res.setHeader('WWW-Authenticate','Basic realm="Continere private workspace"');return res.status(401).send('Sign in to the private Continere workspace.');
 }
 if(!['GET','POST'].includes(req.method))return res.status(405).end();
 if(req.method==='POST'&&req.headers.origin!==origin)return res.status(403).send('Open the production workspace before submitting.');
 const path=typeof req.query?.__path==='string'?'/'+req.query.__path:new URL(req.url,origin).pathname;
 if(!['/','/rehab','/playbook','/app.js','/style.css','/playbook.js','/playbook-fragment.html','/favicon.svg'].includes(path)&&!path.startsWith('/api/'))return res.status(404).end();
 const url=new URL(backend);if(url.protocol!=='https:')return res.status(503).end();
 url.pathname=path;url.search=new URL(req.url,origin).search;
 try{
  const headers={'Authorization':req.headers.authorization};
  let body;
  if(req.method==='POST'){
   if(req.headers['content-type']!=='application/json')return res.status(400).send('JSON required');
   body=JSON.stringify(req.body);if(Buffer.byteLength(body)>100000)return res.status(413).end();
   headers['Content-Type']='application/json';headers.Origin=origin;headers['X-CSRF-Token']=req.headers['x-csrf-token']||'';
  }
  const response=await fetch(url,{method:req.method,headers,body,redirect:'manual',signal:AbortSignal.timeout(25000)});
  for(const name of ['content-type','content-security-policy','referrer-policy','www-authenticate'])if(response.headers.has(name))res.setHeader(name,response.headers.get(name));
  res.status(response.status).send(Buffer.from(await response.arrayBuffer()));
 }catch{return res.status(503).send('The WSL agent is offline. Keep the computer awake and restart its tunnel.');}
}
