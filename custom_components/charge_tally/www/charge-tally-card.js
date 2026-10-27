import {CardView} from './card-view.js?v=0.1.2-7';
import {newRequestId} from './request-id.js?v=0.1.2-7';
import {tr} from './card-i18n.js?v=0.1.2-7';
import {styles} from './card-styles.js?v=0.1.2-7';
import {Latest,Subscription,resolveLocal,queryRequest,recordsRequest,liveRequest,identityRequest} from './card-state.js?v=0.1.2-7';
import {el} from './card-ui.js?v=0.1.2-7';
import {RecordDialog} from './card-dialog.js?v=0.1.2-7';
import './card-editor.js?v=0.1.2-7';

export class ChargeTallyCard extends HTMLElement {
  static getConfigElement(){return document.createElement('charge-tally-card-editor');}
  static getStubConfig(){return {type:'custom:charge-tally-card',show_records:true,show_chart:true};}
  constructor(){
    super();this.attachShadow({mode:'open'});this.body=el('ha-card');this.shadowRoot.append(el('style',styles),this.body);
    this.config={};this.filters={};this.period='daily';this.offset=0;this.latest=new Latest();this.actions=new Latest();this.dialogEpoch=0;this.pendingLive=null;this.expanded={controls:true,statistics:false,records:false};this.summaryDirty=true;this.recordsDirty=true;this.queryVersion=0;this.pendingSelections=new Map();
    this.subscription=new Subscription(snapshot=>this.onSnapshot(snapshot),error=>{this.error=error;this.render();});
  }
  setConfig(config){
    if(!config||typeof config!=='object')throw new Error(this.t('error.configInvalid'));
    for(const key of ['point_id','identity_id','title'])if(config[key]!=null&&typeof config[key]!=='string')throw new Error(tr('error.configString',this.language,{field:key}));
    for(const key of ['show_records','show_chart'])if(config[key]!=null&&typeof config[key]!=='boolean')throw new Error(tr('error.configBoolean',this.language,{field:key}));
    this.config={...config};this.filters={point_id:config.point_id||'',identity_id:config.identity_id||''};this.offset=0;this.invalidateQueries();this.render();if(this.snapshot)this.refresh();
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
  connectedCallback(){if(!this.view)this.render();if(this._hass)this.subscription.connect(this._hass.connection);}
  disconnectedCallback(){this.dialogEpoch++;this.subscription.disconnect();this.latest.invalidate();this.actions.invalidate();this.dialog?.close();this.view?.dispose();this.body.replaceChildren();this.view=null;}
  t(key){return tr(key,this.language||'en');}
  onSnapshot(snapshot){
    this.snapshotVersion=(this.snapshotVersion||0)+1;
    if(!this.snapshot)this.error=null;this.snapshot=snapshot;this.summaryDirty=true;this.recordsDirty=true;
    // Keep loaded content during background refresh so the page does not collapse.
    if(!snapshot){this.latest.invalidate();this.queryVersion++;this.pendingSelections.clear();this.summary=null;this.page=null;this.dialogEpoch++;this.actions.invalidate();this.busy=false;this.notice=null;this.dialog?.close();}
    this.render();if(snapshot)this.refresh();
  }
  call(request){if(!this.snapshot||this._hass.connection.connected===false)throw Object.assign(new Error('unavailable'),{code:'unavailable'});return this._hass.callWS(request);}
  pointName(id){return [...(this.snapshot?.points||[]),...(this.snapshot?.archived_points||[])].find(p=>p.id===id)?.name||id;}
  identityName(id){return this.snapshot?.identities.find(i=>i.id===id)?.name||id;}
  invalidateQueries(){this.queryVersion++;this.latest.invalidate();this.summaryDirty=true;this.recordsDirty=true;this.summary=null;this.page=null;}
  setFilter(key,value){this.error=null;this.filters[key]=value;this.offset=0;this.invalidateQueries();this.render();this.refresh();}
  setPeriod(value){this.error=null;this.period=value;this.summaryVersion=(this.summaryVersion||0)+1;this.summaryDirty=true;this.summaryPending=false;this.summary=null;this.render();this.refresh();}
  applyRange(){
    try{
      const range={start:resolveLocal(this.rangeStart+'T00:00',this.snapshot.timezone),end:resolveLocal(this.rangeEnd+'T00:00',this.snapshot.timezone)};
      queryRequest(this.filters,range);
      this.appliedRange=range;
    }catch(error){this.error=error;this.render();return;}
    this.error=null;this.summaryVersion=(this.summaryVersion||0)+1;this.summaryDirty=true;this.summaryPending=false;this.summary=null;this.render();this.refresh();
  }
  setOffset(value){this.error=null;this.offset=value;this.recordsVersion=(this.recordsVersion||0)+1;this.recordsDirty=true;this.page=null;this.render();this.refresh();}
  setExpanded(id,value){if(!Object.hasOwn(this.expanded,id))return;this.expanded[id]=!!value;this.view?.setExpanded(id,!!value);if(value)this.refresh();}
  canSelect(point){return !!this.snapshot&&this._hass?.connection?.connected!==false&&!!point?.identity_entity_id&&point.active!==false&&point.available!==false&&!['unknown','unavailable'].includes(this._hass?.states?.[point.identity_entity_id]?.state);}
  selectIdentity(pointId,identityId){
    const point=this.snapshot?.points.find(p=>p.id===pointId),identity=this.snapshot?.identities.find(i=>i.id===identityId&&i.active!==false);
    if(!this.canSelect(point)||!identity||this.pendingSelections.has(pointId)){this.error={code:'unavailable'};this.render();return;}
    const pending={identityId};this.pendingSelections.set(pointId,pending);this.error=null;this.render();
    this.actions.run('identity:'+pointId,async()=>{
      await this.call(identityRequest(point,identity));
      if(this.pendingSelections.get(pointId)!==pending)return;
      if(this.snapshot?.points.find(p=>p.id===pointId)?.selected_identity_id===identityId)return this.snapshot;
      // Explicit reads have no stream generation. A later stream snapshot takes ownership.
      pending.readVersion=this.snapshotVersion;
      return await this.call({type:'charge_tally/snapshot'});
    },snapshot=>{
      if(this.pendingSelections.get(pointId)!==pending)return;
      this.pendingSelections.delete(pointId);
      const current=this.snapshot?.points.find(p=>p.id===pointId);
      const readIsCurrent=pending.readVersion===this.snapshotVersion;
      const confirmed=current?.selected_identity_id===identityId?current:readIsCurrent?snapshot?.points.find(p=>p.id===pointId):null;
      if(this.canSelect(current)&&this.snapshot.identities.some(i=>i.id===identityId&&i.active!==false)&&confirmed?.selected_identity_id===identityId){
        // Use the authoritative point, including any completed confirmation.
        this.snapshot={...this.snapshot,points:this.snapshot.points.map(p=>p.id===pointId?{...p,...confirmed}:p)};
        this.notice=this.t('saved');
      }else this.error={code:'selectionUnconfirmed'};
      this.render();
    },error=>{if(this.pendingSelections.get(pointId)===pending){this.pendingSelections.delete(pointId);this.error=error;this.render();}});
  }
  range(){
    if(this.period==='custom')return this.appliedRange;
    return {calendar_period:this.period};
  }
  refresh(newLiveIntent=false){
    if(newLiveIntent){this.pendingLive=null;this.error=null;}
    if(!this.snapshot)return;
    const version=this.queryVersion,summaryVersion=this.summaryVersion,recordsVersion=this.recordsVersion;
    if(this.expanded.statistics&&(this.period!=='custom'||this.appliedRange)&&(this.summaryDirty||!this.summary&&!this.summaryPending)){
      try{
        const request=queryRequest(this.filters,this.range());this.summaryDirty=false;this.summaryPending=true;
        this.latest.run('summary',()=>this.call(request),summary=>{if(version!==this.queryVersion||summaryVersion!==this.summaryVersion)return;this.summaryPending=false;this.summary=summary;this.render();},error=>{if(version!==this.queryVersion||summaryVersion!==this.summaryVersion)return;this.summaryPending=false;this.summaryDirty=true;this.error=error;this.render();});
      }catch(error){this.error=error;this.render();}
    }
    if(this.expanded.records&&this.config.show_records!==false&&(this.recordsDirty||!this.page&&!this.recordsPending)){
      this.recordsDirty=false;this.recordsPending=true;
      this.latest.run('records',()=>this.call(recordsRequest(this.filters,this.offset)),page=>{if(version!==this.queryVersion||recordsVersion!==this.recordsVersion)return;this.recordsPending=false;this.page=page;this.render();},error=>{if(version!==this.queryVersion||recordsVersion!==this.recordsVersion)return;this.recordsPending=false;this.recordsDirty=true;this.error=error;this.render();});
    }
  }
  mutate(request){
    if(this.busy)return;this.busy=true;this.error=null;this.render();
    this.actions.run('write',()=>this.call(request),result=>{
      // HA call_service wraps the business record in result.response.
      if(this.pendingLive?.request===request)this.pendingLive=null;
      this.lastRecord=request.return_response?result.response:result;this.busy=false;this.notice=this.t('saved');this.summaryDirty=true;this.recordsDirty=true;this.refresh();this.render();
    },error=>{this.busy=false;this.error=error;this.render();});
  }
  live(service,point){
    if(this.busy||(service==='start'&&this.pendingSelections.has(point.id)))return;
    try{
      const intent=JSON.stringify([service,point.id,service==='end'?point.active_record?.id:point.selected_identity_id]);
      if(this.pendingLive?.intent!==intent)this.pendingLive={intent,request:liveRequest(service,point,newRequestId())};
      this.mutate(this.pendingLive.request);
    }catch(error){this.error=error;this.render();}
  }
  openDialog(mode,detail){
    this.dialogEpoch++;
    if(!this.snapshot)return;this.dialog?.close();
    this.dialog=new RecordDialog(this.shadowRoot,{mode,detail,record:detail?.record,language:this.language,currency:this.snapshot.currency,timezone:this.snapshot.timezone,points:[...this.snapshot.points,...this.snapshot.archived_points],identities:this.snapshot.identities,defaultPoint:this.filters.point_id,defaultIdentity:this.filters.identity_id,
      call:request=>this.call(request),pointName:id=>this.pointName(id),identityName:id=>this.identityName(id),onSaved:()=>{this.notice=this.t('saved');this.summaryDirty=true;this.recordsDirty=true;this.refresh();},onClose:()=>{this.dialogEpoch++;this.dialog=null;}});
  }
  details(record){
    const epoch=++this.dialogEpoch;
    return this.latest.run('detail',()=>this.call({type:'charge_tally/records',record_id:record.id}),
      detail=>{if(epoch===this.dialogEpoch)this.openDialog('details',detail);},
      error=>{if(epoch===this.dialogEpoch){this.error=error;this.render();}});
  }
  render(){if(!this.body)return;this.view??=new CardView(this);this.view.update();}


}
if(!customElements.get('charge-tally-card'))customElements.define('charge-tally-card',ChargeTallyCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(card=>card.type==='charge-tally-card'))window.customCards.push({type:'charge-tally-card',name:'Charge Tally',preview:true,description:tr('cardDescription',globalThis.navigator?.language)});
