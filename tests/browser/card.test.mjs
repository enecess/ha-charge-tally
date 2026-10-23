import test from 'node:test';
import assert from 'node:assert/strict';
import {createCardFixture} from './card-fixture.mjs';

test('custom date drafts query only the applied range across pushes and filters',async t=>{
  const {page}=await createCardFixture(t,{show_chart:false});
  await page.evaluate(()=>{fixture.card.setPeriod('custom');fixture.card.setExpanded('statistics',true);});
  assert.equal(await page.evaluate(()=>fixture.card.error),null);
  const dates=page.locator('input[type=date]');
  await dates.nth(0).fill('2026-09-01');await dates.nth(1).fill('2026-09-02');
  await page.getByRole('button',{name:'Apply range',exact:true}).click();
  await page.waitForFunction(()=>fixture.pending.length===1);
  await dates.nth(0).fill('2026-09-03');await dates.nth(1).fill('2026-09-04');
  await dates.nth(0).focus();
  await page.evaluate(()=>{window.dateNode=fixture.card.shadowRoot.activeElement;fixture.card.onSnapshot({...fixture.snapshot,generation:2});});
  assert.equal(await dates.nth(0).inputValue(),'2026-09-03');
  assert.equal(await page.evaluate(()=>fixture.card.shadowRoot.activeElement===dateNode),true);
  assert.equal(await page.evaluate(()=>fixture.pending.at(-1).request.start),'2026-09-01T00:00:00.000Z');
  await dates.nth(1).fill('');
  await page.evaluate(()=>{fixture.card.onSnapshot({...fixture.snapshot,generation:3});fixture.card.setFilter('identity_id','j');});
  assert.equal(await page.evaluate(()=>fixture.card.error),null);
  assert.equal(await page.evaluate(()=>fixture.pending.at(-1).request.start),'2026-09-01T00:00:00.000Z');
  await dates.nth(1).fill('2026-09-04');
  await page.getByRole('button',{name:'Apply range',exact:true}).click();
  assert.equal(await page.evaluate(()=>fixture.pending.at(-1).request.start),'2026-09-03T00:00:00.000Z');
  await page.evaluate(()=>{fixture.pending.at(-1).resolve({energy_kwh:'2',known_cost:'1',cost_complete:true});});
  await page.waitForFunction(()=>fixture.card.summary?.energy_kwh==='2');
  await page.evaluate(()=>{for(const p of fixture.pending.slice(0,-1))p.resolve({energy_kwh:'999'});});
  assert.equal(await page.evaluate(()=>fixture.card.summary.energy_kwh),'2');
  await dates.nth(0).fill('2026-09-05');
  await page.evaluate(()=>{fixture.card.setPeriod('daily');fixture.card.setPeriod('custom');});
  assert.equal(await page.evaluate(()=>fixture.pending.at(-1).request.start),'2026-09-03T00:00:00.000Z');
  assert.equal(await dates.nth(0).inputValue(),'2026-09-05');
});

test('25 history rows retain scroll through alternating query completions',async t=>{
  const {page}=await createCardFixture(t,{show_chart:false});
  await page.evaluate(()=>{
    fixture.card.setExpanded('statistics',true);fixture.card.setExpanded('records',true);
    const record={point_id:'p',identity_id:'i',start:'2026-09-19T00:00:00Z',end:'2026-09-19T01:00:00Z',timezone:'UTC',status:'ended',source:'manual',revision:1,energy_kwh:'1',known_cost:'0.5',cost_complete:true,quality:[]};
    fixture.results={summary:{energy_kwh:'25',known_cost:'12.5',cost_complete:true,active_count:0,completed_count:25,matched_count:25,has_energy_data:true,has_known_cost:true,quality:[],bucket_period:'hour',buckets:[]},records:{records:Array.from({length:25},(_,i)=>({...record,id:`record-${i}`})),total:25,offset:0,limit:25}};
    for(const pending of fixture.pending.splice(0))pending.resolve(pending.request.type==='charge_tally/query'?fixture.results.summary:fixture.results.records);
  });
  await page.locator('charge-tally-card li').nth(24).waitFor();
  await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight-100));
  const before=await page.evaluate(()=>window.scrollY);assert.ok(before>1000);
  for(let generation=2;generation<=7;generation++){
    await page.evaluate(generation=>fixture.card.onSnapshot({...fixture.snapshot,generation}),generation);
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(()=>window.scrollY),before);
    for(const type of generation%2?['charge_tally/records','charge_tally/query']:['charge_tally/query','charge_tally/records']){
      await page.evaluate(type=>{
        const index=fixture.pending.findIndex(p=>p.request.type===type);const pending=fixture.pending.splice(index,1)[0];
        pending.resolve(type==='charge_tally/query'?fixture.results.summary:fixture.results.records);
      },type);
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      assert.equal(await page.evaluate(()=>window.scrollY),before);
      assert.equal(await page.locator('charge-tally-card li').count(),25);
    }
  }
  await page.screenshot({path:'.superpowers/card-qa/task9-scroll-25-records.png'});
});

