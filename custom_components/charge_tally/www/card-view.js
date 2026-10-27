import {exportErrorMessage} from './card-export.js?v=0.1.2-8';
import {ChartView} from './card-chart.js?v=0.1.2-8';
import {SelectControl} from './card-controls.js?v=0.1.2-8';
import {el,button,field,input,summaryView,quality,dateText} from './card-ui.js?v=0.1.2-8';
import {formatDecimal,formatCost,errorMessage} from './card-state.js?v=0.1.2-8';

const text=(node,value)=>{if(node.textContent!==String(value))node.textContent=value;};
const label=(control,value)=>text(control.label.firstChild,value);
function selector(onChange){const control=new SelectControl({onChange});control.label=field('',control.node);return control;}
export class CardView {
  constructor(card){
    this.card=card;this.selects=[];this.points=new Map();this.records=new Map();this.sections={};
    const header=el('div',null,{class:'row spread'}),heading=el('div');this.title=el('h2');this.status=el('span',null,{class:'badge',role:'status'});heading.append(el('p','CHARGE TALLY',{class:'eyebrow'}),this.title);header.append(heading,this.status);
    this.error=el('p',null,{class:'alert',role:'alert'});this.notice=el('p',null,{class:'alert success',role:'status'});this.retry=button('',()=>card.subscription.start());this.empty=el('p',null,{class:'alert'});
    card.body.append(header,this.error,this.notice,this.retry,this.empty);
    for(const id of ['controls','statistics','records']){
      const node=el('section',null,{'data-section':id}),toggle=button('',()=>card.setExpanded(id,!card.expanded[id]),false,'section-toggle'),body=el('div',null,{class:'section-body stack'});
      toggle.setAttribute('aria-controls',id);body.id=id;node.append(toggle,body);card.body.append(node);this.sections[id]={node,toggle,body};
    }
    this.pointFilter=this.select(value=>card.setFilter('point_id',value));this.identityFilter=this.select(value=>card.setFilter('identity_id',value));const filters=el('div',null,{class:'grid'});filters.append(this.pointFilter.label,this.identityFilter.label);this.live=el('div');this.sections.controls.body.append(filters,this.live);
    this.period=this.select(value=>card.setPeriod(value));this.refresh=button('',()=>{card.summaryDirty=true;card.recordsDirty=true;card.refresh(true);});
    this.from=input('date');this.to=input('date');this.from.addEventListener('input',()=>{card.rangeStart=this.from.value;});this.to.addEventListener('input',()=>{card.rangeEnd=this.to.value;});this.fromLabel=field('',this.from);this.toLabel=field('',this.to);this.range=el('div',null,{class:'stack'});const dates=el('div',null,{class:'grid'});dates.append(this.fromLabel,this.toLabel);this.rangeHint=el('small');this.apply=button('',()=>card.applyRange());this.range.append(dates,this.rangeHint,this.apply);
    this.export=button('',()=>card.exportPdf());this.export.setAttribute('data-export-pdf','');this.exportError=el('p',null,{class:'alert',role:'alert'});this.statisticsActions=el('div',null,{class:'row'});this.statisticsActions.append(this.refresh,this.export);
    this.scope=el('small');this.summary=el('div');this.chartView=new ChartView({onMetricChange:value=>{card.chartMetric=value;this.updateChart();}});this.chart=this.chartView.node;this.metric=this.chartView.metric;this.sections.statistics.body.append(this.statisticsActions,this.exportError,this.period.label,this.range,this.scope,this.summary,this.chart);
    this.add=button('',()=>card.openDialog('create'));this.historyHint=el('small');this.loading=el('p',null,{role:'status'});this.list=el('ul',null,{class:'records'});this.noRecords=el('p');this.pager=el('div',null,{class:'row spread'});this.previous=button('',()=>card.setOffset(Math.max(0,card.offset-25)));this.next=button('',()=>card.setOffset(card.offset+25));this.pageText=el('small');this.pager.append(this.previous,this.pageText,this.next);this.sections.records.body.append(this.add,this.historyHint,this.loading,this.list,this.noRecords,this.pager);
  }
  select(onChange){const control=selector(onChange);this.selects.push(control);return control;}
  setExpanded(id,expanded){const section=this.sections[id];section.toggle.setAttribute('aria-expanded',String(expanded));section.body.hidden=!expanded;}
  update(){
    const c=this.card,s=c.snapshot,t=key=>c.t(key),online=!!s&&c._hass?.connection?.connected!==false;
    text(this.title,c.config.title||'Charge Tally');text(this.status,t(online?'connected':'offline'));this.error.hidden=!c.error;text(this.error,c.error?errorMessage(c.error,c.language):'');this.notice.hidden=!c.notice||!!c.error;text(this.notice,t('saved'));this.retry.hidden=online;this.retry.disabled=!c._hass?.connection||c._hass.connection.connected===false;text(this.retry,t('retry'));this.empty.hidden=!s||!!s.points.length||!!s.archived_points.length;text(this.empty,t('noPoints'));
    for(const [id,key]of [['controls','controls'],['statistics','statistics'],['records','history']]){text(this.sections[id].toggle,t(key));this.sections[id].node.hidden=id==='records'&&c.config.show_records===false;this.setExpanded(id,c.expanded[id]);}
    const points=[...(s?.points||[]),...(s?.archived_points||[])],identities=s?.identities||[];
    const options=items=>[{id:'',name:t('all')},...items.map(i=>({id:i.id,name:i.name+(i.active===false?` (${t('archived')})`:'' )}))];
    const po=options(points);if(c.filters.point_id&&!points.some(p=>p.id===c.filters.point_id))po.push({id:c.filters.point_id,name:t('invalidPoint')});
    this.pointFilter.update({options:po,value:c.filters.point_id,disabled:!online});label(this.pointFilter,t('point'));this.identityFilter.update({options:options(identities),value:c.filters.identity_id,disabled:!online});label(this.identityFilter,t('identity'));
    const ids=new Set();for(const point of s?.points||[]){if(c.filters.point_id&&c.filters.point_id!==point.id)continue;ids.add(point.id);let view=this.points.get(point.id);if(!view){view=this.createPoint(point.id);this.points.set(point.id,view);this.live.append(view.node);}this.updatePoint(view,point,online);}
    for(const [id,view]of this.points)if(!ids.has(id)){view.select.dispose();view.node.remove();this.points.delete(id);}
    this.period.update({options:['daily','monthly','yearly','total','custom'].map(id=>({id,name:t(id)})),value:c.period,disabled:!online});label(this.period,t('period'));text(this.refresh,t('refresh'));this.refresh.disabled=!online;this.range.hidden=c.period!=='custom';text(this.fromLabel.firstChild,t('from'));text(this.toLabel.firstChild,t('to'));text(this.rangeHint,`${s?.timezone||''} · ${t('rangeHint')}`);text(this.apply,t('apply'));this.apply.disabled=!online;this.from.disabled=!online;this.to.disabled=!online;text(this.scope,t('scope'));
    text(this.export,t(c.exportBusy?'exportingPdf':'exportPdf'));this.export.disabled=!!c.exportBusy||!c.canExport();this.exportError.hidden=!c.exportError;text(this.exportError,c.exportError?exportErrorMessage(c.exportError,c.language):'');
    if(c.summary&&s)this.summary.replaceChildren(summaryView(c.summary,s.currency,c.language),el('p',`${t('count')}: ${c.summary.active_count??'—'} / ${c.summary.completed_count??'—'}`,{class:'muted'}),...(c.summary.quality?.length?[el('p',quality(c.summary.quality,c.language),{class:'quality'})]:[]));else text(this.summary,t(online?'loading':'offline'));
    this.updateChart();this.updateRecords(online);
  }
  createPoint(id){
    const c=this.card,node=el('article',null,{class:'point','data-point-id':id}),head=el('div',null,{class:'row spread'}),name=el('h3'),status=el('span',null,{class:'badge'});head.append(name,status);
    const detection=el('p',null,{class:'muted'}),candidate=el('p'),hint=el('small'),measurements=el('div',null,{class:'row muted'}),message=el('p',null,{class:'quality'}),select=selector(value=>c.selectIdentity(id,value)),summary=el('div',null,{class:'spaced stack'}),actions=el('div',null,{class:'row spaced'});
    const current=()=>c.snapshot?.points.find(p=>p.id===id);
    const details=button('',()=>{const p=current();if(p?.active_record)c.details(p.active_record);}),reassign=button('',()=>{const p=current();if(p?.active_record)c.openDialog('reassign',{record:p.active_record});}),live=button('',()=>{const p=current();if(p)c.live(p.active_record?'end':'start',p);},false,'primary');actions.append(details,reassign,live);node.append(head,detection,measurements,message,candidate,hint,select.label,summary,actions);return {node,name,status,detection,candidate,hint,measurements,message,select,summary,details,reassign,live};
  }
  updatePoint(v,p,online){
    const c=this.card,t=key=>c.t(key),active=p.active_record;
    const recording=p.recording_state??(active?(active.source==='automatic'?'automatic':'manual'):'idle');
    const detection=p.detection_state??(!p.detection_enabled?'disabled':recording==='manual'?'paused_manual':p.status==='idle'?'waiting':p.status);
    const detectionKey={disabled:'detectionDisabled',waiting:'detectionWaiting',paused_manual:'detectionPausedManual',blocked:'detectionBlocked',unavailable:'detectionUnavailable',charging:'detectionCharging',pending_start:'pending_start',pending_end:'pending_end'}[detection]||'detectionUnavailable';
    text(v.name,p.name);text(v.status,t({idle:'recordingIdle',manual:'recordingManual',automatic:'recordingAutomatic'}[recording]||'recordingIdle'));
    text(v.detection,`${t('detector')}: ${t(detectionKey)}`);
    const pending=detection==='pending_start';v.candidate.hidden=!pending;text(v.candidate,pending?`${t('candidateIdentity')}: ${c.identityName(p.candidate_identity_id)}`:'');
    v.hint.hidden=recording!=='manual'&&!pending;text(v.hint,recording==='manual'?t('manualEndRequired'):pending?t('candidateHint'):'');text(v.measurements,`${t('power')}: ${formatDecimal(p.power_w,c.language)} W · ${t('price')}: ${formatDecimal(p.current_price,c.language,4)} ${c.snapshot.currency}/kWh`);text(v.message,[p.error,quality(p.quality,c.language)].filter(Boolean).join(' · '));v.message.hidden=!v.message.textContent;
    const selected=c.pendingSelections.get(p.id)?.identityId??p.selected_identity_id;
    v.select.update({options:c.snapshot.identities.filter(i=>i.active!==false),value:selected,disabled:!online||!!c.busy||!c.canSelect(p)||!!c.pendingSelections.get(p.id)});label(v.select,t(pending?'nextManualIdentity':active?'next':'selected'));
    if(active)v.summary.replaceChildren(el('strong',`${t('current')}: ${c.identityName(active.identity_id)}`),summaryView(active,c.snapshot.currency,c.language),el('small',`${t('began')}: ${dateText(active.start,active.timezone)} (${active.timezone}) · ${t('duration')}: ${Math.max(0,Math.floor((Date.now()-Date.parse(active.start))/60000))} min`));else text(v.summary,'');
    v.details.hidden=v.reassign.hidden=!active;text(v.details,t('details'));text(v.reassign,t('reassign'));text(v.live,t(active?(recording==='manual'?'end':detection==='pending_end'?'endNow':'endAutomatic'):pending?'startNow':'startManual'));v.details.disabled=v.reassign.disabled=!online||!!c.busy;v.live.disabled=!online||!!c.busy||!p.identity_entity_id||(!active&&(!p.available||c.pendingSelections.has(p.id)));
  }
  updateChart(){
    const c=this.card;this.chart.hidden=c.config.show_chart===false||!c.summary;
    if(c.summary&&c.snapshot)this.chartView.update({summary:c.summary,metric:c.chartMetric||'energy_kwh',language:c.language,currency:c.snapshot.currency});
  }

