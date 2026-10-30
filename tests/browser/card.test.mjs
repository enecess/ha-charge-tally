import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createCardFixture,openCompactDetails} from './card-fixture.mjs';

for(const timezoneId of ['UTC','Europe/Berlin'])test(`personal record timezone keeps shared calendar queries in ${timezoneId}`,async t=>{
  const {page}=await createCardFixture(t,{}, {timezoneId});
  await page.evaluate(()=>{
    const c=fixture.card;c.hass={...fixture.hass,locale:undefined,config:{time_zone:'Asia/Shanghai'}};
    c.onSnapshot({...fixture.snapshot,timezone:'Asia/Shanghai'});
    c.expanded={controls:true,statistics:true,records:true};
    fixture.record={id:'tz',revision:2,point_id:'p',identity_id:'i',timezone:'America/New_York',start:'2026-10-29T08:57:00.123456Z',end:'2026-10-29T09:57:00.987654Z',status:'ended',source:'automatic',energy_kwh:'2',known_cost:'1',cost_complete:true,note:'Keep my note',quality:[]};
    c.snapshot.points[0].active_record={...fixture.record,status:'active',end:null};
    c.page={records:[fixture.record],total:1,limit:25};c.recordsDirty=false;c.summary={energy_kwh:'2',known_cost:'1',cost_complete:true,buckets:[]};c.summaryDirty=false;c.render();
  });
  assert.match(await page.locator('[data-record-id=tz]').innerText(),/2026-10-29 16:57:00/);
  assert.match(await page.locator('[data-point-id]').innerText(),/Started: 2026-10-29 16:57:00/);
  assert.equal(await page.locator('[data-timezone=display]:visible').count(),0);
  await page.evaluate(()=>{const c=fixture.card;c.summaryDirty=true;c.refresh();c.period='custom';c.rangeStart='2026-10-29';c.rangeEnd='2026-10-30';c.applyRange();});
  const accountingRequests=await page.evaluate(()=>fixture.pending.map(p=>p.request));
  assert.deepEqual(accountingRequests,[{type:'charge_tally/query',calendar_period:'daily'},{type:'charge_tally/query',start:'2026-10-28T16:00:00.000Z',end:'2026-10-29T16:00:00.000Z'}]);
  await page.evaluate(()=>{const c=fixture.card;c.hass={...fixture.hass,locale:{time_zone:'local'}};});
  assert.match(await page.locator('[data-record-id=tz]').innerText(),timezoneId==='UTC'?/2026-10-29 08:57:00/:/2026-10-29 09:57:00/);
  assert.match(await page.locator('[data-point-id]').innerText(),timezoneId==='UTC'?/Started: 2026-10-29 08:57:00/:/Started: 2026-10-29 09:57:00/);
  assert.match(await page.locator('[data-timezone=display]').innerText(),new RegExp(`Display timezone: ${timezoneId}`));
  assert.match(await page.locator('[data-timezone=statistics]').innerText(),/Statistics timezone: Asia\/Shanghai/);
  assert.deepEqual(await page.evaluate(()=>fixture.pending.map(p=>p.request)),accountingRequests);
  assert.equal(await page.evaluate(()=>fixture.card.snapshot.timezone),'Asia/Shanghai');
  await page.evaluate(()=>{fixture.pending[0].resolve({energy_kwh:'old',buckets:[]});fixture.pending[1].resolve({energy_kwh:'2',known_cost:'1',cost_complete:true,buckets:[]});});
  await page.waitForFunction(()=>fixture.card.summary?.energy_kwh==='2');
  assert.match(await page.locator('[data-section=statistics] .metric').first().innerText(),/2 kWh/);
  await page.evaluate(()=>{fixture.card.details(fixture.record);});
  assert.equal(await page.evaluate(()=>fixture.pending.at(-1).request.display_timezone),timezoneId);
  await page.evaluate(()=>fixture.pending.at(-1).resolve({record:fixture.record,display_timezone:fixture.card.displayTimezone,display_segments:[],billing_periods:[],revisions:[]}));
  await page.waitForSelector('dialog');
  assert.match(await page.locator('dialog').innerText(),/Keep my note/);
  assert.match(await page.locator('dialog [data-timezone=display]').innerText(),new RegExp(timezoneId));
  await page.getByRole('button',{name:'Edit record',exact:true}).click();
  assert.equal(await page.locator('dialog input[type=datetime-local]').first().inputValue(),timezoneId==='UTC'?'2026-10-29T08:57':'2026-10-29T09:57');
  await page.getByRole('button',{name:'Preview changes',exact:true}).click();
  const request=await page.evaluate(()=>fixture.pending.at(-1).request);
  assert.equal(request.display_timezone,timezoneId);assert.equal('start'in request,false);assert.equal('end'in request,false);
  await page.evaluate(()=>fixture.pending.at(-1).resolve({record:fixture.record,token:'personal-preview',display_timezone:fixture.card.displayTimezone,billing_periods:[],display_segments:[],coverage:[{start:fixture.record.start,end:fixture.record.end}],overlaps:[]}));
  await page.waitForFunction(()=>!!fixture.card.dialog.preview);
  assert.match(await page.locator('dialog .preview').innerText(),timezoneId==='UTC'?/2026-10-29 08:57:00 → 2026-10-29 09:57:00/:/2026-10-29 09:57:00 → 2026-10-29 10:57:00/);
});

