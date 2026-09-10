import test from 'node:test';
import assert from 'node:assert/strict';
import {formatCost, validateRange, localCandidates, localInput, resolveLocal, validateForm,
  queryRequest, recordsRequest, previewRequest, commitRequest, liveRequest, identityRequest,
  errorMessage, Latest, Subscription, periodRange} from '../../custom_components/charge_tally/www/card-state.js';

test('unknown cost formats the known subtotal, including negative prices', () => {
  assert.equal(formatCost({known_cost:'2.500000000000000001',cost_complete:false},'CNY','zh-Hans'), 'CNY 2.50（已知小计 · 待补充）');
  assert.equal(formatCost({known_cost:'-2.50',cost_complete:true},'CNY','en'), 'CNY -2.50');
  assert.match(formatCost({},'USD','en'), /pending/);
});
test('datetime input is interpreted in accounting timezone, not browser timezone', () => {
  assert.deepEqual(localCandidates('2026-09-09T10:00','Asia/Shanghai'), ['2026-09-09T02:00:00.000Z']);
  assert.equal(localInput('2026-09-09T02:00:00Z','Asia/Shanghai'), '2026-09-09T10:00:00');
  assert.equal(localCandidates('2026-02-30T10:00','Asia/Shanghai').length, 0);
});
test('DST gap and fold are explicit and fold needs user selection', () => {
  assert.deepEqual(localCandidates('2026-03-08T02:30','America/New_York'), []);
  const candidates = localCandidates('2026-11-01T01:30','America/New_York');
  assert.deepEqual(candidates, ['2026-11-01T05:30:00.000Z','2026-11-01T06:30:00.000Z']);
  assert.throws(() => resolveLocal('2026-11-01T01:30','America/New_York'), /ambiguous/);
  assert.equal(resolveLocal('2026-11-01T01:30','America/New_York', candidates[1]), candidates[1]);
  assert.throws(() => resolveLocal('2026-03-08T02:30','America/New_York'), /nonexistent/);
});
test('ranges reject equal, reversed and missing instants', () => {
  assert.equal(validateRange('2026-09-09T10:00','2026-09-09T09:00').valid, false);
  assert.equal(validateRange('','').valid, false);
  assert.equal(validateRange('2026-09-09T10:00Z','2026-09-09T10:00Z').valid, false);
  assert.equal(validateRange('2026-09-09T10:00Z','2026-09-09T11:00Z').valid, true);
});
const form = {point_id:'p',identity_id:'i',start:'2026-09-09T10:00',end:'2026-09-09T11:00',energy_kwh:'1.000000000000000001',cost:'-2.50',note:'<script>safe</script>'};
test('manual amounts remain strings and unknown cost is explicit null', () => {
  assert.equal(validateForm(form,'Asia/Shanghai').valid, true);
  const request = previewRequest(form,'Asia/Shanghai');
  assert.equal(request.start,'2026-09-09T02:00:00.000Z');
  assert.equal(request.energy_kwh,form.energy_kwh);
  assert.equal(request.cost,'-2.50');
  assert.equal(previewRequest({...form,cost:''},'Asia/Shanghai').cost,null);
  assert.equal('energy_kwh' in previewRequest({...form,energy_kwh:''},'Asia/Shanghai'),false);
});
test('manual validation rejects malformed numbers, negative energy, oversized note', () => {
  for (const energy_kwh of ['NaN','Infinity','-1','1x','1'.repeat(101)]) assert.equal(validateForm({...form,energy_kwh},'Asia/Shanghai').valid,false);
  assert.equal(validateForm({...form,cost:'NaN'},'Asia/Shanghai').valid,false);
  assert.equal(validateForm({...form,note:'x'.repeat(2001)},'Asia/Shanghai').valid,false);
});
test('edit preserves original timezone and revision, never changes point', () => {
  const record = {id:'r',revision:7,timezone:'America/New_York'};
  const request = previewRequest(form,'Asia/Shanghai',record);
  assert.equal(request.start,'2026-09-09T14:00:00.000Z');
  assert.equal(request.expected_revision,7);
  assert.equal(request.record_id,'r');
  assert.equal('point_id' in request,false);
  assert.deepEqual(commitRequest({token:'t',expected_revision:7},'op'), {type:'charge_tally/commit',token:'t',expected_revision:7,request_id:'op'});
  assert.equal('expected_revision' in commitRequest({token:'t',expected_revision:null},'op'),false);
});
test('statistics request uses backend date range; history pagination is separately scoped', () => {
  assert.deepEqual(queryRequest({point_id:'p',identity_id:'i'}, {start:'2026-09-08T16:00:00.000Z',end:'2026-09-09T16:00:00.000Z'}),{type:'charge_tally/query',point_id:'p',identity_id:'i',start:'2026-09-08T16:00:00.000Z',end:'2026-09-09T16:00:00.000Z'});
  assert.deepEqual(recordsRequest({point_id:'p',identity_id:'',start:'ignored'},25),{type:'charge_tally/records',point_id:'p',offset:25,limit:25});
  assert.throws(() => recordsRequest({},0,101));
});
test('live service uses active record revision and response wrapper, native select uses name', () => {
  const p={id:'p',identity_entity_id:'select.actual',active_record:{id:'r',revision:9},available:true};
  assert.deepEqual(liveRequest('end',p,'op'),{type:'call_service',domain:'charge_tally',service:'end',return_response:true,service_data:{record_id:'r',expected_revision:9,request_id:'op'}});
  assert.deepEqual(identityRequest(p,{name:'Family',id:'i'}),{type:'call_service',domain:'select',service:'select_option',service_data:{entity_id:'select.actual',option:'Family'}});
  assert.throws(() => liveRequest('start',{id:'archived'},'op'));
  assert.throws(() => identityRequest({id:'archived'},{name:'Family'}));
});
test('calendar presets use timezone day and month boundaries', () => {
  assert.deepEqual(periodRange('daily','Asia/Shanghai',new Date('2026-09-09T18:00Z')),{start:'2026-09-09T16:00:00.000Z',end:'2026-09-10T16:00:00.000Z'});
  assert.equal(periodRange('monthly','Asia/Shanghai',new Date('2026-09-09T18:00Z')).start,'2026-08-31T16:00:00.000Z');
  assert.equal(periodRange('daily','America/New_York',new Date('2026-03-08T12:00Z')).end,'2026-03-09T04:00:00.000Z');
});
test('errors provide localized actionable guidance', () => {
  assert.match(errorMessage({code:'stale_preview'},'en'), /preview/i);
  assert.match(errorMessage({code:'conflict'},'zh-Hans'), /刷新/);
  assert.match(errorMessage({code:'home_assistant_error'},'en'), /Home Assistant/);
});
test('newer request and invalidation suppress old responses and errors', async () => {
  const latest = new Latest(); let first; const shown=[];
  const old=latest.run('query',()=>new Promise(r=>{first=r;}),v=>shown.push(v));
  await latest.run('query',async()=>2,v=>shown.push(v)); first(1); await old;
  assert.deepEqual(shown,[2]);
  let reject; const pending=latest.run('detail',()=>new Promise((_,r)=>{reject=r;}),v=>shown.push(v),()=>shown.push('error'));
  latest.invalidate(); reject(new Error('old')); await pending;
  assert.deepEqual(shown,[2]);
});
function connection() {
  const listeners=new Map(), callbacks=[]; let canceled=0;
  return {connected:true,callbacks,listeners,get canceled(){return canceled;},
    addEventListener(n,f){listeners.set(n,f);},removeEventListener(n){listeners.delete(n);},
    async subscribeMessage(cb){callbacks.push(cb);return ()=>{canceled++;};}};
}
test('subscription rejects old generation, clears on disconnect and resets generation on reconnect', async () => {
  const c=connection(), seen=[]; const s=new Subscription(v=>seen.push(v));
  s.connect(c); await Promise.resolve(); c.callbacks[0]({generation:2,points:['new']}); c.callbacks[0]({generation:1,points:['old']});
  assert.equal(seen.at(-1).points[0],'new');
  c.listeners.get('disconnected')(); assert.equal(seen.at(-1),null);
  c.listeners.get('ready')(); await Promise.resolve();
  c.callbacks[0]({generation:99,points:['stale runtime']}); c.callbacks[1]({generation:1,points:['reloaded']});
  assert.equal(seen.at(-1).points[0],'reloaded'); s.disconnect();
  assert.equal(seen.at(-1),null); assert.equal(c.canceled,2); assert.equal(c.listeners.size,0);
});
test('late subscribe completion is canceled after unmount', async () => {
  let resolve, canceled=0;const c=connection(); c.subscribeMessage=()=>new Promise(r=>{resolve=r;});
  const s=new Subscription(()=>{});s.connect(c);s.disconnect();resolve(()=>{canceled++;});await Promise.resolve();await Promise.resolve();assert.equal(canceled,1);
});

