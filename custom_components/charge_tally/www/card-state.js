import {tr,locale} from './card-i18n.js?v=0.1.2-7';
const numberFormats=new Map();
export function formatDecimal(value,language='en',digits=3,minimum=0){
  if(value==null)return '—';
  language=locale(language);
  const key=JSON.stringify([language,digits,minimum]);
  if(!numberFormats.has(key))numberFormats.set(key,new Intl.NumberFormat(language,{maximumFractionDigits:digits,minimumFractionDigits:minimum}));
  // Intl accepts decimal strings directly, without an intermediate binary float.
  const parts=numberFormats.get(key).formatToParts(value);
  if(parts.some(part=>part.type==='nan'||part.type==='infinity'))return String(value);
  return parts.map(part=>part.value).join('');
}
export function formatCost(summary, currency = '', language = 'en') {
  const value = `${currency} ${formatDecimal(summary?.known_cost,language,2,2)}`.trim();
  return summary?.cost_complete === true ? value : tr('costIncomplete',language,{value});
}
export function localInput(instant, timezone) {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(instant));
  const p = Object.fromEntries(parts.map(part => [part.type,part.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}`;
}
export function localCandidates(value, timezone) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) return [];
  const full = value.length === 16 ? value + ':00' : value;
  const naive = Date.parse(full + 'Z');
  if (!Number.isFinite(naive) || new Date(naive).toISOString().slice(0,19) !== full) return [];
  // Probe offsets around the calendar day, then round-trip every candidate.
  const offsets = new Set();
  for (let h = -36; h <= 36; h += 3) {
    const probe = naive + h * 3600000;
    offsets.add(Date.parse(localInput(probe,timezone) + 'Z') - probe);
  }
  return [...offsets].map(offset => naive - offset).filter(at => localInput(at,timezone) === full).sort((a,b)=>a-b).map(at=>new Date(at).toISOString());
}
export function resolveLocal(value, timezone, selection) {
  const candidates = localCandidates(value,timezone);
  if (!candidates.length) throw Object.assign(new Error('nonexistent'),{code:'nonexistent'});
  if (candidates.length === 1) return candidates[0];
  if (candidates.includes(selection)) return selection;
  throw Object.assign(new Error('ambiguous'),{code:'ambiguous'});
}
export function validateRange(start,end) {
  return {valid:!!start && !!end && Number.isFinite(Date.parse(start)) && Date.parse(start)<Date.parse(end),code:'range'};
}
const decimal = value => typeof value === 'string' && value.length <= 100 && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value);
export function validateForm(form,timezone,record) {
  try {
    if (!form.identity_id || !form.point_id) return {valid:false,code:'required'};
    const boundaries={start:resolveLocal(form.start,timezone,form.start_choice),end:resolveLocal(form.end,timezone,form.end_choice)};
    const unchanged=[];
    for(const key of ['start','end']){
      if(record?.[key] && Math.floor(Date.parse(boundaries[key])/1000)===Math.floor(Date.parse(record[key])/1000)){
        boundaries[key]=record[key];unchanged.push(key);
      }
    }
    // Persisted unchanged boundaries retain server precision, even below a millisecond.
    if (unchanged.length!==2 && !validateRange(boundaries.start,boundaries.end).valid) return {valid:false,code:'range'};
    if (form.energy_kwh && (!decimal(form.energy_kwh) || /^-/.test(form.energy_kwh))) return {valid:false,code:'energy'};
    if (form.cost && !decimal(form.cost)) return {valid:false,code:'decimal'};
    if (form.cost_mode==='manual' && !form.cost) return {valid:false,code:'decimal'};
    if ((form.note || '').length>2000) return {valid:false,code:'note'};
    return {valid:true,...boundaries,unchanged};
  } catch (error) { return {valid:false,code:error.code || 'timezone'}; }
}
const filters = config => Object.fromEntries(['point_id','identity_id'].filter(key=>config[key]).map(key=>[key,config[key]]));
export function queryRequest(config,range) {
  const bucket = range.bucket_period ?? 'auto';
  if (!['auto','hour','day','month','year'].includes(bucket)) throw new Error('Invalid bucket period');
  const grouping = 'bucket_period' in range ? {bucket_period:bucket} : {};
  if ('calendar_period' in range) {
    if (!['daily','monthly','yearly','total'].includes(range.calendar_period) || 'start' in range || 'end' in range) throw new Error('Invalid calendar period');
    return {type:'charge_tally/query',...filters(config),...grouping,calendar_period:range.calendar_period};
  }
  if (!validateRange(range.start,range.end).valid) throw new Error('Invalid range');
  return {type:'charge_tally/query',...filters(config),...grouping,start:range.start,end:range.end};
}
export function recordsRequest(config,offset=0,limit=25) {
  if (!Number.isInteger(offset) || offset<0 || !Number.isInteger(limit) || limit<1 || limit>100) throw new Error('Invalid page');
  return {type:'charge_tally/records',...filters(config),offset,limit};
}
export function previewRequest(form,timezone,record) {
  const result=validateForm(form,record?.timezone || timezone,record);
  if (!result.valid) throw Object.assign(new Error(result.code),{code:result.code});
  const boundaries={start:result.start,end:result.end};
  for(const key of result.unchanged)delete boundaries[key];
  const cost=form.cost_mode==='auto'?{}:{cost:form.cost_mode==='unknown'?null:form.cost||null};
  return {type:'charge_tally/preview',...(record ? {record_id:record.id,expected_revision:record.revision} : {point_id:form.point_id}),identity_id:form.identity_id,...boundaries,
    ...(form.energy_kwh && form.energy_kwh!==record?.manual_energy ? {energy_kwh:form.energy_kwh} : {}),...cost,note:form.note || ''};
}
export function commitRequest(preview,request_id) {
  return {type:'charge_tally/commit',token:preview.token,request_id,...(preview.expected_revision == null ? {} : {expected_revision:preview.expected_revision})};
}
export function liveRequest(service,point,request_id) {
  if (!point?.identity_entity_id || point.active === false) throw Object.assign(new Error('unavailable'),{code:'unavailable'});
  if (service === 'start' && (!point.available || point.active_record)) throw Object.assign(new Error('unavailable'),{code:'unavailable'});
  if (service === 'end' && !point.active_record) throw new Error('No active record');
  return {type:'call_service',domain:'charge_tally',service,return_response:true,service_data:service==='end' ? {record_id:point.active_record.id,expected_revision:point.active_record.revision,request_id} : {point_id:point.id,...(point.selected_identity_id?{identity_id:point.selected_identity_id}:{}),request_id}};
}
export function identityRequest(point,identity) {
  if (!point?.identity_entity_id || point.active === false || !identity?.name) throw Object.assign(new Error('unavailable'),{code:'unavailable'});
  return {type:'call_service',domain:'select',service:'select_option',service_data:{entity_id:point.identity_entity_id,option:identity.name}};
}
export function errorMessage(error,language='en') {
  const key='error.'+error?.code;
  const message=tr(key,language);
  return message===key ? tr('error.unknown',language) : message;
}
export function periodRange(period,timezone,now=new Date()) {
  const day=localInput(now,timezone).slice(0,10);
  const start=period==='monthly' ? day.slice(0,7)+'-01' : period==='yearly' ? day.slice(0,4)+'-01-01' : day;
  const next=new Date(start+'T00:00:00Z');
  if (period==='monthly') next.setUTCMonth(next.getUTCMonth()+1);
  else if (period==='yearly') next.setUTCFullYear(next.getUTCFullYear()+1);
  else next.setUTCDate(next.getUTCDate()+1);
  return {start:resolveLocal(start+'T00:00',timezone),end:resolveLocal(next.toISOString().slice(0,10)+'T00:00',timezone)};
}
export class Latest {
  constructor(){this.epoch=0;this.keys=new Map();}
  invalidate(){this.epoch++;this.keys.clear();}
  async run(key,request,accept,reject=()=>{}) {
    const epoch=this.epoch, token=(this.keys.get(key)||0)+1;this.keys.set(key,token);
    const current=()=>epoch===this.epoch && this.keys.get(key)===token;
    try { const value=await request();if(current()) accept(value); }
    catch(error){if(current()) reject(error);}
  }
}
export class Subscription {
  constructor(changed,failed=()=>{},clock=globalThis) {this.changed=changed;this.failed=failed;this.clock=clock;this.epoch=0;this.attempt=0;}
  connect(connection) {
    if(this.connection===connection) return;
    this.disconnect();this.connection=connection;
    if(!connection) return;
    this.ready=()=>this.start();this.lost=()=>this.clear();
    connection.addEventListener('ready',this.ready);connection.addEventListener('disconnected',this.lost);
    if(connection.connected!==false) this.start();
  }
  cancel(unsubscribe){try{Promise.resolve(unsubscribe?.()).catch(()=>{});}catch{/* A closed socket needs no further cancellation. */}}
  clear(){this.epoch++;if(this.timer)this.clock.clearTimeout(this.timer);this.timer=null;this.cancel(this.unsubscribe);this.unsubscribe=null;this.changed(null);}
  retry(){
    if(!this.connection || this.connection.connected===false)return;
    const delay=Math.min(30000,1000*2**Math.min(this.attempt++,5));
    this.timer=this.clock.setTimeout(()=>{this.timer=null;this.start();},delay);
  }
  async start(){
    this.clear();const epoch=this.epoch;let generation=0;
    try {
      const unsubscribe=await this.connection.subscribeMessage(snapshot=>{
        if(epoch!==this.epoch)return;
        if(snapshot.type==='unloaded'){this.clear();this.retry();return;}
        if(!Number.isInteger(snapshot.generation) || snapshot.generation<=generation) return;
        generation=snapshot.generation;this.attempt=0;this.changed(snapshot);
      },{type:'charge_tally/subscribe'});
      if(epoch!==this.epoch) this.cancel(unsubscribe); else this.unsubscribe=unsubscribe;
    } catch(error){if(epoch===this.epoch){this.failed(error);this.retry();}}
  }
  disconnect(){
    this.clear();
    if(this.connection){this.connection.removeEventListener('ready',this.ready);this.connection.removeEventListener('disconnected',this.lost);}
    this.connection=null;
  }
}
