import test from 'node:test';
import assert from 'node:assert/strict';
import {createCardFixture} from './card-fixture.mjs';

const states=[
  ['idle','disabled','recordingIdle','detectionDisabled','startManual'],
  ['idle','waiting','recordingIdle','detectionWaiting','startManual'],
  ['idle','pending_start','recordingIdle','pending_start','startNow'],
  ['automatic','charging','recordingAutomatic','detectionCharging','endAutomatic'],
  ['automatic','pending_end','recordingAutomatic','pending_end','endNow'],
  ['manual','paused_manual','recordingManual','detectionPausedManual','end'],
  ['idle','blocked','recordingIdle','detectionBlocked','startManual'],
  ['idle','unavailable','recordingIdle','detectionUnavailable','startManual'],
];
test('authoritative accounting and detection states remain separate from instantaneous power in all languages',async t=>{
  const {page}=await createCardFixture(t);
  for(const language of ['en','zh-Hans','de','fr','pl','it'])for(const [recording,detection,statusKey,detectionKey,actionKey]of states){
    const result=await page.evaluate(({language,recording,detection,statusKey,detectionKey,actionKey})=>{
      const c=fixture.card;c.hass={...fixture.hass,language};
      const active=recording==='idle'?null:{id:'r',revision:3,identity_id:'i',source:recording,start:'2026-09-29T00:00:00Z',timezone:'UTC',energy_kwh:'1',known_cost:'1',cost_complete:true};
      c.onSnapshot({...fixture.snapshot,generation:++fixture.snapshot.generation,points:[{...fixture.snapshot.points[0],status:'charging',recording_state:recording,detection_state:detection,power_w:recording==='manual'?'0':'900',active_record:active,candidate_identity_id:detection==='pending_start'?'j':null}]});
      const v=c.view.points.get('p');return {status:v.status.textContent,expectedStatus:c.t(statusKey),detection:v.detection?.textContent,expectedDetection:`${c.t('detector')}: ${c.t(detectionKey)}`,action:v.live.textContent,expectedAction:c.t(actionKey),manualHint:v.hint?.textContent,hintHidden:v.hint?.hidden,expectedManualHint:c.t('manualEndRequired')};
    },{language,recording,detection,statusKey,detectionKey,actionKey});
    assert.equal(result.status,result.expectedStatus,`${language}: ${recording}/${detection}`);
    assert.equal(result.detection,result.expectedDetection);
    assert.equal(result.action,result.expectedAction);
    if(recording==='manual'){assert.equal(result.hintHidden,false);assert.equal(result.manualHint,result.expectedManualHint);}
    if(language==='zh-Hans'&&['paused_manual','pending_start','blocked'].includes(detection))await page.screenshot({path:`.superpowers/card-qa/manual-auto-${detection}.png`});
  }
});

test('pending automatic identity stays locked while immediate manual start uses selected identity',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{
    const c=fixture.card;c.onSnapshot({...fixture.snapshot,generation:2,points:[{...fixture.snapshot.points[0],recording_state:'idle',detection_state:'pending_start',candidate_identity_id:'i',selected_identity_id:'j'}]});
    c.view.points.get('p').select.node.focus();window.originalSelect=c.shadowRoot.activeElement;
  });
  const result=await page.evaluate(()=>{
    const c=fixture.card,v=c.view.points.get('p');return {candidate:v.candidate?.textContent,hint:v.hint?.textContent,expectedHint:c.t('candidateHint'),label:v.select.label.firstChild.textContent,expectedLabel:c.t('nextManualIdentity')};
  });
  assert.match(result.candidate,/Family/);assert.equal(result.hint,result.expectedHint);assert.equal(result.label,result.expectedLabel);
  await page.evaluate(()=>{const c=fixture.card;c.onSnapshot({...c.snapshot,generation:3,points:[{...c.snapshot.points[0],power_w:'5000'}]});});
  assert.equal(await page.evaluate(()=>fixture.card.shadowRoot.activeElement===originalSelect),true);
  await page.locator('[data-point-id] button.primary').click();
  assert.deepEqual(await page.evaluate(()=>({service:fixture.pending[0].request.service,identity:fixture.pending[0].request.service_data.identity_id})),{service:'start',identity:'j'});
});

test('accounting actions retain unavailable meter, busy and connection guards',async t=>{
  const {page}=await createCardFixture(t);
  const apply=async(recording,available,busy=false,connected=true)=>page.evaluate(({recording,available,busy,connected})=>{
    const c=fixture.card;fixture.hass.connection.connected=connected;c.busy=busy;
    c.onSnapshot({...fixture.snapshot,generation:++fixture.snapshot.generation,points:[{...fixture.snapshot.points[0],recording_state:recording,detection_state:'unavailable',available,active_record:recording==='idle'?null:{id:'r',revision:7,identity_id:'i',source:recording,start:'2026-09-29T00:00:00Z',timezone:'UTC'}}]});
    return c.view.points.get('p').live.disabled;
  },{recording,available,busy,connected});
  assert.equal(await apply('idle',false),true);
  assert.equal(await apply('manual',false),false);
  assert.equal(await apply('automatic',false),false);
  assert.equal(await apply('manual',true,true),true);
  assert.equal(await apply('manual',true,false,false),true);
  await apply('manual',false);
  await page.locator('[data-point-id] button.primary').click();
  assert.deepEqual(await page.evaluate(()=>{const r=fixture.pending[0].request;return {service:r.service,id:r.service_data.record_id,revision:r.service_data.expected_revision,request:!!r.service_data.request_id};}),{service:'end',id:'r',revision:7,request:true});
});
test('manual start waits for a pending identity selection without blocking active end',async t=>{
  const {page}=await createCardFixture(t);
  await page.locator('[data-point-id] select').selectOption('j');
  assert.equal(await page.locator('[data-point-id] button.primary').isDisabled(),true);
  await page.evaluate(()=>fixture.card.live('start',fixture.card.snapshot.points[0]));
  assert.equal(await page.evaluate(()=>fixture.pending.length),1);
  await page.evaluate(()=>fixture.pending.shift().resolve({}));
  await page.waitForFunction(()=>fixture.pending.some(p=>p.request.type==='charge_tally/snapshot'));
  await page.evaluate(()=>fixture.pending.shift().resolve({...fixture.snapshot,generation:2,points:[{...fixture.snapshot.points[0],selected_identity_id:'j'}]}));
  await page.waitForFunction(()=>fixture.card.pendingSelections.size===0);
  assert.equal(await page.locator('[data-point-id] button.primary').isDisabled(),false);
  await page.locator('[data-point-id] button.primary').click();
  assert.equal(await page.evaluate(()=>fixture.pending[0].request.service_data.identity_id),'j');
  await page.evaluate(()=>{
    const c=fixture.card;c.busy=false;c.pendingSelections.set('p',{identityId:'i'});
    c.onSnapshot({...c.snapshot,generation:3,points:[{...c.snapshot.points[0],recording_state:'manual',detection_state:'paused_manual',active_record:{id:'r',revision:1,identity_id:'j',source:'manual',start:'2026-09-29T00:00:00Z',timezone:'UTC'}}]});
  });
  assert.equal(await page.locator('[data-point-id] button.primary').isDisabled(),false);
});