test('personal timezone leaves PDF request language and system date scope intact',async t=>{
  const {page}=await createCardFixture(t,{}, {timezoneId:'UTC'});
  await page.evaluate(()=>{
    const c=fixture.card;c.onSnapshot({...fixture.snapshot,timezone:'Asia/Shanghai'});c.hass={...fixture.hass,locale:{time_zone:'local'},language:'de-DE'};
    c.period='custom';c.rangeStart='2026-10-29';c.rangeEnd='2026-10-30';c.applyRange();c.exportPdf();
  });
  assert.deepEqual(await page.evaluate(()=>fixture.exports[0].payload),{language:'de-DE',start:'2026-10-28T16:00:00.000Z',end:'2026-10-29T16:00:00.000Z'});
  await page.evaluate(()=>fixture.card.cancelExport());
});

for(const change of ['personal','system'])test(`${change} timezone change retains editable draft and rejects a pending preview`,async t=>{
  const {page}=await createCardFixture(t,{}, {timezoneId:'UTC'});
  await page.evaluate(()=>{const c=fixture.card;c.onSnapshot({...fixture.snapshot,timezone:'Asia/Shanghai'});c.openDialog('create');});
  await page.locator('dialog input[type=datetime-local]').first().fill('2026-10-29T16:57:01');
  await page.locator('dialog input[type=datetime-local]').nth(1).fill('2026-10-29T17:57:01');
  await page.locator('dialog textarea').fill('Copyable draft');
  await page.getByRole('button',{name:'Preview changes',exact:true}).click();
  await page.evaluate(change=>{const c=fixture.card;fixture.draft=c.dialog.node.querySelector('textarea');if(change==='personal')c.hass={...fixture.hass,locale:{time_zone:'local'}};else c.onSnapshot({...c.snapshot,timezone:'Europe/Berlin'});},change);
  assert.equal(await page.locator('dialog textarea').inputValue(),'Copyable draft');
  assert.equal(await page.evaluate(()=>fixture.draft===fixture.card.dialog.node.querySelector('textarea')),true);
  assert.equal(await page.locator('dialog textarea').isDisabled(),false);
  assert.match(await page.locator('dialog [data-timezone=display]').innerText(),/Asia\/Shanghai/);
  assert.match(await page.locator('dialog [role=alert]').innerText(),/Timezone changed.*reopen/i);
  assert.equal(await page.getByRole('button',{name:'Preview changes',exact:true}).isDisabled(),true);
  assert.equal(await page.locator('dialog button[data-write]').last().isDisabled(),true);
  await page.evaluate(()=>fixture.pending[0].resolve({token:'stale'}));
  await page.waitForTimeout(30);
  assert.equal(await page.evaluate(()=>fixture.card.dialog.preview),null);
});

test('detail timezone changes replace pending projections and keep fee expansion',async t=>{
  const {page}=await createCardFixture(t,{}, {timezoneId:'UTC'});
  await page.evaluate(()=>{const c=fixture.card;c.onSnapshot({...fixture.snapshot,timezone:'Asia/Shanghai'});c.details({id:'r'});c.hass={...fixture.hass,locale:{time_zone:'local'}};});
  assert.deepEqual(await page.evaluate(()=>fixture.pending.map(p=>p.request.display_timezone)),['Asia/Shanghai','UTC']);
  await page.evaluate(()=>fixture.pending[0].resolve({record:{id:'old'}}));
  await page.waitForTimeout(20);assert.equal(await page.locator('dialog').count(),0);
  await page.evaluate(()=>{const record={id:'r',revision:1,point_id:'p',identity_id:'i',timezone:'Asia/Shanghai',start:'2026-10-29T08:57:00Z',end:'2026-10-29T09:57:00Z',status:'ended',source:'automatic',energy_kwh:'2',known_cost:'1',cost_complete:true,quality:[]};fixture.detail={record,display_timezone:'UTC',display_segments:[],billing_periods:[],revisions:[]};fixture.pending[1].resolve(fixture.detail);});
  await page.waitForSelector('dialog');await page.locator('dialog details summary').click();
  await page.evaluate(()=>fixture.card.hass={...fixture.hass,locale:{time_zone:'server'}});
  assert.equal(await page.evaluate(()=>fixture.pending.at(-1).request.display_timezone),'Asia/Shanghai');
  await page.evaluate(()=>fixture.pending.at(-1).resolve({...fixture.detail,display_timezone:'Asia/Shanghai'}));
  await page.waitForFunction(()=>fixture.card.dialog.detail.display_timezone==='Asia/Shanghai');
  assert.equal(await page.locator('dialog details').evaluate(node=>node.open),true);
  assert.match(await page.locator('dialog .record-overview').innerText(),/16:57–17:57/);
});