test('entry unload clears immediately, retries with bounded backoff, and resets generation', async () => {
  const c=connection(),seen=[],timers=[];
  const clock={setTimeout(fn,delay){const timer={fn,delay};timers.push(timer);return timer;},clearTimeout(timer){timer.canceled=true;}};
  const s=new Subscription(v=>seen.push(v),()=>{},clock);s.connect(c);await Promise.resolve();
  c.callbacks[0]({generation:8,points:['old']});c.callbacks[0]({type:'unloaded'});
  assert.equal(seen.at(-1),null);assert.equal(timers[0].delay,1000);
  timers[0].fn();await Promise.resolve();c.callbacks[1]({generation:1,points:['new']});
  assert.equal(seen.at(-1).points[0],'new');c.callbacks[0]({generation:99,points:['stale']});assert.equal(seen.at(-1).points[0],'new');
  c.callbacks[1]({type:'unloaded'});s.disconnect();assert.equal(timers.at(-1).canceled,true);
});
test('unchanged edit boundaries retain original precision instead of rewriting rounded input', () => {
  const record={id:'r',revision:2,timezone:'Asia/Shanghai',start:'2026-09-09T02:00:00.123456+00:00',end:'2026-09-09T03:00:00.654321+00:00'};
  const request=previewRequest(form,'Asia/Shanghai',record);
  assert.equal('start' in request,false);assert.equal('end' in request,false);
});
test('automatic pricing omits manual cost, unknown explicitly sends null', () => {
  assert.equal('cost' in previewRequest({...form,cost:'',cost_mode:'auto'},'Asia/Shanghai'),false);
  assert.equal(previewRequest({...form,cost:'9',cost_mode:'unknown'},'Asia/Shanghai').cost,null);
  assert.equal(validateForm({...form,cost:'',cost_mode:'manual'},'Asia/Shanghai').valid,false);
});
test('subscription failures back off to 30 seconds and disconnect clears pending retry', async () => {
  const c=connection(),timers=[];c.subscribeMessage=async()=>{throw {code:'home_assistant_error'};};
  const clock={setTimeout(fn,delay){const t={fn,delay};timers.push(t);return t;},clearTimeout(t){t.canceled=true;}};
  const s=new Subscription(()=>{},()=>{},clock);s.connect(c);await Promise.resolve();await Promise.resolve();
  for(let i=0;i<6;i++){timers.at(-1).fn();await Promise.resolve();await Promise.resolve();}
  assert.deepEqual(timers.map(t=>t.delay),[1000,2000,4000,8000,16000,30000,30000]);
  c.listeners.get('disconnected')();assert.equal(timers.at(-1).canceled,true);s.disconnect();
});

