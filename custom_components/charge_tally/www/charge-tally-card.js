import {tr} from './card-i18n.js?v=0.1.1';
import {styles} from './card-styles.js?v=0.1.1';
import {Latest,Subscription,formatCost,formatDecimal,errorMessage,resolveLocal,queryRequest,recordsRequest,liveRequest,identityRequest} from './card-state.js?v=0.1.1';
import {el,button,field,select,input,metric,summaryView,quality,dateText} from './card-ui.js?v=0.1.1';
import {RecordDialog} from './card-dialog.js?v=0.1.1';
import './card-editor.js?v=0.1.1';

export class ChargeTallyCard extends HTMLElement {
  static getConfigElement(){return document.createElement('charge-tally-card-editor');}
  static getStubConfig(){return {type:'custom:charge-tally-card',show_records:true,show_chart:true};}
  constructor(){
    super();this.attachShadow({mode:'open'});this.body=el('ha-card');this.shadowRoot.append(el('style',styles),this.body);
    this.config={};this.filters={};this.period='daily';this.offset=0;this.latest=new Latest();this.actions=new Latest();this.dialogEpoch=0;this.pendingLive=null;
    this.subscription=new Subscription(snapshot=>this.onSnapshot(snapshot),error=>{this.error=error;this.render();});
  }
  setConfig(config){
    if(!config||typeof config!=='object')throw new Error(this.t('error.configInvalid'));
    for(const key of ['point_id','identity_id','title'])if(config[key]!=null&&typeof config[key]!=='string')throw new Error(tr('error.configString',this.language,{field:key}));
    for(const key of ['show_records','show_chart'])if(config[key]!=null&&typeof config[key]!=='boolean')throw new Error(tr('error.configBoolean',this.language,{field:key}));
    this.config={...config};this.filters={point_id:config.point_id||'',identity_id:config.identity_id||''};this.offset=0;this.latest.invalidate();this.render();if(this.snapshot)this.refresh();
  }
  set hass(hass){
    this._hass=hass;const language=hass.language||'en';
    if(language!==this.language){
      this.language=language;this.render();this.dialog?.setLanguage(language);
      const metadata=window.customCards?.find(card=>card.type==='charge-tally-card');
      if(metadata)metadata.description=this.t('cardDescription');
    }
    if(this.isConnected)this.subscription.connect(hass.connection);
  }
  getCardSize(){return this.config.show_records===false?6:10;}
  connectedCallback(){if(this._hass)this.subscription.connect(this._hass.connection);}
  disconnectedCallback(){this.dialogEpoch++;this.subscription.disconnect();this.latest.invalidate();this.actions.invalidate();this.dialog?.close();}
  t(key){return tr(key,this.language||'en');}
  onSnapshot(snapshot){
    this.snapshot=snapshot;this.error=null;this.latest.invalidate();this.summary=null;this.page=null;
    if(!snapshot){this.dialogEpoch++;this.actions.invalidate();this.busy=false;this.notice=null;this.dialog?.close();}
    this.render();if(snapshot)this.refresh();
  }
  call(request){if(!this.snapshot||this._hass.connection.connected===false)throw Object.assign(new Error('unavailable'),{code:'unavailable'});return this._hass.callWS(request);}
  pointName(id){return [...(this.snapshot?.points||[]),...(this.snapshot?.archived_points||[])].find(p=>p.id===id)?.name||id;}
  identityName(id){return this.snapshot?.identities.find(i=>i.id===id)?.name||id;}
  setFilter(key,value){this.filters[key]=value;this.offset=0;this.latest.invalidate();this.summary=null;this.page=null;this.render();this.refresh();}
  range(){
    if(this.period==='custom')return {start:resolveLocal(this.rangeStart+'T00:00',this.snapshot.timezone),end:resolveLocal(this.rangeEnd+'T00:00',this.snapshot.timezone)};
    return {calendar_period:this.period};
  }
  refresh(newLiveIntent=false){
    if(newLiveIntent)this.pendingLive=null;
    if(!this.snapshot)return;this.error=null;
    let request;
    try{
      if(this.period==='total'){
        request={type:'charge_tally/snapshot',...(this.filters.point_id?{point_id:this.filters.point_id}:{})};
        this.latest.run('summary',()=>this.call(request),snapshot=>{this.summary=this.filters.identity_id?snapshot.identities.find(i=>i.id===this.filters.identity_id)?.summaries?.total:snapshot.summary;this.render();},error=>{this.error=error;this.render();});
      }else{
        request=queryRequest(this.filters,this.range());
        this.latest.run('summary',()=>this.call(request),summary=>{this.summary=summary;this.render();},error=>{this.error=error;this.render();});
      }
    }catch(error){this.error=error;this.render();}
    if(this.config.show_records!==false)this.latest.run('records',()=>this.call(recordsRequest(this.filters,this.offset)),page=>{this.page=page;this.render();},error=>{this.error=error;this.render();});
  }
  mutate(request){
    if(this.busy)return;this.busy=true;this.error=null;this.render();
    this.actions.run('write',()=>this.call(request),result=>{
      // HA call_service wraps the business record in result.response.
      if(this.pendingLive?.request===request)this.pendingLive=null;
      this.lastRecord=request.return_response?result.response:result;this.busy=false;this.notice=this.t('saved');this.refresh();this.render();
    },error=>{this.busy=false;this.error=error;this.render();});
  }
  live(service,point){
    if(this.busy)return;
    try{
      const intent=JSON.stringify([service,point.id,service==='end'?point.active_record?.id:point.selected_identity_id]);
      if(this.pendingLive?.intent!==intent)this.pendingLive={intent,request:liveRequest(service,point,crypto.randomUUID())};
      this.mutate(this.pendingLive.request);
    }catch(error){this.error=error;this.render();}
  }
  openDialog(mode,detail){
    this.dialogEpoch++;
    if(!this.snapshot)return;this.dialog?.close();
    this.dialog=new RecordDialog(this.shadowRoot,{mode,detail,record:detail?.record,language:this.language,currency:this.snapshot.currency,timezone:this.snapshot.timezone,points:[...this.snapshot.points,...this.snapshot.archived_points],identities:this.snapshot.identities,defaultPoint:this.filters.point_id,defaultIdentity:this.filters.identity_id,
      call:request=>this.call(request),pointName:id=>this.pointName(id),identityName:id=>this.identityName(id),onSaved:()=>{this.notice=this.t('saved');this.refresh();},onClose:()=>{this.dialogEpoch++;this.dialog=null;}});
  }
  details(record){
    const epoch=++this.dialogEpoch;
    return this.latest.run('detail',()=>this.call({type:'charge_tally/records',record_id:record.id}),
      detail=>{if(epoch===this.dialogEpoch)this.openDialog('details',detail);},
      error=>{if(epoch===this.dialogEpoch){this.error=error;this.render();}});
  }
  render(){
    if(!this.body)return;const card=this.body;card.replaceChildren();
    const header=el('div',null,{class:'row spread'}),heading=el('div');heading.append(el('p','CHARGE TALLY',{class:'eyebrow'}),el('h2',this.config.title||'Charge Tally'));
    header.append(heading,el('span',this.t(this.snapshot?'connected':'offline'),{class:'badge',role:'status'}));card.append(header);
    if(this.error)card.append(el('p',errorMessage(this.error,this.language),{class:'alert',role:'alert'}));
    if(this.notice&&!this.error)card.append(el('p',this.t('saved'),{class:'alert success',role:'status'}));
    if(!this.snapshot){card.append(button(this.t('retry'),()=>this.subscription.start(),!this._hass?.connection||this._hass.connection.connected===false));return;}
    const points=[...this.snapshot.points,...this.snapshot.archived_points];
    if(!points.length){card.append(el('p',this.t('noPoints'),{class:'alert'}));return;}
    const pointOptions=[{id:'',name:this.t('all')},...points.map(p=>({...p,name:p.name+(p.active===false?` (${this.t('archived')})`:'')}))];
    if(this.filters.point_id&&!points.some(p=>p.id===this.filters.point_id))pointOptions.push({id:this.filters.point_id,name:this.t('invalidPoint')});
    const identityOptions=[{id:'',name:this.t('all')},...this.snapshot.identities.map(i=>({...i,name:i.name+(i.active===false?` (${this.t('archived')})`:'')}))];
    const filter=el('section',null,{class:'grid'});filter.append(field(this.t('point'),select(pointOptions,this.filters.point_id,value=>this.setFilter('point_id',value))),field(this.t('identity'),select(identityOptions,this.filters.identity_id,value=>this.setFilter('identity_id',value))));card.append(filter);
    const live=el('section');for(const point of this.snapshot.points.filter(p=>!this.filters.point_id||this.filters.point_id===p.id))live.append(this.renderPoint(point));card.append(live);
    card.append(this.renderStatistics());if(this.config.show_records!==false)card.append(this.renderHistory());
  }
  renderPoint(point){
    const node=el('article',null,{class:'point'}),head=el('div',null,{class:'row spread'});head.append(el('h3',point.name),el('span',tr(point.status,this.language),{class:'badge'}));node.append(head);
    const measurements=el('div',null,{class:'row muted'});measurements.append(el('span',`${this.t('power')}: ${formatDecimal(point.power_w,this.language)} W`),el('span',`${this.t('price')}: ${formatDecimal(point.current_price,this.language,4)} ${this.snapshot.currency}/kWh`),el('span',`${this.t('detector')}: ${this.t(point.detection_enabled?'enabled':'disabled')}`));node.append(measurements);
    if(point.error||point.quality?.length)node.append(el('p',[point.error,quality(point.quality,this.language)].filter(Boolean).join(' · '),{class:'quality spaced'}));
    const active=point.active_record,controls=el('div',null,{class:'grid spaced'});
    if(active)controls.append(metric(this.t('current'),this.identityName(active.identity_id)));
    const options=this.snapshot.identities.filter(i=>i.active!==false),next=select(options,point.selected_identity_id,value=>{const identity=options.find(i=>i.id===value);try{this.mutate(identityRequest(point,identity));}catch(error){this.error=error;this.render();}});
    next.disabled=this.busy||!point.identity_entity_id||point.active===false||['unknown','unavailable'].includes(this._hass.states?.[point.identity_entity_id]?.state);
    controls.append(field(this.t(active?'next':'selected'),next));node.append(controls);
    if(active){const summary=el('div',null,{class:'spaced stack'});summary.append(el('strong',this.t('active')),summaryView(active,this.snapshot.currency,this.language),el('small',`${this.t('began')}: ${dateText(active.start,active.timezone)} (${active.timezone}) · ${this.t('duration')}: ${Math.max(0,Math.floor((Date.now()-Date.parse(active.start))/60000))} min`),el('small',quality(active.quality,this.language)));node.append(summary);}
    else node.append(el('p',this.t('idle'),{class:'muted spaced'}));
    const actions=el('div',null,{class:'row spaced'});
    if(active)actions.append(button(this.t('details'),()=>this.details(active),this.busy),button(this.t('reassign'),()=>this.openDialog('reassign',{record:active}),this.busy||!point.identity_entity_id));
    actions.append(button(this.t(active?'end':'start'),()=>this.live(active?'end':'start',point),this.busy||!point.identity_entity_id||(!active&&!point.available),'primary'));node.append(actions);return node;
  }
  renderStatistics(){
    const node=el('section',null,{class:'stack summary'}),header=el('div',null,{class:'row spread'});header.append(el('h3',this.t('statistics')),button(this.t('refresh'),()=>{this.latest.invalidate();this.refresh(true);}));node.append(header);
    node.append(field(this.t('period'),select(['daily','monthly','yearly','total','custom'].map(id=>({id,name:this.t(id)})),this.period,value=>{this.period=value;this.summary=null;this.latest.invalidate();this.render();if(value!=='custom'||this.rangeStart&&this.rangeEnd)this.refresh();})));
    if(this.period==='custom'){
      const range=el('div',null,{class:'grid'}),from=input('date',this.rangeStart||''),to=input('date',this.rangeEnd||'');from.addEventListener('input',()=>{this.rangeStart=from.value;});to.addEventListener('input',()=>{this.rangeEnd=to.value;});range.append(field(this.t('from'),from),field(this.t('to'),to));node.append(range,el('small',`${this.snapshot.timezone} · ${this.t('rangeHint')}`),button(this.t('apply'),()=>{this.summary=null;this.latest.invalidate();this.refresh();}));
    }
    node.append(el('small',this.t('scope')));
    if(this.summary){node.append(summaryView(this.summary,this.snapshot.currency,this.language),el('p',`${this.t('count')}: ${this.summary.active_count??'—'} / ${this.summary.completed_count??'—'}`,{class:'muted'}),el('p',quality(this.summary.quality,this.language),{class:'quality'}));if(this.config.show_chart!==false)node.append(this.renderChart(this.summary.buckets||[]));}
    else node.append(el('p',this.t('loading'),{role:'status'}));return node;
  }
  renderChart(buckets){
    const wrap=el('div',null,{class:'stack'});wrap.append(field(this.t('chartMetric'),select([{id:'energy_kwh',name:this.t('energy')},{id:'known_cost',name:this.t('cost')}],this.chartMetric||'energy_kwh',value=>{this.chartMetric=value;this.render();})));
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 600 160');svg.setAttribute('class','chart');svg.setAttribute('role','img');svg.setAttribute('aria-label',this.t('statistics'));
    const key=this.chartMetric||'energy_kwh';
    // Number conversion is limited to chart geometry; labels format server strings.
    const values=buckets.map(b=>Number(b[key])),max=Math.max(1,...values.filter(Number.isFinite).map(Math.abs));
    const baseline=document.createElementNS(ns,'line');for(const [k,v]of Object.entries({x1:0,x2:600,y1:90,y2:90}))baseline.setAttribute(k,v);svg.append(baseline);
    buckets.forEach((bucket,index)=>{const value=values[index];if(!Number.isFinite(value))return;const width=580/Math.max(1,buckets.length),height=Math.abs(value)/max*64,rect=document.createElementNS(ns,'rect');for(const [k,v]of Object.entries({x:10+index*width,y:value<0?90:90-height,width:Math.max(1,width*.72),height}))rect.setAttribute(k,v);const title=document.createElementNS(ns,'title');title.textContent=`${bucket.local_date}: ${key==='known_cost'?formatCost(bucket,this.snapshot.currency,this.language):formatDecimal(bucket.energy_kwh,this.language)+' kWh'}`;rect.append(title);svg.append(rect);});
    const axis=el('div',null,{class:'chart-axis'});
    const labels=buckets.length<=4?buckets:[buckets[0],buckets.at(-1)];
    for(const bucket of labels)if(bucket)axis.append(el('span',bucket.local_date));
    wrap.append(svg,axis);const details=el('details');details.append(el('summary',this.t('details')));const table=el('table'),head=el('tr');for(const key of ['from','energy','cost'])head.append(el('th',this.t(key),{scope:'col'}));table.append(head);
    for(const bucket of buckets){const row=el('tr');for(const value of [bucket.local_date,formatDecimal(bucket.energy_kwh,this.language)+' kWh',formatCost(bucket,this.snapshot.currency,this.language)])row.append(el('td',value));table.append(row);}const scroll=el('div',null,{class:'table-wrap'});scroll.append(table);details.append(scroll);wrap.append(details);return wrap;
  }
  renderHistory(){
    const node=el('section'),heading=el('div',null,{class:'row spread'});heading.append(el('h3',this.t('history')),button(this.t('add'),()=>this.openDialog('create'),this.busy));node.append(heading,el('small',this.t('historyHint')));
    if(!this.page){node.append(el('p',this.t('loading'),{role:'status'}));return node;}
    const list=el('ul',null,{class:'records'});for(const record of this.page.records){const item=el('li',null,{class:'row'}),open=button('',()=>this.details(record),false,'record-open');open.append(el('strong',`${this.pointName(record.point_id)} · ${this.identityName(record.identity_id)}`),el('small',`${dateText(record.start,record.timezone)} · ${tr(record.status,this.language)}`),el('span',`${formatDecimal(record.energy_kwh,this.language)} kWh · ${formatCost(record,this.snapshot.currency,this.language)}`),el('small',quality(record.quality,this.language)));item.append(open);list.append(item);}node.append(list);if(!this.page.records.length)node.append(el('p',this.t('empty')));
    const pager=el('div',null,{class:'row spread'});pager.append(button(this.t('previous'),()=>{this.offset=Math.max(0,this.offset-25);this.page=null;this.refresh();this.render();},this.offset===0),el('small',`${this.page.total?this.offset+1:0}–${this.offset+this.page.records.length} / ${this.page.total}`),button(this.t('nextPage'),()=>{this.offset+=25;this.page=null;this.refresh();this.render();},this.offset+this.page.limit>=this.page.total));node.append(pager);return node;
  }
}
if(!customElements.get('charge-tally-card'))customElements.define('charge-tally-card',ChargeTallyCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(card=>card.type==='charge-tally-card'))window.customCards.push({type:'charge-tally-card',name:'Charge Tally',preview:true,description:tr('cardDescription',globalThis.navigator?.language)});