test('system timezone replaces a pending summary using applied calendar dates',async t=>{
  const {page}=await createCardFixture(t,{}, {timezoneId:'UTC'});
  await page.evaluate(()=>{
    const c=fixture.card;c.onSnapshot({...fixture.snapshot,timezone:'Asia/Shanghai'});c.period='custom';c.rangeStart='2026-10-29';c.rangeEnd='2026-10-30';c.applyRange();c.setExpanded('statistics',true);
    c.rangeStart='2026-11-05';c.rangeEnd='2026-11-09';c.onSnapshot({...c.snapshot,timezone:'America/New_York'});
  });
  assert.deepEqual(await page.evaluate(()=>fixture.pending.map(p=>p.request)),[
    {type:'charge_tally/query',start:'2026-10-28T16:00:00.000Z',end:'2026-10-29T16:00:00.000Z'},
    {type:'charge_tally/query',start:'2026-10-29T04:00:00.000Z',end:'2026-10-30T04:00:00.000Z'},
  ]);
  await page.evaluate(()=>{fixture.pending[1].resolve({energy_kwh:'2',known_cost:'1',cost_complete:true,buckets:[]});fixture.pending[0].resolve({energy_kwh:'old',buckets:[]});});
  await page.waitForFunction(()=>fixture.card.summary?.energy_kwh==='2');
  assert.equal(await page.evaluate(()=>fixture.card.rangeStart),'2026-11-05');
});

test('editing retains its draft when another timezone change supersedes a detail refresh',async t=>{
  const {page}=await createCardFixture(t,{}, {timezoneId:'UTC'});
  await openCompactDetails(page);
  await page.evaluate(()=>fixture.card.onSnapshot({...fixture.card.snapshot,timezone:'Asia/Shanghai'}));
  await page.getByRole('button',{name:'Edit record',exact:true}).click();await page.locator('dialog textarea').fill('Keep after two changes');
  await page.evaluate(()=>{const c=fixture.card;c.hass={...fixture.hass,locale:{time_zone:'local'}};fixture.pending.forEach(p=>p.resolve(fixture.compact));});
  await page.waitForTimeout(30);
  assert.equal(await page.locator('dialog textarea').inputValue(),'Keep after two changes');
  assert.equal(await page.getByRole('button',{name:'Preview changes',exact:true}).isDisabled(),true);
});

test('timezone changes do not cancel an already submitted historical write',async t=>{
  const {page}=await createCardFixture(t,{}, {timezoneId:'UTC'});await openCompactDetails(page);
  await page.getByRole('button',{name:'Edit record',exact:true}).click();await page.getByRole('button',{name:'Preview changes',exact:true}).click();
  await page.evaluate(()=>fixture.pending[0].resolve({...fixture.compact,token:'token',expected_revision:1797,overlaps:[],coverage:[]}));
  await page.waitForFunction(()=>!!fixture.card.dialog.preview);
  await page.locator('dialog button[data-write]').last().click();
  await page.evaluate(()=>{fixture.card.onSnapshot({...fixture.card.snapshot,timezone:'Asia/Shanghai'});fixture.pending[1].resolve(fixture.compact.record);});
  await page.waitForFunction(()=>!fixture.card.dialog);
  assert.equal(await page.evaluate(()=>fixture.pending[1].request.type),'charge_tally/commit');
  assert.equal(await page.evaluate(()=>fixture.card.notice),'Saved');
});

test('timezone labels follow six languages without replacing a focused draft',async t=>{
  const {page}=await createCardFixture(t,{}, {timezoneId:'UTC'});
  await page.evaluate(()=>{const c=fixture.card;c.hass={...fixture.hass,language:'invalid_locale_!'};c.onSnapshot({...fixture.snapshot,timezone:'Asia/Shanghai'});c.hass={...c._hass,locale:{time_zone:'local'}};c.expanded={controls:false,statistics:true,records:true};c.render();c.openDialog('create');});
  await page.locator('dialog textarea').fill('My draft');await page.locator('dialog textarea').focus();
  assert.match(await page.locator('dialog [data-timezone=display]').innerText(),/Input timezone: UTC/);
  for(const [language,display,statistics,input]of [['en','Display timezone','Statistics timezone','Input timezone'],['zh-Hans','显示时区','统计时区','输入时区'],['de','Anzeigezeitzone','Statistikzeitzone','Eingabezeitzone'],['fr','Fuseau horaire d’affichage','Fuseau horaire des statistiques','Fuseau horaire de saisie'],['it','Fuso orario di visualizzazione','Fuso orario delle statistiche','Fuso orario di inserimento'],['pl','Strefa czasowa wyświetlania','Strefa czasowa statystyk','Strefa czasowa wprowadzania']]){
    await page.evaluate(language=>fixture.card.hass={...fixture.card._hass,language},language);
    assert.equal(await page.locator('[data-section=records] [data-timezone=display]').innerText(),`${display}: UTC`);
    assert.equal(await page.locator('[data-timezone=statistics]').innerText(),`${statistics}: Asia/Shanghai`);
    assert.equal(await page.locator('dialog [data-timezone=display]').innerText(),`${input}: UTC`);
    assert.equal(await page.locator('dialog textarea').inputValue(),'My draft');assert.equal(await page.locator('dialog textarea').evaluate(node=>node.getRootNode().activeElement===node),true);
  }
});