// Only DOM plumbing is replaced; controller requests, callbacks and dialogs are real.
class TestNode extends EventTarget {
  constructor(){super();this.children=[];this.dataset={};}
  append(...nodes){this.children.push(...nodes);}
  setAttribute(){}
  showModal(){}
  close(){this.dispatchEvent(new Event('close'));}
  remove(){}
}
globalThis.HTMLElement=class {attachShadow(){this.shadowRoot=new TestNode();}};
globalThis.document={createElement:()=>new TestNode()};
globalThis.window={customCards:[]};
globalThis.customElements={get:()=>undefined,define:()=>{}};
const {ChargeTallyCard}=await import('../../custom_components/charge_tally/www/charge-tally-card.js');
const {RecordDialog}=await import('../../custom_components/charge_tally/www/card-dialog.js?v=0.1.0');
const state=await import('../../custom_components/charge_tally/www/card-state.js');
const {tr,summaryView,segmentTable}=await import('../../custom_components/charge_tally/www/card-ui.js?v=0.1.0');

test('segment ranges use the record accounting timezone without altering UTC data',()=>{
  const segments=[{local_date:'2025-12-31',start:'2025-12-31T15:00:00+00:00',end:'2025-12-31T16:00:00+00:00',energy_kwh:'7',cost:null}];
  const before=structuredClone(segments);
  const table=segmentTable(segments,'zh-Hans','CNY','Asia/Shanghai');
  assert.equal(table.children[0].children[1].children[0].textContent,'2025-12-31 23:00:00 → 2026-01-01 00:00:00 (Asia/Shanghai)');
  assert.deepEqual(segments,before);
});
test('long server decimals are formatted for display without changing payloads',()=>{
  const summary={energy_kwh:'0.285887930259482529870184281103830795',known_cost:'0.142943965129741264935092140551915398',cost_complete:false};
  const original=structuredClone(summary);
  assert.equal(typeof state.formatDecimal,'function');
  assert.equal(state.formatDecimal(summary.energy_kwh,'zh-Hans'),'0.286');
  assert.equal(state.formatDecimal('9007199254740993.125','en'),'9,007,199,254,740,993.125');
  assert.equal(formatCost(summary,'CNY','zh-Hans'),'CNY 0.14（已知小计 · 待补充）');
  assert.equal(formatCost({...summary,known_cost:'-2.555',cost_complete:true},'CNY','en'),'CNY -2.56');
  const view=summaryView(summary,'CNY','zh-Hans');
  assert.equal(view.children[0].children[1].textContent,'0.286 kWh');
  assert.equal(view.children[1].children[1].textContent,'CNY 0.14（已知小计 · 待补充）');
  const table=segmentTable([{energy_kwh:summary.energy_kwh,cost:summary.known_cost}], 'en','CNY');
  assert.equal(table.children[0].children[1].children[1].textContent,'0.286 kWh');
  assert.equal(table.children[0].children[1].children[2].textContent,'CNY 0.14');
  assert.deepEqual(summary,original);
  const request=previewRequest({...form,energy_kwh:summary.energy_kwh,cost:summary.known_cost},'Asia/Shanghai');
  assert.equal(request.energy_kwh,summary.energy_kwh);assert.equal(request.cost,summary.known_cost);
  assert.equal(tr('reset','zh-Hans'),'电表重置');
});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function controller(callWS){
  const card=new ChargeTallyCard();card.render=()=>{};card.refresh=()=>{};
  card.snapshot={points:[],archived_points:[],identities:[],timezone:'Asia/Shanghai',currency:'CNY'};
  card._hass={connection:{connected:true},callWS};return card;
}
for(const service of ['start','end'])test(`live ${service} retries the original operation after an unconfirmed result`,async()=>{
  const sent=[];let fail=true;
  const card=controller(async request=>{sent.push(structuredClone(request));if(fail)throw new Error('Response lost');return {response:{id:'confirmed'}};});
  const point={id:'p',identity_entity_id:'select.p',available:true,selected_identity_id:'i',active_record:service==='end'?{id:'r',revision:9}:null};
  card.live(service,point);await tick();
  if(service==='end')point.active_record.revision=10;
  card.live(service,point);await tick();
  assert.deepEqual(sent[1],sent[0]);
  fail=false;card.live(service,point);await tick();assert.deepEqual(sent[2],sent[0]);
  assert.equal(card.lastRecord.id,'confirmed');
  card.live(service,point);await tick();assert.notEqual(sent[3].service_data.request_id,sent[0].service_data.request_id);
  fail=true;card.live(service,point);await tick();
  card.live(service,{...point,id:'other',active_record:service==='end'?{id:'other-r',revision:1}:null});await tick();
  assert.notEqual(sent.at(-1).service_data.request_id,sent.at(-2).service_data.request_id);
  const snapshot=card.snapshot;card.onSnapshot(null);card.snapshot=snapshot;
  card.live(service,{...point,id:'other',active_record:service==='end'?{id:'other-r',revision:2}:null});await tick();
  assert.deepEqual(sent.at(-1),sent.at(-2));
  card.snapshot=null;ChargeTallyCard.prototype.refresh.call(card,true);card.snapshot=snapshot;
  card.live(service,{...point,id:'other',active_record:service==='end'?{id:'other-r',revision:2}:null});await tick();
  assert.notEqual(sent.at(-1).service_data.request_id,sent.at(-2).service_data.request_id);
});
for(const mode of ['create','reassign'])for(const outcome of ['success','failure'])test(`new ${mode} dialog intent suppresses older detail ${outcome}`,async t=>{
  t.mock.method(RecordDialog.prototype,'render',()=>{});
  let resolve,reject;const card=controller(()=>new Promise((yes,no)=>{resolve=yes;reject=no;}));
  card.details({id:'old'});card.openDialog(mode,{record:{id:'current'}});const newer=card.dialog;
  if(outcome==='success')resolve({record:{id:'old'}});else reject({code:'conflict'});
  await tick();assert.equal(card.dialog,newer);assert.equal(card.dialog.mode,mode);assert.equal(card.error,undefined);
  card.dialog.close();
});
test('closing a dialog or disconnecting invalidates pending detail intent',async t=>{
  t.mock.method(RecordDialog.prototype,'render',()=>{});
  let resolve;const card=controller(()=>new Promise(yes=>{resolve=yes;}));
  card.openDialog('create');card.details({id:'old'});card.dialog.close();resolve({record:{id:'old'}});await tick();assert.equal(card.dialog,null);
  card.details({id:'another'});card.onSnapshot(null);resolve({record:{id:'another'}});await tick();assert.equal(card.dialog,null);
});
test('note-only editing preserves a valid record entirely within one second',()=>{
  const record={id:'r',revision:4,timezone:'Asia/Shanghai',start:'2026-09-09T02:00:00.100000Z',end:'2026-09-09T02:00:00.900000Z'};
  const values={...form,start:'2026-09-09T10:00:00',end:'2026-09-09T10:00:00',note:'Only changed note',cost_mode:'auto',energy_kwh:''};
  const request=previewRequest(values,'Asia/Shanghai',record);
  assert.equal(request.note,values.note);assert.equal('start' in request,false);assert.equal('end' in request,false);
  assert.throws(()=>previewRequest({...values,end:'2026-09-09T09:59:59'},'Asia/Shanghai',record),/range/);
});