for(const exit of ['Enter','Escape'])test(`native identity menu survives pushes and ${exit}`,async t=>{
  const {page}=await createCardFixture(t);
  const select=page.locator('[data-point-id] select');await select.focus();
  await page.evaluate(()=>window.originalSelect=fixture.card.shadowRoot.activeElement);
  await select.click();
  if(exit==='Enter')await page.keyboard.press('ArrowDown');
  for(let generation=2;generation<=5;generation++){
    await page.evaluate(generation=>fixture.card.onSnapshot({...fixture.snapshot,generation,points:[{...fixture.snapshot.points[0],power_w:String(generation*100)}]}),generation);
    assert.equal(await page.evaluate(()=>fixture.card.shadowRoot.activeElement===originalSelect),true);
    assert.match(await page.locator('ha-card').textContent(),new RegExp(`${generation*100} W`));
  }
  await page.keyboard.press(exit);
  assert.equal(await page.evaluate(()=>fixture.card.shadowRoot.querySelector('[data-point-id] select')===originalSelect),true);
  if(exit==='Escape'){
    assert.equal(await page.evaluate(()=>fixture.card.shadowRoot.activeElement===originalSelect),true);
    assert.equal(await select.inputValue(),'i');
    assert.equal(await page.evaluate(()=>fixture.pending.length),0);
  }else{
    assert.equal(await select.inputValue(),'j');
    assert.equal(await select.isDisabled(),true);
    assert.deepEqual(await page.evaluate(()=>fixture.pending[0].request.service_data),{entity_id:'select.garage',option:'Guest'});
    await page.evaluate(()=>fixture.pending.shift().resolve({}));
    await page.waitForFunction(()=>fixture.pending.some(p=>p.request.type==='charge_tally/snapshot'));
    await page.evaluate(()=>fixture.pending.shift().resolve({...fixture.snapshot,points:[{...fixture.snapshot.points[0],selected_identity_id:'j',power_w:'500'}]}));
    await page.waitForFunction(()=>fixture.card.pendingSelections.size===0);
    assert.equal(await select.inputValue(),'j');
  }
  await page.screenshot({path:`.superpowers/card-qa/task9-menu-${exit.toLowerCase()}.png`});
});