for(const width of [900,320])test(`backend personal projections keep midnight fees and manual coverage bounded at ${width}px`,async t=>{
  const projections=JSON.parse(execFileSync(process.env.PYTHON||'python3',['-c',`
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from custom_components.charge_tally.ledger import Ledger
from custom_components.charge_tally.accounting import Accounting
from custom_components.charge_tally.record_views import detail_view
ledger = Ledger(':memory:')
ledger.put_point({'id': 'p'})
ledger.put_identity({'id': 'i', 'name': 'Family'})
app = Accounting(ledger)
start = datetime(2026, 10, 29, 23, 59, tzinfo=UTC)
record = app.start('p', 'i', start, 'start', source='automatic', timezone='Asia/Shanghai')
app.add_interval('p', start, start + timedelta(minutes=2), Decimal('2'), [(start, Decimal('0.5'))])
app.add_interval('p', start + timedelta(minutes=2), start + timedelta(minutes=2, seconds=5), Decimal('0'), [(start, Decimal('0.5'))], ('reset',))
record = app.end(record['id'], start + timedelta(minutes=2, seconds=10), 'end')
parts = ledger.list_segments(record['id'])
normal = detail_view(record, parts, [], include_history=False, display_timezone=ZoneInfo('UTC'))
fee_preview = app.preview({'record_id': record['id'], 'expected_revision': record['revision'], 'cost': '12.00'})
manual_fee = detail_view(fee_preview['record'], fee_preview['segments'], [], include_history=False, display_timezone=ZoneInfo('UTC'))
preview = app.preview({'point_id': 'p', 'identity_id': 'i', 'start': start - timedelta(days=1), 'end': start - timedelta(days=1) + timedelta(hours=2), 'timezone': 'Asia/Shanghai', 'energy_kwh': '6', 'prices': [(start - timedelta(days=1), '0.25')]})
manual_energy = detail_view(preview['record'], preview['segments'], [], include_history=False, display_timezone=ZoneInfo('UTC'))
print(json.dumps({'normal': normal, 'manual_fee': manual_fee, 'manual_energy': manual_energy}))
ledger.close()
`],{encoding:'utf8'}));
  const {page}=await createCardFixture(t,{}, {timezoneId:'UTC'});await page.setViewportSize({width,height:900});
  await page.evaluate(detail=>{const c=fixture.card;c.onSnapshot({...fixture.snapshot,timezone:'Asia/Shanghai'});c.hass={...fixture.hass,locale:{time_zone:'local'}};c.openDialog('details',detail);},projections.normal);
  await page.locator('dialog details summary').click();
  assert.match(await page.locator('dialog .billing-details').innerText(),/23:59:00–2026-10-30 00:00:00/);
  assert.equal(await page.locator('dialog .billing-period').count(),2);assert.equal(await page.locator('dialog .billing-gap').count(),1);
  assert.match(await page.locator('dialog .billing-gap').innerText(),/00:01:00–00:01:10.*10 s/);
  assert.match(await page.locator('dialog .record-overview').innerText(),/A meter reset caused missing energy data/);
  assert.equal(await page.evaluate(()=>{const d=fixture.card.dialog.node;return d.scrollWidth<=d.clientWidth&&d.getBoundingClientRect().width<=innerWidth;}),true);
  const {mkdir}=await import('node:fs/promises');await mkdir('.superpowers/timezone-qa',{recursive:true});
  await page.screenshot({path:`.superpowers/timezone-qa/task-3-${width}-details.png`,fullPage:true});
  if(width===320){await page.locator('dialog').evaluate(node=>{node.scrollTop=node.scrollHeight;});await page.screenshot({path:'.superpowers/timezone-qa/task-3-320-details-bottom.png',fullPage:true});}
  await page.evaluate(detail=>fixture.card.openDialog('details',detail),projections.manual_fee);await page.locator('dialog details summary').click();
  assert.equal(await page.locator('dialog .measurement-period').count(),2);assert.equal(await page.locator('dialog .billing-gap').count(),1);
  assert.doesNotMatch(await page.locator('dialog .billing-details').innerText(),/CNY\/kWh|CNY 12/);
  await page.evaluate(detail=>fixture.card.openDialog('details',detail),projections.manual_energy);await page.locator('dialog details summary').click();
  assert.match(await page.locator('dialog .record-metrics').innerText(),/Manual energy\s+6/);
  assert.equal(await page.locator('dialog .billing-period').count(),2);assert.match(await page.locator('dialog .billing-details').innerText(),/0.25/);
  assert.deepEqual(projections.normal.record.timezone,'Asia/Shanghai');
});

test('backend mixed reset and pending span keeps its real loss in details and record rows',async t=>{
  const detail=JSON.parse(execFileSync(process.env.PYTHON||'python3',['-c',`
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from custom_components.charge_tally.ledger import Ledger
from custom_components.charge_tally.accounting import Accounting
from custom_components.charge_tally.record_views import detail_view
ledger = Ledger(':memory:')
ledger.put_point({'id': 'p'})
ledger.put_identity({'id': 'i', 'name': 'Family'})
start = datetime(2026, 1, 1, tzinfo=UTC)
app = Accounting(ledger)
record = app.start('p', 'i', start, 'start')
app.add_interval('p', start, start + timedelta(seconds=30), Decimal('1'), [(start, Decimal('0.5'))])
app.add_interval('p', start + timedelta(seconds=30), start + timedelta(seconds=40), Decimal('0'), [(start, Decimal('0.5'))], ('reset',))
record = app.end(record['id'], start + timedelta(seconds=50), 'end')
print(json.dumps(detail_view(record, ledger.list_segments(record['id']), [], include_history=False)))
ledger.close()
`],{encoding:'utf8'}));
  assert.deepEqual(detail.record.quality_spans.map(span=>span.quality),[['missing_energy','pending_settlement','reset']]);
  const {page}=await createCardFixture(t);
  await page.evaluate(detail=>{const c=fixture.card;c.expanded.records=true;c.page={records:[detail.record],total:1,limit:25};c.render();c.openDialog('details',detail);},detail);
  assert.match(await page.locator('[data-record-id]').innerText(),/A meter reset caused missing energy data/);
  assert.match(await page.locator('dialog .record-overview').innerText(),/A meter reset caused missing energy data/);
  await page.locator('dialog details summary').click();
  assert.equal(await page.locator('dialog .billing-gap').count(),1);
  assert.match(await page.locator('dialog .billing-gap').innerText(),/20 s/);
});