  updateRecords(online){
    const c=this.card,t=key=>c.t(key);text(this.add,t('add'));this.add.disabled=!online||!!c.busy;text(this.historyHint,t('historyHint'));text(this.loading,t(online?'loading':'offline'));this.loading.hidden=!!c.page;this.pager.hidden=!c.page;this.noRecords.hidden=!c.page||!!c.page.records.length;text(this.noRecords,t('empty'));
    const ids=new Set();for(const record of c.page?.records||[]){ids.add(record.id);let v=this.records.get(record.id);if(!v){const node=el('li',null,{class:'row','data-record-id':record.id}),open=button('',()=>{const current=c.page?.records.find(r=>r.id===record.id);if(current)c.details(current);},false,'record-open');node.append(open);v={node,open};this.records.set(record.id,v);this.list.append(node);}v.open.replaceChildren(el('strong',`${c.pointName(record.point_id)} · ${c.identityName(record.identity_id)}`),el('small',`${dateText(record.start,record.timezone)} · ${t(record.status)}`),el('span',`${formatDecimal(record.energy_kwh,c.language)} kWh · ${formatCost(record,c.snapshot.currency,c.language)}`),...(record.quality?.length?[el('small',quality(record.quality,c.language))]:[]));}
    for(const [id,v]of this.records)if(!ids.has(id)){v.node.remove();this.records.delete(id);}
    const focused=c.shadowRoot.activeElement;
    (c.page?.records||[]).forEach((record,index)=>{const node=this.records.get(record.id).node;if(this.list.children[index]!==node)this.list.insertBefore(node,this.list.children[index]||null);});
    if(focused&&this.list.contains(focused)&&c.shadowRoot.activeElement!==focused)focused.focus({preventScroll:true});
    text(this.previous,t('previous'));text(this.next,t('nextPage'));this.previous.disabled=!online||c.offset===0;this.next.disabled=!online||!c.page||c.offset+c.page.limit>=c.page.total;if(c.page)text(this.pageText,`${c.page.total?c.offset+1:0}–${c.offset+c.page.records.length} / ${c.page.total}`);
  }
  dispose(){this.chartView.dispose();for(const select of this.selects)select.dispose();for(const point of this.points.values())point.select.dispose();}
}
