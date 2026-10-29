import test from 'node:test';
import assert from 'node:assert/strict';
import {createCardFixture} from './card-fixture.mjs';

test('slow records finish under continuous snapshots with one queued refresh',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{
    fixture.card.setExpanded('records',true);
    for(let generation=2;generation<=20;generation++)fixture.card.onSnapshot({...fixture.snapshot,generation});
  });
  assert.deepEqual(await page.evaluate(()=>fixture.pending.map(p=>p.request.type)),['charge_tally/records']);
  await page.evaluate(()=>fixture.pending[0].resolve({records:[],total:0,limit:25,offset:0}));
  await page.waitForFunction(()=>!!fixture.card.page);
  assert.equal(await page.evaluate(()=>fixture.card.view.loading.hidden),true);
  assert.equal(await page.evaluate(()=>fixture.pending.length),2);
  await page.evaluate(()=>{
    fixture.card.setExpanded('records',false);
    fixture.card.onSnapshot({...fixture.snapshot,generation:21});
    fixture.pending[1].resolve({records:[],total:0,limit:25,offset:0});
  });
  await page.waitForFunction(()=>!fixture.card.recordsPending);
  assert.equal(await page.evaluate(()=>fixture.pending.length),2);
});

test('slow summary completes before the next dirty refresh',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{
    fixture.card.setExpanded('statistics',true);
    fixture.card.onSnapshot({...fixture.snapshot,generation:2});
    fixture.card.onSnapshot({...fixture.snapshot,generation:3});
  });
  assert.equal(await page.evaluate(()=>fixture.pending.length),1);
  await page.evaluate(()=>fixture.pending[0].resolve({energy_kwh:'1',known_cost:'2',cost_complete:true,buckets:[]}));
  await page.waitForFunction(()=>fixture.card.summary?.energy_kwh==='1');
  assert.equal(await page.evaluate(()=>fixture.pending.length),2);
});

test('collapsed data and unchanged chart keep their rendered nodes',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{
    fixture.card.setExpanded('statistics',true);fixture.card.setExpanded('records',true);
    fixture.summary={energy_kwh:'1',known_cost:'2',cost_complete:true,matched_count:1,has_energy_data:true,has_known_cost:true,bucket_period:'hour',buckets:[{key:'h',label:'10:00',energy_kwh:'1',known_cost:'2',has_energy_data:true,has_known_cost:true}]};
    fixture.records={records:[{id:'r',point_id:'p',identity_id:'i',start:'2026-09-19T00:00:00Z',timezone:'UTC',status:'ended',energy_kwh:'1',known_cost:'2',cost_complete:true,quality:[]}],limit:25,total:1};
    fixture.pending[0].resolve(fixture.summary);fixture.pending[1].resolve(fixture.records);
  });
  await page.waitForFunction(()=>!!fixture.card.page&&!!fixture.card.summary);
  assert.deepEqual(await page.evaluate(()=>{
    const c=fixture.card,svg=c.view.chart.querySelector('svg'),row=c.view.list.querySelector('strong');
    c.setExpanded('statistics',false);c.setExpanded('records',false);
    c.onSnapshot({...fixture.snapshot,generation:2});
    const hiddenStable=svg===c.view.chart.querySelector('svg')&&row===c.view.list.querySelector('strong');
    c.setExpanded('statistics',true);c.render();
    return {hiddenStable,chartStable:svg===c.view.chart.querySelector('svg')};
  }),{hiddenStable:true,chartStable:true});
});