test('normal settlement and recovered records stay quiet while current point failures remain visible',async t=>{
  const {page}=await createCardFixture(t);
  for(const [overrides,label,value]of [
    [{quality:['missing_energy','pending_settlement'],quality_spans:[{start:'2026-10-29T19:29:10Z',end:'2026-10-29T19:29:15Z',quality:['missing_energy','pending_settlement']}],has_known_cost:false,known_cost:'0'},'Settling','—'],
    [{status:'active',end:null,quality:['provisional'],quality_spans:[],has_known_cost:false,known_cost:'0'},'Current cost','—'],
    [{quality:['unavailable','estimated','manual'],quality_spans:[],cost_complete:true},'Cost','EUR 5.29'],
  ]){
    await openCompactDetails(page,overrides);
    assert.equal(await page.locator('dialog .record-issue').count(),0);
    assert.match(await page.locator('dialog .record-metrics').innerText(),new RegExp(label));
    assert.match(await page.locator('dialog .record-metrics').innerText(),new RegExp(value));
    await page.locator('dialog details summary').click();
    assert.equal(await page.locator('dialog .billing-gap').count(),0);
    await page.evaluate(()=>{const c=fixture.card;c.dialog.close();c.expanded.records=true;c.expanded.statistics=true;c.page={records:[fixture.compact.record],total:1,limit:25};c.summary={energy_kwh:'17.675',known_cost:'5.29',has_known_cost:true,quality:['missing_energy','pending_settlement','reset','estimated','unavailable'],cost_complete:false,matched_count:1,has_energy_data:true,bucket_period:'hour',buckets:[]};c.render();});
    assert.doesNotMatch(await page.locator('[data-record-id]').innerText(),/Some data|Unavailable|Pending settlement|Cost to be added|missing energy/);
    assert.equal(await page.locator('[data-section=statistics] .quality').count(),0);
    assert.match(await page.locator('[data-section=statistics] .metric').nth(1).innerText(),/Calculated cost/);
  }
  await page.evaluate(()=>fixture.card.onSnapshot({...fixture.snapshot,generation:2,points:[{...fixture.snapshot.points[0],available:false,detection_state:'unavailable',quality:['unavailable'],error:'Energy sensor unavailable'}]}));
  assert.match(await page.locator('[data-point-id]').innerText(),/Waiting for valid energy and power data.*Energy sensor unavailable.*Unavailable/s);
});

test('backend manual energy shows tariff periods in shared details and preview',async t=>{
  const detail=JSON.parse(execFileSync(process.env.PYTHON||'python3',['-c',`
import json
from datetime import UTC, datetime, timedelta
from custom_components.charge_tally.ledger import Ledger
from custom_components.charge_tally.accounting import Accounting
from custom_components.charge_tally.record_views import detail_view
ledger = Ledger(':memory:')
ledger.put_point({'id': 'p'})
ledger.put_identity({'id': 'i', 'name': 'Family'})
start = datetime(2026, 1, 1, tzinfo=UTC)
preview = Accounting(ledger).preview({'point_id': 'p', 'identity_id': 'i',
    'start': start, 'end': start + timedelta(hours=3), 'timezone': 'UTC',
    'energy_kwh': '6', 'prices': [(start, '0.25'), (start + timedelta(hours=1), '0.5')]})
print(json.dumps(detail_view(preview['record'], preview['segments'], [], include_history=False)))
ledger.close()
`],{encoding:'utf8'}));
  assert.equal(Number(detail.record.energy_kwh),6);assert.equal(Number(detail.record.known_cost),2.5);
  assert.equal('manual_cost'in detail.record,false);
  assert.deepEqual(detail.billing_periods.map(part=>Number(part.unit_price)),[0.25,0.5]);
  const {page}=await createCardFixture(t);
  await page.evaluate(detail=>{const c=fixture.card;c.expanded.records=true;c.page={records:[detail.record],total:1,limit:25};c.render();c.openDialog('details',detail);},detail);
  await t.test('record row identifies the entered energy',async()=>assert.match(await page.locator('[data-record-id]').innerText(),/Manual energy: 6 kWh/));
  assert.equal(await page.locator('dialog details').first().getAttribute('open'),null);
  await page.locator('dialog details').first().locator('summary').click();
  assert.equal(await page.locator('dialog .billing-period:visible').count(),2);
  assert.match(await page.locator('dialog .billing-period').nth(0).innerText(),/00:00:00–01:00:00.*0.25.*2 kWh.*0.50/s);
  assert.match(await page.locator('dialog .billing-period').nth(1).innerText(),/01:00:00–03:00:00.*0.5.*4 kWh.*2.00/s);
  assert.match(await page.locator('dialog .record-overview').innerText(),/^Manual energy/m);
  assert.doesNotMatch(await page.locator('dialog .billing-details').innerText(),/allocated from sampling intervals/);
  assert.equal(await page.locator('dialog .measurement-period').count(),0);
  await page.getByRole('button',{name:'Edit record',exact:true}).click();
  await page.locator('dialog textarea').fill('Manual energy with tariff cost');
  await page.getByRole('button',{name:'Preview changes',exact:true}).click();
  await page.waitForFunction(()=>fixture.pending.length===1);
  await page.evaluate(detail=>fixture.pending[0].resolve({...detail,token:'manual-tariff',coverage:[],overlaps:[]}),detail);
  await t.test('Before summary retains the entered energy source',async()=>assert.match(await page.locator('dialog .preview > .grid').innerText(),/Manual energy\s+6 kWh/));
  assert.equal(await page.locator('dialog .preview details').getAttribute('open'),null);
  await page.locator('dialog .preview details summary').click();
  assert.equal(await page.locator('dialog .preview .billing-period:visible').count(),2);
  assert.match(await page.locator('dialog .preview .billing-details').innerText(),/0.25.*0.50.*0.5.*2.00/s);
  assert.match(await page.locator('dialog .preview .record-overview').innerText(),/^Manual energy/m);
  assert.doesNotMatch(await page.locator('dialog .preview .billing-details').innerText(),/allocated from sampling intervals/);
});

