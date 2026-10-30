import {SelectControl} from './card-controls.js?v=0.1.2-12';
import {el,field} from './card-ui.js?v=0.1.2-12';
import {formatDecimal,formatCost} from './card-state.js?v=0.1.2-12';
import {tr} from './card-i18n.js?v=0.1.2-12';

export function chartGeometry(values,{width=600,height=144,padding=12}={}){
  const low=Math.min(0,...values),high=Math.max(0,...values);
  if(high===low)return {baseline:height-padding,bars:[]};
  const y=value=>padding+(high-value)/(high-low)*(height-2*padding),baseline=y(0),slot=(width-2*padding)/values.length;
  return {baseline,bars:values.map((value,index)=>({x:padding+index*slot+slot*.14,y:Math.min(y(value),baseline),width:slot*.72,height:Math.abs(y(value)-baseline)}))};
}
export function chartState(summary,metric){
  if(!summary.matched_count)return 'no_records';
  if(!summary.has_energy_data)return 'awaiting_energy';
  if(metric==='known_cost'&&!summary.has_known_cost)return 'unknown_cost';
  return summary.buckets.some(bucket=>bucket[metric]!=null&&Number(bucket[metric])!==0)?'ready':'zero';
}
const svgNode=(tag,attrs={})=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,value);return node;};
export class ChartView{
  constructor({onMetricChange}){
    this.node=el('div',null,{class:'stack'});this.metric=new SelectControl({onChange:onMetricChange});this.metric.label=field('',this.metric.node);
    this.hint=el('small');this.message=el('p',null,{role:'status'});this.plot=el('div');this.incomplete=el('p',null,{class:'quality'});
    this.details=el('details');this.toggle=el('summary');this.scroll=el('div',null,{class:'table-wrap'});this.details.append(this.toggle,this.scroll);
    this.node.append(this.metric.label,this.hint,this.message,this.plot,this.incomplete,this.details);
  }
  update({summary,metric,language,currency}){
    const key=JSON.stringify([summary,metric,language,currency]);if(this.key===key)return;this.key=key;
    const t=key=>tr(key,language),buckets=summary.buckets||[],state=chartState(summary,metric);
    this.metric.label.firstChild.textContent=t('chartMetric');this.metric.update({options:[{id:'energy_kwh',name:t('energy')},{id:'known_cost',name:t('cost')}],value:metric});
    this.hint.textContent=t('group_'+summary.bucket_period);this.toggle.textContent=t('chartData');
    this.message.hidden=state==='ready';this.message.textContent=t('chart_'+state);this.plot.hidden=state!=='ready';this.plot.replaceChildren();
    this.incomplete.hidden=metric!=='known_cost'||summary.cost_complete;this.incomplete.textContent=t('chartIncomplete');
    const value=b=>metric==='energy_kwh'?`${formatDecimal(b.energy_kwh,language)} kWh`:b.has_known_cost?formatCost(b,currency,language):t('chart_unknown_cost');
    if(state==='ready'){
      // Decimal strings remain untouched; only geometry uses Number values.
      const valid=buckets.filter(b=>b[metric]!=null&&(metric==='energy_kwh'?b.has_energy_data:b.has_known_cost)&&Number.isFinite(Number(b[metric]))),geometry=chartGeometry(valid.map(b=>Number(b[metric])));
      const svg=svgNode('svg',{viewBox:'0 0 600 144',class:'chart',role:'img','aria-label':t(metric==='energy_kwh'?'energy':'cost'),preserveAspectRatio:'none'});
      svg.append(svgNode('line',{x1:12,x2:588,y1:geometry.baseline,y2:geometry.baseline}));
      valid.forEach((bucket,index)=>{const rect=svgNode('rect',{...geometry.bars[index],role:'img','aria-label':`${bucket.label}: ${value(bucket)}`}),title=svgNode('title');title.textContent=rect.getAttribute('aria-label');rect.append(title);svg.append(rect);});
      const axis=el('div',null,{class:'chart-axis'});for(const b of valid.length<=2?valid:[valid[0],valid.at(-1)])axis.append(el('span',b.label));this.plot.append(svg,axis);
    }
    const table=el('table'),head=el('tr');for(const key of ['from','energy','cost'])head.append(el('th',t(key),{scope:'col'}));table.append(head);
    for(const bucket of buckets){const row=el('tr');for(const text of [bucket.label,bucket.has_energy_data?formatDecimal(bucket.energy_kwh,language)+' kWh':t('chart_awaiting_energy'),bucket.has_known_cost?formatCost(bucket,currency,language):t('chart_unknown_cost')])row.append(el('td',text));table.append(row);}this.scroll.replaceChildren(table);
  }
  dispose(){this.metric.dispose();}
}
