import {formatCost,formatDecimal,localInput,recordCostState,permanentEnergyGap} from './card-state.js?v=0.1.2-13';
import {tr} from './card-i18n.js?v=0.1.2-13';
import {SelectControl} from './card-controls.js?v=0.1.2-13';

export function el(tag,text,attributes={}) {
  const node=document.createElement(tag);if(text!=null)node.textContent=text;
  for(const [key,value] of Object.entries(attributes)){if(key==='class')node.className=value;else node.setAttribute(key,value);}
  return node;
}
export function button(text,handler,disabled=false,kind='') {
  const node=el('button',text,{type:'button',class:kind});node.disabled=disabled;node.addEventListener('click',handler);return node;
}
export function field(text,input){const label=el('label');label.append(el('span',text),input);return label;}
export function select(options,value,change){const control=new SelectControl({onChange:change});control.update({options,value});control.node.selectControl=control;return control.node;}
// Presentation updates retain existing controls, listeners and scroll containers.
export function updateLabels(target,source,mapping=new Map()){
  mapping.set(source,target);
  if(target.nodeType===3){if(target.textContent!==source.textContent)target.textContent=source.textContent;return mapping;}
  if(target.tagName==='SELECT'){
    target.selectControl?.update({options:Array.from(source.options,o=>({id:o.value,name:o.textContent})),value:source.value,disabled:source.disabled});source.selectControl?.dispose();return mapping;
  }
  if(target.tagName==='INPUT'||target.tagName==='TEXTAREA')return mapping;
  for(const attribute of source.attributes||[])if(attribute.name!=='open')target.setAttribute(attribute.name,attribute.value);
  const old=Array.from(target.childNodes),next=Array.from(source.childNodes);
  next.forEach((node,index)=>{
    const current=old[index];
    if(current&&current.nodeType===node.nodeType&&current.nodeName===node.nodeName)updateLabels(current,node,mapping);
    else if(current)current.replaceWith(node);else target.append(node);
  });
  for(const node of old.slice(next.length))node.remove();
  return mapping;
}
export function input(type,value=''){const node=el('input',null,{type});node.value=value;return node;}
export function metric(label,value){const node=el('div',null,{class:'metric'});node.append(el('small',label),el('div',value,{class:'value'}));return node;}
export function quality(flags,language){return (flags||[]).map(flag=>tr(flag,language)).join(' · ');}
export function summaryView(summary,currency,language){const node=el('div',null,{class:'grid'}),cost=summary?.status?recordCostState(summary,currency,language):{label:summary?.cost_complete?'cost':'calculatedCost',value:formatCost(summary,currency,language)};node.append(metric(tr('energy',language),`${formatDecimal(summary?.energy_kwh,language)} kWh`),metric(tr(cost.label,language),cost.value));return node;}
export function dateText(value,timezone){if(!value)return '—';try{return localInput(value,timezone).replace('T',' ');}catch{return value;}}
export function recordOverview(record,currency,language){
  const view=el('div',null,{class:'stack record-overview'}),metrics=el('div',null,{class:'record-metrics'}),cost=recordCostState(record,currency,language);
  const energy=metric(tr(record.manual_override?'manualEnergyLabel':'energy',language),'');energy.children[1].append(el('span',formatDecimal(record.energy_kwh,language)),el('small',' kWh',{class:'record-unit'}));
  metrics.append(energy,metric(tr(cost.label,language),cost.value));view.append(metrics);
  const start=localInput(record.start,record.timezone),end=record.end?localInput(record.end,record.timezone):null;
  const minutes=Math.max(0,Math.round(((record.end?Date.parse(record.end):Date.now())-Date.parse(record.start))/60000));
  const range=end?(start.slice(0,10)===end.slice(0,10)?`${start.slice(0,10)} · ${start.slice(11,16)}–${end.slice(11,16)}`:`${start.slice(0,10)} ${start.slice(11,16)} – ${end.slice(0,10)} ${end.slice(11,16)}`):`${start.slice(0,10)} · ${start.slice(11,16)}–…`;
  view.append(el('p',`${range} · ${tr('durationCompact',language,{hours:Math.floor(minutes/60),minutes:minutes%60})}`),el('p',`${tr(record.status,language)} · ${tr(record.source==='manual'?'manual_source':record.source,language)} · ${record.timezone}`,{class:'muted record-context'}));
  if(record.note)view.append(el('p',record.note));
  for(const issue of cost.issues)view.append(el('p',tr(issue,language),{class:'record-issue'}));
  return view;
}
export function billingDetails(detail,language,currency){
  const {record}=detail,manual=(record.manual_fee_override||record.manual_override)&&Object.hasOwn(record,'manual_cost');
  if(record.manual_override&&manual)return null;
  const section=el('details',null,{class:'record-section'}),body=el('div',null,{class:'billing-details stack'});
  section.append(el('summary',tr('feeDetails',language)),body);
  const missing=(record.quality_spans||[]).filter(permanentEnergyGap);
  // Fee allocations include unmeasured zero-energy spans; only raw measured parts
  // can establish measurement coverage. Never use this view for accounting.
  const periods=manual?(detail.segments||[]).filter(part=>!part.quality?.includes('missing_energy')):(detail.billing_periods??detail.segments??[]);
  const entries=[...periods.map(period=>({period,start:period.start})),...missing.map(gap=>({gap,start:gap.start}))].sort((a,b)=>Date.parse(a.start)-Date.parse(b.start));
  let date,shown=0;const hidden=[];
  for(const entry of entries){
    const part=entry.period||entry.gap,currentDate=localInput(part.start,record.timezone).slice(0,10),range=`${localInput(part.start,record.timezone).slice(11)}–${localInput(part.end,record.timezone).slice(11)}`;
    if(currentDate!==date){const heading=el('p',currentDate,{class:'billing-date muted'});body.append(heading);if(shown>=12)hidden.push(heading);date=currentDate;}
    if(entry.gap){const gap=el('p',`${range} · ${tr('dataGap',language,{seconds:Math.max(1,Math.round((Date.parse(part.end)-Date.parse(part.start))/1000))})}`,{class:'billing-gap muted'});body.append(gap);if(shown>=12)hidden.push(gap);continue;}
    const row=el('div',null,{class:`billing-period${manual?' measurement-period':''}`});row.append(el('span',range,{class:'billing-range'}));
    const values=manual?[[tr('energy',language),`${formatDecimal(part.energy_kwh,language)} kWh`]]:[[`${currency}/kWh`,part.unit_price==null?tr('price_unknown',language):formatDecimal(part.unit_price,language,6)],[tr('energy',language),`${formatDecimal(part.energy_kwh,language)} kWh`],[tr('cost',language),part.cost==null?tr('amountMissing',language):`${currency} ${formatDecimal(part.cost,language,2,2)}`]];
    for(const [label,value]of values){const cell=el('span',null,{class:'billing-value'});cell.append(el('small',label),el('span',value));row.append(cell);}body.append(row);if(shown++>=12)hidden.push(row);
  }
  if(!periods.length&&!missing.length)body.append(el('p',tr('noCoverage',language)));
  if(hidden.length){const more=el('details',null,{class:'more-periods'});more.append(el('summary',tr('showAllPeriods',language)),...hidden);body.append(more);}
  return section;
}
