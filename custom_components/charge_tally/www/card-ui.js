import {formatCost,formatDecimal,localInput} from './card-state.js?v=0.1.2-8';
import {tr} from './card-i18n.js?v=0.1.2-8';
import {SelectControl} from './card-controls.js?v=0.1.2-8';

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
export function segmentTable(segments,language,currency,timezone="UTC"){
  const wrap=el('div',null,{class:'table-wrap'}),table=el('table'),head=el('tr');
  for(const label of ['from','energy','cost','quality'])head.append(el('th',tr(label,language),{scope:'col'}));table.append(head);
  for(const segment of segments||[]){const row=el('tr');for(const text of [`${dateText(segment.start,timezone)} → ${dateText(segment.end,timezone)} (${timezone})`,`${formatDecimal(segment.energy_kwh,language)} kWh`,segment.cost==null?tr('pending',language):formatCost({known_cost:segment.cost,cost_complete:true},currency,language),quality(segment.quality,language,{kind:'segment',cost_basis:segment.cost_basis})])row.append(el('td',text));table.append(row);}wrap.append(table);return wrap;
}