test('snapshot preserves the actual focused select node',async t=>{
  const {page}=await createCardFixture(t);
  assert.deepEqual(await page.evaluate(()=>{
    const select=fixture.card.shadowRoot.querySelector('select');select.focus();window.selectedNode=select;
    fixture.card.onSnapshot({...fixture.snapshot,generation:2});
    return {same:select===fixture.card.shadowRoot.querySelector('select'),focused:fixture.card.shadowRoot.activeElement===select};
  }),{same:true,focused:true});
});
test('modules query independently only when expanded',async t=>{
  const {page}=await createCardFixture(t);
  assert.deepEqual(await page.evaluate(()=>fixture.pending.map(p=>p.request.type)),[]);
  await page.evaluate(()=>fixture.card.setExpanded('statistics',true));
  assert.deepEqual(await page.evaluate(()=>fixture.pending.map(p=>p.request.type)),['charge_tally/query']);
  await page.evaluate(()=>{fixture.card.setExpanded('statistics',false);fixture.card.onSnapshot({...fixture.snapshot,generation:2});fixture.card.setExpanded('records',true);});
  assert.deepEqual(await page.evaluate(()=>fixture.pending.map(p=>p.request.type)),['charge_tally/query','charge_tally/records']);
});
test('dialog language updates retain focused drafts and operations',async t=>{
  const {page}=await createCardFixture(t);
  assert.deepEqual(await page.evaluate(()=>{
    const c=fixture.card;c.openDialog('create');const d=c.dialog,note=d.node.querySelector('textarea');note.value='draft';note.dispatchEvent(new Event('input'));note.focus();
    d.requestId='request';d.preview={token:'token',record:{point_id:'p',identity_id:'i',timezone:'UTC',start:'2026-01-01T00:00:00Z',end:'2026-01-01T01:00:00Z',source:'manual'},segments:[],overlaps:[]};d.renderPreview();const before=d.node;d.node.scrollTop=40;const scroll=d.node.scrollTop;
    c.hass={...fixture.hass,language:'fr'};
    return {dialog:before===d.node,note:note===d.node.querySelector('textarea'),focused:c.shadowRoot.activeElement===note,draft:d.form.note,request:d.requestId,token:d.preview.token,scroll:d.node.scrollTop===scroll};
  }),{dialog:true,note:true,focused:true,draft:'draft',request:'request',token:'token',scroll:true});
});
test('focused point selector submits current names and keeps selection until confirmed',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{const s=fixture.card.shadowRoot.querySelector('[data-point-id] select');s.focus();fixture.card.onSnapshot({...fixture.snapshot,generation:2,identities:[fixture.snapshot.identities[0],{id:'j',name:'New guest',active:true}]});});
  await page.locator('[data-point-id] select').selectOption('j');
  assert.deepEqual(await page.evaluate(()=>fixture.pending[0].request.service_data),{entity_id:'select.garage',option:'New guest'});
  await page.evaluate(()=>{fixture.card.onSnapshot({...fixture.snapshot,generation:3});fixture.card.shadowRoot.querySelector('[data-point-id] select').blur();});
  assert.equal(await page.locator('[data-point-id] select').inputValue(),'j');
  await page.evaluate(()=>fixture.pending[0].resolve({}));await page.waitForFunction(()=>fixture.pending.length===2);
  assert.equal(await page.evaluate(()=>fixture.pending[1].request.type),'charge_tally/snapshot');
  await page.evaluate(()=>fixture.pending[1].resolve({...fixture.snapshot,points:[{...fixture.snapshot.points[0],selected_identity_id:'j'}]}));
  await page.waitForFunction(()=>fixture.card.pendingSelections.size===0);
  assert.equal(await page.locator('[data-point-id] select').inputValue(),'j');
});
test('failed selection is visible and restores confirmed identity',async t=>{
  const {page}=await createCardFixture(t);
  await page.locator('[data-point-id] select').selectOption('j');
  await page.evaluate(()=>fixture.pending[0].reject({code:'home_assistant_error'}));
  await page.waitForFunction(()=>!!fixture.card.error);
  await page.evaluate(()=>fixture.card.shadowRoot.querySelector('[data-point-id] select').blur());
  assert.equal(await page.locator('[data-point-id] select').inputValue(),'i');
  assert.match(await page.locator('[role=alert]').first().textContent(),/Home Assistant/);
});
for(const exit of ['Tab','Escape','outside'])test(`focused option changes apply only after blur (${exit})`,async t=>{
  const {page}=await createCardFixture(t);
  await page.locator('[data-point-id] select').focus();
  await page.evaluate(()=>fixture.card.onSnapshot({...fixture.snapshot,generation:2,identities:[{id:'i',name:'Renamed'},{id:'k',name:'New'}]}));
  assert.deepEqual(await page.locator('[data-point-id] option').allTextContents(),['Family','Guest']);
  if(exit==='outside')await page.locator('h2').click();else {await page.keyboard.press(exit);if(exit==='Escape')await page.keyboard.press('Tab');}
  assert.deepEqual(await page.locator('[data-point-id] option').allTextContents(),['Renamed','New']);
});
test('editor preserves title focus while translated snapshot options update',async t=>{
  const {page}=await createCardFixture(t);
  assert.deepEqual(await page.evaluate(()=>{
    const editor=document.createElement('charge-tally-card-editor');editor.setConfig({title:'Draft'});editor.hass=fixture.hass;document.body.append(editor);editor.snapshot=fixture.snapshot;editor.render();
    const title=editor.shadowRoot.querySelector('input');title.focus();title.value='Typing';title.dispatchEvent(new Event('input'));editor.hass={...fixture.hass,language:'de'};
    return {same:title===editor.shadowRoot.querySelector('input'),focused:editor.shadowRoot.activeElement===title,value:title.value,label:editor.shadowRoot.querySelector('label span').textContent};
  }),{same:true,focused:true,value:'Typing',label:'Titel'});
});
test('date drafts and chart metric survive push and language changes',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{fixture.card.setExpanded('statistics',true);fixture.card.setPeriod('custom');});
  await page.locator('input[type=date]').first().fill('2026-09-01');
  assert.deepEqual(await page.evaluate(()=>{
    const c=fixture.card,date=c.shadowRoot.querySelector('input[type=date]');date.focus();c.onSnapshot({...fixture.snapshot,generation:2});c.hass={...fixture.hass,language:'zh-Hans'};
    return {same:date===c.shadowRoot.querySelector('input[type=date]'),value:date.value,draft:c.rangeStart,expanded:c.expanded.statistics};
  }),{same:true,value:'2026-09-01',draft:'2026-09-01',expanded:true});
});
test('opening another section does not duplicate an in-flight summary',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{fixture.card.setExpanded('statistics',true);fixture.card.setExpanded('records',true);});
  assert.deepEqual(await page.evaluate(()=>fixture.pending.map(p=>p.request.type)),['charge_tally/query','charge_tally/records']);
});
test('snapshot refresh retains summary and keyed records, rejecting late scope responses',async t=>{
  const {page}=await createCardFixture(t,{show_chart:false});
  await page.evaluate(()=>{
    const c=fixture.card;c.setExpanded('statistics',true);c.setExpanded('records',true);
    fixture.summary={energy_kwh:'12',known_cost:'6',cost_complete:true};fixture.record={id:'r',point_id:'p',identity_id:'i',start:'2026-09-19T00:00:00Z',timezone:'UTC',status:'ended',energy_kwh:'10',known_cost:'5',cost_complete:true,quality:[]};fixture.recordPage={records:[fixture.record],total:1,limit:25};
    fixture.pending[0].resolve(fixture.summary);fixture.pending[1].resolve(fixture.recordPage);
  });
  await page.waitForFunction(()=>!!fixture.card.page);
  await page.evaluate(()=>{window.recordNode=fixture.card.shadowRoot.querySelector('li');fixture.card.onSnapshot({...fixture.snapshot,generation:2});});
  assert.match(await page.locator('ha-card').textContent(),/12 kWh/);assert.match(await page.locator('ha-card').textContent(),/10 kWh/);
  await page.evaluate(()=>{fixture.pending[2].resolve({...fixture.summary,energy_kwh:'13'});fixture.pending[3].resolve({...fixture.recordPage,records:[{...fixture.record,energy_kwh:'11'}]});});
  await page.waitForFunction(()=>fixture.card.summary.energy_kwh==='13');assert.equal(await page.evaluate(()=>recordNode===fixture.card.shadowRoot.querySelector('li')),true);
  await page.evaluate(()=>{fixture.card.onSnapshot({...fixture.snapshot,generation:3});fixture.card.setFilter('identity_id','j');fixture.pending[4].resolve({energy_kwh:'999'});fixture.pending[5].reject({code:'conflict'});fixture.pending[6].resolve({...fixture.summary,energy_kwh:'1'});fixture.pending[7].resolve({records:[],total:0,limit:25});});
  await page.waitForFunction(()=>fixture.card.summary?.energy_kwh==='1');assert.equal(await page.evaluate(()=>fixture.card.error),null);
  await page.evaluate(()=>{fixture.card.onSnapshot({...fixture.snapshot,generation:4});fixture.card.onSnapshot(null);fixture.pending[8].resolve(fixture.summary);fixture.pending[9].resolve(fixture.recordPage);});
  assert.deepEqual(await page.evaluate(()=>({summary:fixture.card.summary,page:fixture.card.page,rows:fixture.card.shadowRoot.querySelectorAll('li').length})),{summary:null,page:null,rows:0});
});
test('card and editor translate supported languages without replacing controls',async t=>{
  const {page}=await createCardFixture(t);
  for(const [language,title]of [['de','Titel'],['fr','Titre'],['pl','Tytuł'],['it-IT','Titolo']]){
    assert.equal(await page.evaluate(({language})=>{fixture.card.hass={...fixture.hass,language};let editor=document.querySelector('charge-tally-card-editor');if(!editor){editor=document.createElement('charge-tally-card-editor');editor.setConfig({});document.body.append(editor);}editor.hass={...fixture.hass,language};return editor.shadowRoot.querySelector('label span').textContent;},{language}),title);
  }
});
test('instances and display flags are independent; module toggles support keyboard',async t=>{
  const {page}=await createCardFixture(t,{show_records:false,show_chart:false});
  assert.equal(await page.locator('[data-section=records]').isVisible(),false);
  await page.locator('[data-section=statistics] > button').focus();await page.keyboard.press('Enter');
  assert.equal(await page.locator('[data-section=statistics] > button').getAttribute('aria-expanded'),'true');
  assert.deepEqual(await page.evaluate(()=>{const other=document.createElement('charge-tally-card');other.setConfig({});other.hass=fixture.hass;document.body.append(other);return other.expanded;}),{controls:true,statistics:false,records:false});
  await page.evaluate(()=>fixture.pending[0].resolve({energy_kwh:'2',known_cost:'1',cost_complete:true,buckets:[]}));
  await page.waitForFunction(()=>!!fixture.card.summary);
  assert.equal(await page.locator('charge-tally-card').first().locator('svg').isVisible(),false);
});
test('disconnect prevents stale selection and reconnect resets disposed controls',async t=>{
  const {page}=await createCardFixture(t);
  assert.deepEqual(await page.evaluate(()=>{
    const c=fixture.card,select=c.shadowRoot.querySelector('[data-point-id] select');select.focus();fixture.hass.connection.connected=false;fixture.listeners.get('disconnected')();select.value='j';select.dispatchEvent(new Event('change'));return {requests:fixture.pending.length,offline:c.view.status.textContent===c.t('offline'),pending:c.pendingSelections.size};
  }),{requests:0,offline:true,pending:0});
  await page.evaluate(()=>{fixture.hass.connection.connected=true;fixture.listeners.get('ready')();});
  await page.waitForFunction(()=>!!fixture.card.snapshot);
  await page.locator('[data-point-id] select').focus();
  assert.equal(await page.evaluate(()=>{const c=fixture.card,control=c.view.points.get('p').select;c.remove();return control.editing===false&&control.pending===null&&c.view===null;}),true);
});
test('chart metric and expanded data table preserve focus during refresh',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{fixture.card.setExpanded('statistics',true);fixture.pending[0].resolve({energy_kwh:'1',known_cost:'2',cost_complete:true,buckets:[{key:'a',label:'September',energy_kwh:'1',known_cost:'2',cost_complete:true}]});});
  await page.waitForFunction(()=>!!fixture.card.summary);
  assert.deepEqual(await page.evaluate(()=>{
    const c=fixture.card,metric=c.view.metric.node;metric.focus();c.onSnapshot({...fixture.snapshot,generation:2});const same=metric===c.view.metric.node&&c.shadowRoot.activeElement===metric;metric.blur();const table=c.shadowRoot.querySelector('details');table.open=true;const toggle=table.querySelector('summary');toggle.focus();c.hass={...fixture.hass,language:'de'};
    return {metric:same,table:table===c.shadowRoot.querySelector('details'),expanded:c.shadowRoot.querySelector('details').open,focused:c.shadowRoot.activeElement===toggle};
  }),{metric:true,table:true,expanded:true,focused:true});
});
test('removed identity cannot be submitted from protected old options',async t=>{
  const {page}=await createCardFixture(t);
  await page.locator('[data-point-id] select').focus();
  await page.evaluate(()=>fixture.card.onSnapshot({...fixture.snapshot,generation:2,identities:[fixture.snapshot.identities[0]]}));
  await page.locator('[data-point-id] select').selectOption('j');
  assert.deepEqual(await page.evaluate(()=>({requests:fixture.pending.length,error:fixture.card.error?.code})),{requests:0,error:'unavailable'});
});
test('period and page versions independently reject late responses',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{const c=fixture.card;c.setExpanded('statistics',true);c.setExpanded('records',true);c.setPeriod('monthly');c.setOffset(25);fixture.pending[0].resolve({energy_kwh:'old'});fixture.pending[1].reject({code:'conflict'});fixture.pending[2].resolve({energy_kwh:'new',buckets:[]});fixture.pending[3].resolve({records:[],limit:25,total:26});});
  await page.waitForFunction(()=>fixture.card.page?.total===26);
  assert.deepEqual(await page.evaluate(()=>({energy:fixture.card.summary.energy_kwh,offset:fixture.card.offset,error:fixture.card.error})),{energy:'new',offset:25,error:null});
});
test('select protection clones the latest queued options and dispose drops pending changes',async t=>{
  const {page}=await createCardFixture(t);
  assert.deepEqual(await page.evaluate(async()=>{
    const {SelectControl}=await import('/card-controls.js?v=0.1.2-7');const control=new SelectControl();document.body.append(control.node);control.update({options:[{id:'a',name:'A'}],value:'a'});const original=control.node.firstChild;control.update({options:[{id:'a',name:'A'}],value:'a'});const untouched=original===control.node.firstChild;control.node.focus();const options=[{id:'b',name:'B'}];control.update({options,value:'b'});options[0].name='Changed outside';control.node.blur();const name=control.node.firstChild.textContent;control.node.focus();control.update({options:[{id:'c',name:'C'}],value:'c'});control.dispose();control.node.blur();return {untouched,name,value:control.node.value,pending:control.pending,editing:control.editing};
  }),{untouched:true,name:'B',value:'b',pending:null,editing:false});
});
test('selection failure stays visible through a background push',async t=>{
  const {page}=await createCardFixture(t);
  await page.locator('[data-point-id] select').selectOption('j');await page.evaluate(()=>fixture.pending[0].reject({code:'home_assistant_error'}));await page.waitForFunction(()=>!!fixture.card.error);
  await page.evaluate(()=>fixture.card.onSnapshot({...fixture.snapshot,generation:2}));
  assert.equal(await page.evaluate(()=>fixture.card.error?.code),'home_assistant_error');
});
test('fresh stream confirmation wins over a late older confirmation read',async t=>{
  const {page}=await createCardFixture(t);
  await page.locator('[data-point-id] select').selectOption('j');await page.evaluate(()=>fixture.pending[0].resolve({}));await page.waitForFunction(()=>fixture.pending.length===2);
  await page.evaluate(()=>{fixture.card.onSnapshot({...fixture.snapshot,generation:3,points:[{...fixture.snapshot.points[0],selected_identity_id:'j'}]});fixture.pending[1].resolve(fixture.snapshot);});
  await page.waitForFunction(()=>fixture.card.pendingSelections.size===0);
  assert.equal(await page.evaluate(()=>fixture.card.error),null);
  assert.equal(await page.locator('[data-point-id] select').inputValue(),'j');
});
test('keyed history follows backend ordering when a new record arrives',async t=>{
  const {page}=await createCardFixture(t,{show_chart:false});
  assert.deepEqual(await page.evaluate(()=>{
    const c=fixture.card,record=id=>({id,point_id:'p',identity_id:'i',start:'2026-09-22T08:00:00Z',timezone:'UTC',status:'ended',energy_kwh:'1',known_cost:'1',cost_complete:true});c.page={records:[record('old')],total:1,limit:25};c.render();const old=c.shadowRoot.querySelector('li');c.page={records:[record('new'),record('old')],total:2,limit:25};c.render();return {order:[...c.shadowRoot.querySelectorAll('li')].map(n=>n.dataset.recordId),reused:old===c.shadowRoot.querySelectorAll('li')[1]};
  }),{order:['new','old'],reused:true});
});
for(const exit of ['Tab','save'])test(`reassign retains a new choice after a queued translation (${exit})`,async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>fixture.card.openDialog('reassign',{record:{id:'r',revision:1,point_id:'p',identity_id:'i',start:'2026-09-22T08:00:00Z',timezone:'UTC',energy_kwh:'1',known_cost:'1',cost_complete:true}}));
  await page.locator('dialog select').focus();
  await page.evaluate(()=>fixture.card.hass={...fixture.hass,language:'fr'});
  await page.locator('dialog select').selectOption('j');
  if(exit==='Tab'){
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('dialog select').inputValue(),'j');
  }
  await page.locator('dialog button[data-write]').click();
  assert.deepEqual(await page.evaluate(()=>({draft:fixture.card.dialog.targetIdentityId,value:fixture.card.dialog.node.querySelector('select').value,sent:fixture.pending[0].request.identity_id})),{draft:'j',value:'j',sent:'j'});
});
for(const [streamIdentity,readIdentity,wantError]of [['i','j','selectionUnconfirmed'],['j','i',null]])test(`newer stream ${streamIdentity} wins over older confirmation read ${readIdentity}`,async t=>{
  const {page}=await createCardFixture(t);
  await page.locator('[data-point-id] select').selectOption('j');
  await page.evaluate(()=>fixture.pending[0].resolve({}));await page.waitForFunction(()=>fixture.pending.length===2);
  await page.evaluate(({streamIdentity,readIdentity})=>{
    fixture.card.onSnapshot({...fixture.snapshot,generation:4,points:[{...fixture.snapshot.points[0],selected_identity_id:streamIdentity}]});
    fixture.pending[1].resolve({...fixture.snapshot,generation:3,points:[{...fixture.snapshot.points[0],selected_identity_id:readIdentity}]});
  },{streamIdentity,readIdentity});
  await page.waitForFunction(()=>fixture.card.pendingSelections.size===0);
  await page.locator('h2').click();
  assert.deepEqual(await page.evaluate(()=>({generation:fixture.card.snapshot.generation,selected:fixture.card.snapshot.points[0].selected_identity_id,error:fixture.card.error?.code??null,value:fixture.card.shadowRoot.querySelector('[data-point-id] select').value})),{generation:4,selected:streamIdentity,error:wantError,value:streamIdentity});
});
test('unversioned confirmation read loses ownership after a new stream snapshot',async t=>{
  const {page}=await createCardFixture(t);
  await page.locator('[data-point-id] select').selectOption('j');await page.evaluate(()=>fixture.pending[0].resolve({}));await page.waitForFunction(()=>fixture.pending.length===2);
  await page.evaluate(()=>{fixture.card.onSnapshot({...fixture.snapshot,generation:4});const {generation,...read}=fixture.snapshot;fixture.pending[1].resolve({...read,points:[{...read.points[0],selected_identity_id:'j'}]});});
  await page.waitForFunction(()=>fixture.card.pendingSelections.size===0);
  assert.deepEqual(await page.evaluate(()=>({selected:fixture.card.snapshot.points[0].selected_identity_id,error:fixture.card.error?.code})),{selected:'i',error:'selectionUnconfirmed'});
});
test('an owned confirmation read succeeds and a later stream remains authoritative',async t=>{
  const {page}=await createCardFixture(t);
  await page.locator('[data-point-id] select').selectOption('j');await page.evaluate(()=>fixture.pending[0].resolve({}));await page.waitForFunction(()=>fixture.pending.length===2);
  await page.evaluate(()=>{const {generation,...read}=fixture.snapshot;fixture.pending[1].resolve({...read,points:[{...read.points[0],selected_identity_id:'j'}]});});
  await page.waitForFunction(()=>fixture.card.pendingSelections.size===0);
  assert.equal(await page.evaluate(()=>fixture.card.snapshot.points[0].selected_identity_id),'j');
  await page.evaluate(()=>fixture.card.onSnapshot({...fixture.snapshot,generation:4}));
  assert.equal(await page.evaluate(()=>fixture.card.snapshot.points[0].selected_identity_id),'i');
});
test('service rejection overrides a local choice made after queued translation',async t=>{
  const {page}=await createCardFixture(t);
  await page.locator('[data-point-id] select').focus();await page.evaluate(()=>fixture.card.hass={...fixture.hass,language:'fr'});
  await page.locator('[data-point-id] select').selectOption('j');await page.evaluate(()=>fixture.pending[0].reject({code:'home_assistant_error'}));await page.waitForFunction(()=>!!fixture.card.error);
  await page.locator('h2').click();
  assert.deepEqual(await page.evaluate(()=>({value:fixture.card.shadowRoot.querySelector('[data-point-id] select').value,error:fixture.card.error.code})),{value:'i',error:'home_assistant_error'});
});