for(const width of [736,320])test(`compact details keep chronological periods and a distinct gap at ${width}px`,async t=>{
  const {page}=await createCardFixture(t);await page.setViewportSize({width,height:900});
  await openCompactDetails(page);
  assert.deepEqual(await page.locator('dialog details').evaluateAll(nodes=>nodes.map(node=>node.open)),[false]);
  assert.equal(await page.evaluate(()=>fixture.pending.length),0);
  assert.doesNotMatch(await page.locator('dialog').innerText(),/Record history/);
  assert.doesNotMatch(await page.locator('dialog').innerText(),/1797|Revision|estimated|Unavailable|Status:|Source:/);
  assert.match(await page.locator('dialog').innerText(),/17.675.*EUR 5.29.*2026-10-29 · 16:57–19:29 · 2 h 32 min.*A meter reset caused missing energy data/s);
  await page.locator('dialog details').first().locator('summary').click();
  assert.equal(await page.evaluate(()=>fixture.pending.length),0);
  assert.equal(await page.locator('dialog .billing-period').count(),3);
  assert.equal(await page.locator('dialog .billing-gap').count(),1);
  assert.match(await page.locator('dialog .billing-gap').innerText(),/19:04:11–19:04:16.*5 s/);
  assert.match(await page.locator('dialog .billing-details').innerText(),/0.25.*0.319.*0.08/s);
  assert.doesNotMatch(await page.locator('dialog .billing-details').innerText(),/allocated from sampling intervals|rounded|does not establish/);
  assert.equal(await page.evaluate(()=>{const d=fixture.card.dialog.node;return d.scrollWidth<=d.clientWidth&&d.getBoundingClientRect().width<=innerWidth;}),true);
  const {mkdir}=await import('node:fs/promises');await mkdir('.superpowers/card-qa',{recursive:true});
  await page.screenshot({path:`.superpowers/card-qa/task2-${width}-periods.png`,fullPage:true});
  if(width===320){await page.locator('dialog').evaluate(node=>{node.scrollTop=node.scrollHeight;});await page.screenshot({path:'.superpowers/card-qa/task2-320-periods-bottom.png',fullPage:true});}
});
test('manual totals keep measured coverage and exclude allocated gap money',async t=>{
  const {page}=await createCardFixture(t);await openCompactDetails(page,{manual_fee_override:true,manual_cost:'12.00'});
  await page.evaluate(()=>{const d=fixture.compact;d.segments=[d.segments[0],{start:d.record.quality_spans[0].start,end:d.record.quality_spans[0].end,energy_kwh:'0',cost:'3',cost_basis:'manual',unit_price:null,quality:['missing_energy','manual']},...d.segments.slice(1)];fixture.card.dialog.detail=d;fixture.card.dialog.render();});
  await page.locator('dialog details').first().locator('summary').click();
  assert.equal(await page.locator('dialog .billing-period').count(),3);
  assert.equal(await page.locator('dialog .billing-gap').count(),1);
  const text=await page.locator('dialog .billing-details').innerText();assert.doesNotMatch(text,/EUR 3.00|EUR\/kWh|0.08|4.35/);
  assert.equal((await page.locator('dialog').innerText()).match(/EUR 12.00/g)?.length,1);
  await page.evaluate(()=>{fixture.card.dialog.close();});await openCompactDetails(page,{manual_override:true,manual_energy:'17.675',manual_cost:null,has_known_cost:false,known_cost:'0'});
  assert.match(await page.locator('dialog').innerText(),/Cost to be added/);
  assert.equal(await page.locator('dialog details').count(),0);
  await page.evaluate(()=>fixture.card.dialog.close());await openCompactDetails(page,{manual_override:true,manual_energy:'17.675',manual_cost:'12.00',known_cost:'12.00'});
  assert.equal(await page.locator('dialog details').count(),0);
  assert.equal((await page.locator('dialog').innerText()).match(/EUR 12.00/g)?.length,1);
  assert.match(await page.locator('dialog .record-metrics').innerText(),/^Manual energy/m);
  await page.getByRole('button',{name:'Edit record',exact:true}).click();
  await page.getByRole('button',{name:'Preview changes',exact:true}).click();
  await page.waitForFunction(()=>fixture.pending.length===1);
  await page.evaluate(()=>fixture.pending[0].resolve({...fixture.compact,token:'manual-total',coverage:[],overlaps:[]}));
  assert.equal(await page.locator('dialog .preview details').count(),0);
  assert.equal((await page.locator('dialog .preview').innerText()).match(/EUR 12.00/g)?.length,2);
});
test('real tariff periods expand beyond twelve and preserve negative and unknown prices',async t=>{
  const {page}=await createCardFixture(t);await openCompactDetails(page,{quality:[],quality_spans:[]});
  await page.evaluate(()=>{const d=fixture.compact;d.billing_periods=Array.from({length:13},(_,i)=>({...d.billing_periods[0],start:`2026-10-29T${String(i).padStart(2,'0')}:00:00Z`,end:`2026-10-29T${String(i+1).padStart(2,'0')}:00:00Z`,unit_price:i===0?'-0.25':i===1?null:'0.3',cost:i===0?'-0.5':i===1?null:'0.3'}));fixture.card.dialog.render();});
  await page.locator('dialog details').first().locator(':scope > summary').click();
  assert.equal(await page.locator('dialog .billing-period:visible').count(),12);
  assert.match(await page.locator('dialog .billing-period').nth(0).innerText(),/-0.25.*-0.50/s);
  assert.match(await page.locator('dialog .billing-period').nth(1).innerText(),/Unknown price.*Cost to be added/s);
  await page.locator('dialog .more-periods > summary').click();
  assert.equal(await page.locator('dialog .billing-period:visible').count(),13);
  await page.evaluate(()=>fixture.card.hass={...fixture.hass,language:'de'});
  assert.equal(await page.locator('dialog .billing-period:visible').count(),13);
});
test('unchanged subsecond edit boundaries survive compact details and shared preview',async t=>{
  const {page}=await createCardFixture(t);await openCompactDetails(page);
  await page.getByRole('button',{name:'Edit record',exact:true}).click();
  await page.locator('dialog textarea').fill('A note change');
  await page.getByRole('button',{name:'Preview changes',exact:true}).click();
  await page.waitForFunction(()=>fixture.pending.length===1);
  const request=await page.evaluate(()=>fixture.pending[0].request);
  assert.equal(request.expected_revision,1797);assert.equal('start'in request,false);assert.equal('end'in request,false);
  await page.evaluate(()=>fixture.pending[0].resolve({...fixture.compact,token:'preview-token',expected_revision:1797,coverage:[],overlaps:[]}));
  await page.locator('dialog .preview').waitFor();
  assert.equal(await page.locator('dialog .preview details').getAttribute('open'),null);
  await page.locator('dialog .preview details summary').click();
  assert.equal(await page.locator('dialog .preview .billing-period').count(),3);
  assert.equal(await page.locator('dialog .preview .billing-gap').count(),1);
});
test('compact detail language updates retain fee details and grouped dates',async t=>{
  const {page}=await createCardFixture(t);await page.setViewportSize({width:320,height:900});await openCompactDetails(page,{quality:[],quality_spans:[],cost_complete:true});
  await page.locator('dialog details').first().locator('summary').click();
  assert.equal(await page.locator('dialog .billing-date').count(),1);
  await page.evaluate(()=>{const d=fixture.compact;d.billing_periods=[...d.billing_periods,{...d.billing_periods[2],start:'2026-10-30T00:00:00Z',end:'2026-10-30T01:00:00Z',local_date:'2026-10-30'}];fixture.card.dialog.render();});
  await page.locator('dialog details').first().locator('summary').click();
  for(const language of ['zh-Hans','de','fr','pl','it','en']){
    await page.evaluate(language=>fixture.card.hass={...fixture.hass,language},language);
    assert.equal(await page.locator('dialog details').first().getAttribute('open'),'');
    assert.equal(await page.locator('dialog .billing-date').count(),2);
    assert.equal(await page.evaluate(()=>fixture.card.dialog.node.scrollWidth<=fixture.card.dialog.node.clientWidth),true);
  }
});

