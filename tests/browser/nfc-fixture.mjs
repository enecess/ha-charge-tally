import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {resolve,sep} from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=resolve('custom_components/charge_tally/www');

export async function createNfcFixture(t,language='en'){
  const server=createServer(async(req,res)=>{
    try{
      const url=new URL(req.url,'http://localhost');
      if(url.pathname==='/'){
        res.setHeader('Content-Type','text/html');
        res.end('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><script type="module" src="/nfc-panel.js"></script>');return;
      }
      const file=resolve(root,'.'+decodeURIComponent(url.pathname));
      if(!file.startsWith(root+sep)||!file.endsWith('.js')){res.writeHead(403).end();return;}
      res.setHeader('Content-Type','text/javascript');res.end(await readFile(file));
    }catch{res.writeHead(404).end();}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||undefined,headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:390,height:844}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  t.after(()=>assert.deepEqual(errors,[]));
  await page.goto(`http://127.0.0.1:${server.address().port}/?entry_id=entry`);
  await page.waitForFunction(()=>customElements.get('charge-tally-nfc-panel'),{},{timeout:5000});
  await page.evaluate(language=>{
    const catalog={
      points:[{id:'p',name:'Garage',active:true}],
      identities:[{id:'i',name:'Family',active:true},{id:'j',name:'Guest',active:true},{id:'unassigned',name:'Unassigned',active:true}],
      tags:[{id:'t',name:'Charging tag'}],
      devices:[{id:'d1',name:'Phone',active:true},{id:'d2',name:'Phone',active:true}],
    };
    const fixture={rules:[],configs:{},posts:0,lost:false,external:false,paused:false,catalog};
    const same=(a,b)=>JSON.stringify(a?.actions)===JSON.stringify(b?.actions);
    const hass={language,user:{is_admin:true},config:{components:['config','automation']},
      connection:{connected:true},
      callApi:async(method,path,config)=>{
        const id=decodeURIComponent(path.split('/').at(-1));
        if(method==='GET'){
          if(!fixture.configs[id])throw {status_code:404};
          return structuredClone(fixture.configs[id]);
        }
        if(method==='POST'){
          fixture.posts++;fixture.configs[id]=structuredClone(config);fixture.external=false;
          if(fixture.lost){fixture.lost=false;throw {code:'disconnected'};}
        }else if(method==='DELETE')delete fixture.configs[id];
      },
      callWS:async msg=>{
        const command=msg.type.split('/').at(-1);
        if(command==='catalog')return structuredClone(catalog);
        if(command==='list')return structuredClone(fixture.rules);
        if(command==='prepare'){
          let rule=fixture.rules.find(x=>x.rule_id===msg.rule_id);
          if(!rule){rule={rule_id:'r',automation_id:'a',revision:0,applied:null,pending:null};fixture.rules.push(rule);}
          const draft=msg.draft||rule.applied?.draft;
          const version=(rule.applied?.version||0)+1;
          rule.pending={operation_id:msg.operation_id,rule_id:rule.rule_id,automation_id:rule.automation_id,
            revision:++rule.revision,kind:msg.kind,draft,version,
            expected_config:rule.applied?.automation_config||null,
            desired_config:msg.kind==='delete'?null:{id:rule.automation_id,alias:'Managed',description:'Managed',actions:[{data:{version,...draft}}]},
          };return structuredClone(rule.pending);
        }
        const rule=fixture.rules.find(x=>x.rule_id===msg.rule_id||x.pending?.operation_id===msg.operation_id);
        if(command==='inspect'){
          const pending=rule.pending,observed=msg.observed_config;
          return {config_status:fixture.external?'external':!observed?(pending?'pending':'missing'):pending?'pending':'synced',
            runtime_status:fixture.paused?'paused':'enabled',automation_entity_id:'automation.managed',
            pending_state:pending?(same(observed,pending.desired_config)?'applied':same(observed,pending.expected_config)?'unwritten':'conflict'):null};
        }
        if(command==='confirm'){
          if(!same(msg.observed_config,rule.pending.desired_config))throw {code:'conflict'};
          if(rule.pending.kind==='delete'){fixture.rules=[];return null;}
          rule.applied={version:rule.pending.version,draft:rule.pending.draft,automation_config:msg.observed_config};
          rule.pending=null;rule.revision++;return structuredClone(rule);
        }
        if(command==='cancel'){rule.pending=null;rule.deleting=false;return structuredClone(rule);}
        throw Error(command);
      }};
    const panel=document.createElement('charge-tally-nfc-panel');
    fixture.hass=hass;fixture.panel=panel;window.fixture=fixture;
    panel.hass=hass;document.body.append(panel);
  },language);
  return {page};
}