for(const viewport of [{width:900,height:700},{width:390,height:844}])test(`compact chart states and accessible labels at ${viewport.width}`,async t=>{
  const {page}=await createCardFixture(t);await page.setViewportSize(viewport);
  const {mkdir}=await import('node:fs/promises');await mkdir('.superpowers/card-qa',{recursive:true});
  for(const state of ['small','negative','unknown','zero','empty','awaiting','partial']){
    const result=await page.evaluate(state=>{
      const c=fixture.card;c.expanded={controls:false,statistics:true,records:false};
      const bucket=(label,energy,cost)=>({key:label,label,energy_kwh:energy,known_cost:cost,cost_complete:cost!==null,has_energy_data:energy!==null,has_known_cost:cost!==null});
      let buckets=[bucket('2026-10-25 02:00 +02:00','0.012','1')];if(state==='negative')buckets=[bucket('2026-10-25 02:00 +02:00','1','-2'),bucket('2026-10-25 02:00 +01:00','2','4')];if(state==='unknown')buckets=[bucket('2026-09-22 08:00 +00:00','1',null)];if(state==='partial')buckets=[bucket('08:00 +00:00','1',null),bucket('09:00 +00:00','1','2')];if(state==='zero')buckets=[bucket('08:00 +00:00','0','0')];if(state==='empty'||state==='awaiting')buckets=[];
      c.chartMetric=['negative','unknown','partial'].includes(state)?'known_cost':'energy_kwh';c.summary={energy_kwh:({small:'.012',negative:'3',unknown:'1',partial:'2',zero:'0',empty:'0',awaiting:'0'})[state],known_cost:({small:'1',negative:'2',partial:'2',unknown:'0',zero:'0',empty:'0',awaiting:'0'})[state],active_count:state==='awaiting'?1:0,completed_count:state==='empty'||state==='awaiting'?0:1,quality:state==='unknown'?['missing_price']:[],cost_complete:!['unknown','partial'].includes(state),matched_count:state==='empty'?0:1,has_energy_data:state!=='awaiting',has_known_cost:state!=='unknown',bucket_period:'hour',buckets};c.render();
      return {bars:c.shadowRoot.querySelectorAll('svg rect').length,plotHeight:c.view.chartView.plot.getBoundingClientRect().height,labels:[...c.shadowRoot.querySelectorAll('svg rect')].map(n=>n.getAttribute('aria-label')),bodyWidth:document.body.scrollWidth,viewport:innerWidth};
    },state);
    assert.equal(result.bars,{small:1,negative:2,unknown:0,zero:0,empty:0,awaiting:0,partial:1}[state]);if(['unknown','zero','empty','awaiting'].includes(state))assert.equal(result.plotHeight,0);assert.ok(result.bodyWidth<=result.viewport);if(state==='negative'){assert.match(result.labels[0],/\+02:00/);assert.match(result.labels[1],/\+01:00/);}await page.screenshot({path:`.superpowers/card-qa/task8-${viewport.width}-${state}.png`,fullPage:true});
  }
});