test('record details show the source outage end reason',async t=>{
  const {page}=await createCardFixture(t);
  await page.evaluate(()=>{
    const record={id:'r',revision:2,point_id:'p',identity_id:'i',start:'2026-10-29T10:00:00Z',end:'2026-10-29T10:01:00Z',timezone:'UTC',status:'ended',source:'automatic',end_reason:'source_unavailable',energy_kwh:'1',known_cost:'0.5',cost_complete:false,quality:['missing_energy']};
    fixture.card.openDialog('details',{record,segments:[],revisions:[]});
  });
  assert.match(await page.locator('dialog').innerText(),/Some energy is missing/);
  await page.locator('dialog details').first().locator('summary').click();
  assert.match(await page.locator('dialog').innerText(),/Ended after the source remained unavailable for 5 minutes/);
});

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
    assert.equal(await select.isDisabled(),true);
    await page.evaluate(()=>fixture.pending.shift().resolve({...fixture.snapshot,points:[{...fixture.snapshot.points[0],selected_identity_id:'j',power_w:'500'}]}));
    await page.waitForFunction(()=>fixture.card.pendingSelections.size===0);
    assert.equal(await select.isDisabled(),false);
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
    d.requestId='request';d.preview={token:'token',record:{point_id:'p',identity_id:'i',timezone:'UTC',start:'2026-01-01T00:00:00Z',end:'2026-01-01T01:00:00Z',status:'ended',source:'manual',energy_kwh:'1',known_cost:'0',has_known_cost:false,cost_complete:false,quality:[]},segments:[],billing_periods:[],overlaps:[]};d.renderPreview();const before=d.node;d.node.scrollTop=40;const scroll=d.node.scrollTop;
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
    const {SelectControl}=await import('/card-controls.js?v=0.1.2-14');const control=new SelectControl();document.body.append(control.node);control.update({options:[{id:'a',name:'A'}],value:'a'});const original=control.node.firstChild;control.update({options:[{id:'a',name:'A'}],value:'a'});const untouched=original===control.node.firstChild;control.node.focus();const options=[{id:'b',name:'B'}];control.update({options,value:'b'});options[0].name='Changed outside';control.node.blur();const name=control.node.firstChild.textContent;control.node.focus();control.update({options:[{id:'c',name:'C'}],value:'c'});control.dispose();control.node.blur();return {untouched,name,value:control.node.value,pending:control.pending,editing:control.editing};
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
  await page.evaluate(()=>fixture.card.setExpanded('records',true));
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

