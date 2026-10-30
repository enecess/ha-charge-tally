import {formatCost,formatDecimal,localInput,recordCostState} from './card-state.js?v=0.1.2-12';
import {tr} from './card-i18n.js?v=0.1.2-12';
import {SelectControl} from './card-controls.js?v=0.1.2-12';

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
export function quality(flags,language,context={}){return (flags||[]).map(flag=>tr(flag==='estimated'&&context.kind==='segment'?((flags.includes('manual')||context.cost_basis==='manual')?'estimateManual':'estimateSampling'):flag,language)).join(' · ');}
export function summaryView(summary,currency,language){const node=el('div',null,{class:'grid'});node.append(metric(tr('energy',language),`${formatDecimal(summary?.energy_kwh,language)} kWh`),metric(tr('cost',language),formatCost(summary,currency,language)));return node;}
export function dateText(value,timezone){if(!value)return '—';try{return localInput(value,timezone).replace('T',' ');}catch{return value;}}
export function recordOverview(record,currency,language){
  const view=el('div',null,{class:'stack record-overview'}),metrics=el('div',null,{class:'record-metrics'}),cost=recordCostState(record,currency,language);
  const energy=metric(tr('energy',language),'');energy.children[1].append(el('span',formatDecimal(record.energy_kwh,language)),el('small',' kWh',{class:'record-unit'}));
  metrics.append(energy,metric(tr(cost.label,language),cost.value));view.append(metrics);
  const start=localInput(record.start,record.timezone),end=record.end?localInput(record.end,record.timezone):null;
  const minutes=Math.max(0,Math.round(((record.end?Date.parse(record.end):Date.now())-Date.parse(record.start))/60000));
  const range=end?(start.slice(0,10)===end.slice(0,10)?`${start.slice(0,10)} · ${start.slice(11,16)}–${end.slice(11,16)}`:`${start.slice(0,10)} ${start.slice(11,16)} – ${end.slice(0,10)} ${end.slice(11,16)}`):`${start.slice(0,10)} · ${start.slice(11,16)}–…`;
  view.append(el('p',`${range} · ${tr('durationCompact',language,{hours:Math.floor(minutes/60),minutes:minutes%60})}`),el('p',`${tr(record.status,language)} · ${tr(record.source==='manual'?'manual_source':record.source,language)} · ${record.timezone}`,{class:'muted record-context'}));
  if(record.note)view.append(el('p',record.note));
  if(cost.issue)view.append(el('p',tr(cost.issue==='energyMissing'&&(record.quality||[]).includes('reset')?'energyMissingReset':cost.issue,language),{class:'record-issue'}));
  else if(record.end_reason==='source_unavailable')view.append(el('p',tr('ended_source_unavailable',language),{class:'record-issue'}));
  return view;
}
export function billingDetails(detail,language,currency){
  const {record}=detail,section=el('details',null,{class:'record-section'}),body=el('div',null,{class:'billing-details stack'});
  section.append(el('summary',tr('feeDetails',language)),body);
  const manual=(record.manual_fee_override||record.manual_override)&&Object.hasOwn(record,'manual_cost');
  if(manual)body.append(el('p',record.manual_cost==null?tr('manualAmountMissing',language):`${tr('manualAmount',language)}: ${recordCostState(record,currency,language).value}`));
  if(record.manual_override){
    body.append(el('p',tr('manualEnergyExplanation',language)));
    if(manual)return section;
  }
  const missing=(record.quality_spans||[]).filter(span=>span.quality.includes('missing_energy'));
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
  const explanations=[];
  if(!record.manual_override&&(record.quality||[]).some(flag=>['estimated','unavailable'].includes(flag)))explanations.push(tr('samplingExplanation',language));
  if((record.quality||[]).some(flag=>['missing_price','price_unknown'].includes(flag))&&!manual)explanations.push(tr('priceMissing',language));
  if(record.end_reason==='source_unavailable'&&recordCostState(record,currency,language).issue)explanations.push(tr('ended_source_unavailable',language));
  const rounded=(value,digits)=>{const text=formatDecimal(value,'en',digits,digits).replace(/[,.]/g,'');return /^-?\d+$/.test(text)?BigInt(text):null;};
  if(periods.length&&[['energy_kwh',3],...(!manual&&periods.every(part=>part.cost!=null)?[['cost',2]]:[])].some(([key,digits])=>{
    const values=[record[key==='cost'?'known_cost':key],...periods.map(part=>part[key])].map(value=>rounded(value,digits));
    return values.every(value=>value!==null)&&values.slice(1).reduce((sum,value)=>sum+value,0n)!==values[0];
  }))explanations.push(tr('roundingExplanation',language));
  if(explanations.length)body.append(el('p',explanations.join(' '),{class:'quality'}));
  return section;
}
export function segmentTable(segments,language,currency,timezone="UTC"){
  const wrap=el('div',null,{class:'table-wrap'}),table=el('table'),head=el('tr');
  for(const label of ['from','energy','cost','quality'])head.append(el('th',tr(label,language),{scope:'col'}));table.append(head);
  for(const segment of segments||[]){const row=el('tr');for(const text of [`${dateText(segment.start,timezone)} → ${dateText(segment.end,timezone)} (${timezone})`,`${formatDecimal(segment.energy_kwh,language)} kWh`,segment.cost==null?tr('pending',language):formatCost({known_cost:segment.cost,cost_complete:true},currency,language),quality(segment.quality,language,{kind:'segment',cost_basis:segment.cost_basis})])row.append(el('td',text));table.append(row);}wrap.append(table);return wrap;
}