test('real record details explain missing data and manual estimates with snapshot count',async t=>{
  const {page}=await createCardFixture(t);
  for(const [kind,flags,basis]of [['normal',[],'tariff'],['price',['missing_price'],'unknown'],['sampling',['gap'],'tariff'],['manual',['estimated','manual'],'manual']]){
    await page.evaluate(({flags,basis})=>{const c=fixture.card;c.hass={...fixture.hass,language:'zh-Hans'};const record={id:'r',revision:90,point_id:'p',identity_id:'i',start:'2026-09-22T08:00:00Z',end:'2026-09-22T09:00:00Z',timezone:'UTC',status:'ended',source:'manual',energy_kwh:'1',known_cost:'1',cost_complete:basis!=='unknown',quality:flags};c.openDialog('details',{record,segments:[{start:record.start,end:record.end,energy_kwh:'1',cost:basis==='unknown'?null:'1',cost_basis:basis,quality:flags}],revisions:[{record}]});},{flags,basis});
    const text=await page.locator('dialog').innerText();assert.match(text,/修改记录 \(1\)/);if(kind==='manual'){assert.match(text,/部分数据为估算值/);assert.match(text,/按时间分配手动填写的总量/);}if(kind==='sampling')assert.match(text,/部分时段缺少电量数据/);if(kind==='price')assert.match(text,/缺少电价/);if(kind==='normal')assert.equal(await page.locator('dialog .quality').isVisible(),false);
    await page.evaluate(()=>fixture.card.dialog.close());
  }
});