test('record details show each actual problem once without routine explanations',async t=>{
  const {page}=await createCardFixture(t);
  for(const [kind,flags,basis]of [['normal',[],'tariff'],['price',['missing_price'],'unknown'],['sampling',['gap'],'tariff'],['manual',['estimated','manual'],'manual']]){
    await page.evaluate(({flags,basis})=>{const c=fixture.card;c.hass={...fixture.hass,language:'zh-Hans'};const record={id:'r',revision:90,point_id:'p',identity_id:'i',start:'2026-09-22T08:00:00Z',end:'2026-09-22T09:00:00Z',timezone:'UTC',status:'ended',source:'manual',energy_kwh:'1',known_cost:'1',cost_complete:basis!=='unknown',quality:flags};c.openDialog('details',{record,segments:[{start:record.start,end:record.end,energy_kwh:'1',cost:basis==='unknown'?null:'1',cost_basis:basis,quality:flags}],revisions:[{record}]});},{flags,basis});
    const text=await page.locator('dialog').innerText();assert.doesNotMatch(text,/记录历史|修改记录 \(|版本|部分数据为估算值/);assert.equal(await page.locator('dialog details').count(),1);if(kind==='price')assert.match(text,/部分时段未计价/);
    await page.locator('dialog details').first().locator('summary').click();assert.equal(await page.locator('dialog .quality').count(),0);
    if(kind==='price')assert.equal((await page.locator('dialog').innerText()).match(/部分时段未计价/g)?.length,1);
    await page.evaluate(()=>fixture.card.dialog.close());
  }
});


test('chart translations keep metric and table state and narrow details stay bounded',async t=>{
  const {page}=await createCardFixture(t);await page.setViewportSize({width:390,height:844});
  assert.deepEqual(await page.evaluate(()=>{const c=fixture.card;c.expanded.statistics=true;c.summary={matched_count:1,active_count:0,completed_count:1,energy_kwh:'1',known_cost:'1',cost_complete:true,has_energy_data:true,has_known_cost:true,bucket_period:'hour',buckets:[{label:'2026-10-25 02:00 +02:00',energy_kwh:'1',known_cost:'1',cost_complete:true,has_energy_data:true,has_known_cost:true}]};c.render();const v=c.view.chartView;v.details.open=true;v.toggle.focus();c.hass={...fixture.hass,language:'zh-Hans'};return {title:c.view.sections.statistics.toggle.textContent,hint:v.hint.textContent,table:v.toggle.textContent,focus:c.shadowRoot.activeElement===v.toggle,open:v.details.open};}),{title:'记录统计',hint:'按小时统计；重复的当地时间用 UTC 偏移区分。',table:'图表数据',focus:true,open:true});
  await page.evaluate(()=>{const record={id:'r',revision:1,point_id:'p',identity_id:'i',start:'2026-09-22T08:00:00Z',end:'2026-09-22T09:00:00Z',timezone:'UTC',status:'ended',source:'automatic',energy_kwh:'1',known_cost:'1',cost_complete:true,quality:[]};fixture.card.openDialog('details',{record,segments:[{...record,cost:'1',cost_basis:'tariff'}],revisions:[]});});
  await page.locator('dialog details').first().locator('summary').click();
  assert.equal(await page.evaluate(()=>{const d=fixture.card.dialog.node;return d.getBoundingClientRect().width<=innerWidth&&d.scrollWidth<=d.clientWidth;}),true);
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
