import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {resolve,sep} from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=resolve('custom_components/charge_tally/www');
export async function openCompactDetails(page,overrides={}){
  await page.evaluate(overrides=>{
    const record={id:'r',revision:1797,point_id:'p',identity_id:'i',start:'2026-10-29T16:57:02.002070Z',end:'2026-10-29T19:29:15.123456Z',timezone:'UTC',status:'ended',source:'automatic',energy_kwh:'17.675',known_cost:'5.286525',cost_complete:false,has_known_cost:true,quality:['estimated','unavailable','missing_energy','reset'],quality_spans:[{start:'2026-10-29T19:04:11.106208Z',end:'2026-10-29T19:04:16.207151Z',quality:['missing_energy','reset']}]};
    const period=(start,end,energy_kwh,cost,unit_price)=>({start:`2026-10-29T${start}Z`,end:`2026-10-29T${end}Z`,local_date:'2026-10-29',energy_kwh,cost,unit_price,cost_basis:'tariff',quality:['estimated']});
    const billing_periods=[period('16:57:02.002070','17:00:00','0.3194','0.07985','0.25'),period('17:00:00','19:04:11.106208','14.4884','4.34652','0.3'),period('19:04:16.207151','19:29:15.123456','2.8672','0.86016','0.3')];
    fixture.compact={record:{...record,...overrides},billing_periods,segments:billing_periods,revisions:[]};
    fixture.card.snapshot={...fixture.card.snapshot,currency:'EUR'};fixture.card.openDialog('details',fixture.compact);
  },overrides);
}
export async function createCardFixture(t,config={},{insecure=false,timezoneId}={}){
  const server=createServer(async(req,res)=>{
    try{
      const url=new URL(req.url,'http://localhost');
      if(url.pathname==='/'){res.setHeader('Content-Type','text/html');res.end('<!doctype html><meta charset="utf-8"><style>body{font:16px sans-serif;margin:16px}charge-tally-card{display:block;max-width:900px}</style><script type="module" src="/charge-tally-card.js"></script>');return;}
      const file=resolve(root,'.'+decodeURIComponent(url.pathname));
      if(!file.startsWith(root+sep)||!file.endsWith('.js')){res.writeHead(403).end();return;}
      res.setHeader('Content-Type','text/javascript');res.end(await readFile(file));
    }catch{res.writeHead(404).end();}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||undefined,headless:true,
    args:insecure?['--host-resolver-rules=MAP charge-tally.test 127.0.0.1','--no-proxy-server']:[],
  });
  t.after(()=>browser.close());
  const page=await browser.newPage({timezoneId});t.after(()=>page.close());
  const errors=[];page.on('pageerror',error=>errors.push(error.message));t.after(()=>assert.deepEqual(errors,[], 'No uncaught browser errors'));
  await page.goto(`http://${insecure?'charge-tally.test':'127.0.0.1'}:${server.address().port}`);
  await page.waitForFunction(()=>customElements.get('charge-tally-card'));
  await page.evaluate(config=>{
    const snapshot={generation:1,points:[{id:'p',name:'Garage',status:'idle',recording_state:'idle',detection_state:'waiting',candidate_identity_id:null,detection_enabled:true,active:true,available:true,selected_identity_id:'i',identity_entity_id:'select.garage',power_w:'0',current_price:'.5',quality:[]}],archived_points:[],identities:[{id:'i',name:'Family',active:true},{id:'j',name:'Guest',active:true}],timezone:'UTC',currency:'CNY'};
    const pending=[],exports=[],urls={created:[],revoked:[]},listeners=new Map();
    const createURL=URL.createObjectURL.bind(URL),revokeURL=URL.revokeObjectURL.bind(URL);
    URL.createObjectURL=blob=>{const url=createURL(blob);urls.created.push(url);return url;};
    URL.revokeObjectURL=url=>{urls.revoked.push(url);revokeURL(url);};
    const connection={connected:true,addEventListener:(k,f)=>listeners.set(k,f),removeEventListener:k=>listeners.delete(k),subscribeMessage:async callback=>{queueMicrotask(()=>callback(snapshot));return ()=>{};}};
    const card=document.createElement('charge-tally-card');card.setConfig(config);
    const hass={fetchWithAuth:(url,options)=>new Promise((resolve,reject)=>exports.push({url,options,payload:JSON.parse(options.body),resolve,reject})),language:'en',connection,states:{'select.garage':{state:'Family'}},callWS:request=>new Promise((resolve,reject)=>pending.push({request,resolve,reject}))};
    window.fixture={card,snapshot,pending,exports,urls,listeners,hass};card.hass=hass;document.body.append(card);
  },config);
  return {page};
}