test('chart translations keep metric and table state and narrow details stay bounded',async t=>{
  const {page}=await createCardFixture(t);await page.setViewportSize({width:390,height:844});
  assert.deepEqual(await page.evaluate(()=>{const c=fixture.card;c.expanded.statistics=true;c.summary={matched_count:1,active_count:0,completed_count:1,energy_kwh:'1',known_cost:'1',cost_complete:true,has_energy_data:true,has_known_cost:true,bucket_period:'hour',buckets:[{label:'2026-10-25 02:00 +02:00',energy_kwh:'1',known_cost:'1',cost_complete:true,has_energy_data:true,has_known_cost:true}]};c.render();const v=c.view.chartView;v.details.open=true;v.toggle.focus();c.hass={...fixture.hass,language:'zh-Hans'};return {title:c.view.sections.statistics.toggle.textContent,hint:v.hint.textContent,table:v.toggle.textContent,focus:c.shadowRoot.activeElement===v.toggle,open:v.details.open};}),{title:'记录统计',hint:'按小时统计；重复的当地时间用 UTC 偏移区分。',table:'图表数据',focus:true,open:true});
  await page.evaluate(()=>{const record={id:'r',revision:1,point_id:'p',identity_id:'i',start:'2026-09-22T08:00:00Z',end:'2026-09-22T09:00:00Z',timezone:'UTC',status:'ended',source:'automatic',energy_kwh:'1',known_cost:'1',cost_complete:true,quality:[]};fixture.card.openDialog('details',{record,segments:[{...record,cost:'1',cost_basis:'tariff'}],revisions:[]});});
  assert.equal(await page.evaluate(()=>{const d=fixture.card.dialog.node;const table=d.querySelector('.table-wrap');return d.getBoundingClientRect().width<=innerWidth&&d.scrollWidth<=d.clientWidth&&table.scrollWidth>table.clientWidth;}),true);
  await page.screenshot({path:'.superpowers/card-qa/task8-390-details.png',fullPage:true});
});

