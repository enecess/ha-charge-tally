import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {resolve,sep} from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=resolve('custom_components/charge_tally/www');
export async function createCardFixture(t,config={}){
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
  const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||undefined,headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage();t.after(()=>page.close());
  const errors=[];page.on('pageerror',error=>errors.push(error.message));t.after(()=>assert.deepEqual(errors,[], 'No uncaught browser errors'));
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(()=>customElements.get('charge-tally-card'));
  await page.evaluate(config=>{
    const snapshot={generation:1,points:[{id:'p',name:'Garage',status:'idle',active:true,available:true,selected_identity_id:'i',identity_entity_id:'select.garage',power_w:'0',current_price:'.5',quality:[]}],archived_points:[],identities:[{id:'i',name:'Family',active:true},{id:'j',name:'Guest',active:true}],timezone:'UTC',currency:'CNY'};
    const pending=[],listeners=new Map();
    const connection={connected:true,addEventListener:(k,f)=>listeners.set(k,f),removeEventListener:k=>listeners.delete(k),subscribeMessage:async callback=>{queueMicrotask(()=>callback(snapshot));return ()=>{};}};
    const card=document.createElement('charge-tally-card');card.setConfig(config);
    const hass={language:'en',connection,states:{'select.garage':{state:'Family'}},callWS:request=>new Promise((resolve,reject)=>pending.push({request,resolve,reject}))};
    window.fixture={card,snapshot,pending,listeners,hass};card.hass=hass;document.body.append(card);
  },config);
  return {page};
}