test('statistics excluded end date and precise record end time have distinct labels',async t=>{
  const {page}=await createCardFixture(t);
  for(const [language,dateLabel,timeLabel]of [['zh-Hans','结束日期（当天不计入）','结束时间'],['en','End date (excluded)','End time'],['de','Enddatum (nicht enthalten)','Endzeit'],['fr','Date de fin (exclue)','Heure de fin'],['pl','Data końcowa (bez tego dnia)','Czas zakończenia'],['it','Data finale (esclusa)','Ora di fine']]){
    const labels=await page.evaluate(language=>{const c=fixture.card;c.hass={...fixture.hass,language};c.period='custom';c.expanded.statistics=true;c.render();c.openDialog('create');return {date:c.view.toLabel.firstChild.textContent,time:c.dialog.node.querySelectorAll('input[type="datetime-local"]')[1].closest('label').firstChild.textContent};},language);
    assert.deepEqual(labels,{date:dateLabel,time:timeLabel});await page.evaluate(()=>fixture.card.dialog.close());
  }
});


test('ArrowDown and Escape match the native select baseline during pushes',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{
    const native=document.createElement('select');native.id='native-baseline';
    native.innerHTML='<option value="i">Family</option><option value="j">Guest</option>';
    document.body.append(native);
  });
  const native=page.locator('#native-baseline');await native.click();
  await page.keyboard.press('ArrowDown');await page.keyboard.press('Escape');
  const nativeValue=await native.inputValue();
  const select=page.locator('[data-point-id] select');await select.click();
  await page.keyboard.press('ArrowDown');
  for(let generation=2;generation<=4;generation++)await page.evaluate(generation=>fixture.card.onSnapshot({...fixture.snapshot,generation}),generation);
  assert.equal(await page.evaluate(()=>fixture.card.shadowRoot.activeElement===fixture.card.shadowRoot.querySelector('[data-point-id] select')),true);
  await page.keyboard.press('Escape');
  assert.equal(await select.inputValue(),nativeValue);
  assert.equal(await page.evaluate(()=>fixture.pending.length),nativeValue==='j'?1:0);
});
