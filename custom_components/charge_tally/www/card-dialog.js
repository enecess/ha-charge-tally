import {tr} from './card-i18n.js?v=0.1.2';
import {Latest,localInput,localCandidates,errorMessage,previewRequest,commitRequest} from './card-state.js?v=0.1.2';
import {el,button,field,select,input,summaryView,segmentTable,quality,dateText} from './card-ui.js?v=0.1.2';

export class RecordDialog {
  constructor(host,options){
    Object.assign(this,options);this.host=host;this.latest=new Latest();this.closed=false;this.preview=null;
    this.language=options.language||'en';this.t=key=>tr(key,this.language);
    this.node=el('dialog',null,{'aria-label':this.t(options.mode==='create'?'newRecord':options.mode)});
    this.node.addEventListener('cancel',()=>this.close());this.node.addEventListener('close',()=>this.dispose());
    host.append(this.node);this.render();this.node.showModal();
  }
  dispose(){if(this.closed)return;this.closed=true;this.latest.invalidate();this.node.remove();this.onClose?.();}
  close(){this.node.close();this.dispose();}
  setLanguage(language){
    if(this.language===language||this.closed)return;
    this.language=language;this.render();this.updateButtons();
  }
  fail(error){this.lastError=error;this.error.textContent=errorMessage(error,this.language);this.error.hidden=false;}
  async run(request,accept){
    if(this.busy||this.closed)return;this.busy=true;this.lastError=null;this.error.hidden=true;this.updateButtons();
    await this.latest.run('dialog',()=>this.call(request),value=>{this.busy=false;if(!this.closed){accept(value);this.updateButtons();}},error=>{this.busy=false;if(!this.closed){this.fail(error);this.updateButtons();}});
  }
  updateButtons(){
    for(const b of this.node.querySelectorAll('button[data-write]'))b.disabled=this.busy;
    for(const control of this.node.querySelectorAll('input,select,textarea'))control.disabled=this.busy||control.dataset.locked==='true';
    if(this.saveButton)this.saveButton.disabled=this.busy||!this.preview||!!this.preview.overlaps?.length;
  }
  action(label,fn,kind=''){const b=button(this.t(label),fn,false,kind);b.dataset.write='';return b;}
  render(){
    this.node.setAttribute('aria-label',this.t(this.mode==='create'?'newRecord':this.mode));
    const title=el('div',null,{class:'row spread'});title.append(el('h2',this.t(this.mode==='create'?'newRecord':this.mode)),button(this.t('close'),()=>this.close()));
    this.error=el('p',null,{class:'alert',role:'alert'});this.error.hidden=true;
    this.content=el('div',null,{class:'dialog-content stack'});this.node.replaceChildren(title,this.error,this.content);
    if(this.mode==='details')this.renderDetails();else if(this.mode==='reassign'||this.mode==='void')this.renderAction();else this.renderForm();
    if(this.lastError)this.fail(this.lastError);
    this.node.scrollTop=0;
  }
  renderDetails(){
    const {record,segments,revisions}=this.detail;this.record=record;
    this.content.append(el('p',`${this.pointName(record.point_id)} · ${this.identityName(record.identity_id)}`),summaryView(record,this.currency,this.language),el('p',`${dateText(record.start,record.timezone)} → ${dateText(record.end,record.timezone)} (${record.timezone})`),el('p',`${this.t('status')}: ${tr(record.status,this.language)} · ${this.t('source')}: ${tr(record.source==='manual'?'manual_source':record.source,this.language)} · ${this.t('revision')}: ${record.revision}`),el('p',quality(record.quality,this.language),{class:'quality'}),el('p',record.note||''),el('h3',this.t('segments')),segmentTable(segments,this.language,this.currency,record.timezone));
    const history=el('details');history.append(el('summary',`${this.t('revisions')} (${revisions?.length||0})`));
    for(const revision of revisions||[]){const item=el('div',null,{class:'point'}),r=revision.record;item.append(el('p',`${this.t('revision')} ${r.revision} · ${this.identityName(r.identity_id)} · ${tr(r.status,this.language)}`),summaryView(r,this.currency,this.language),el('p',r.note||''));history.append(item);}this.content.append(history);
    const actions=el('div',null,{class:'row dialog-actions'});
    if(record.status!=='void')actions.append(button(this.t('reassign'),()=>{this.mode='reassign';this.render();}));
    if(record.status==='ended')actions.append(button(this.t('edit'),()=>{this.mode='edit';this.render();}),button(this.t('void'),()=>{this.mode='void';this.render();},false,'danger'));this.content.append(actions);
  }
  identityOptions(){const available=this.identities.filter(i=>i.active!==false);if(this.record&&!available.some(i=>i.id===this.record.identity_id)){const old=this.identities.find(i=>i.id===this.record.identity_id);available.push(old||{id:this.record.identity_id,name:this.identityName(this.record.identity_id)});}return available;}
  renderAction(){
    this.content.append(summaryView(this.record,this.currency,this.language),el('p',`${this.identityName(this.record.identity_id)} · ${dateText(this.record.start,this.record.timezone)}`));
    let target;
    if(this.mode==='reassign'){target=select(this.identityOptions(),this.targetIdentityId??this.record.identity_id);this.content.append(field(this.t('assignedIdentity'),target));}
    else this.content.append(el('p',this.t('voidHint')));
    this.requestId??=crypto.randomUUID();
    this.content.append(this.action(this.mode==='void'?'confirmVoid':'save',()=>{
      const request={type:'charge_tally/'+this.mode,record_id:this.record.id,expected_revision:this.record.revision,request_id:this.requestId,...(target?{identity_id:target.value}:{})};
      this.run(request,()=>{this.onSaved();this.close();});
    },this.mode==='void'?'danger':'primary'));
    target?.addEventListener('change',()=>{this.targetIdentityId=target.value;this.requestId=crypto.randomUUID();});
  }
  renderForm(){
    const record=this.record,timezone=record?.timezone||this.timezone;
    if(!this.form){
      this.form={point_id:record?.point_id||this.defaultPoint||this.points[0]?.id||'',identity_id:record?.identity_id||this.defaultIdentity||this.identities.find(i=>i.active!==false)?.id||'',start:record?localInput(record.start,timezone):'',end:record?localInput(record.end,timezone):'',energy_kwh:record?.manual_energy??'',cost:record?.manual_cost??'',cost_mode:'auto',note:record?.note||''};
      for(const key of ['start','end'])if(record?.[key])this.form[key+'_choice']=new Date(Math.floor(Date.parse(record[key])/1000)*1000).toISOString();
    }
    this.content.append(el('p',`${this.t('timezone')}: ${timezone}`,{class:'badge'}));
    const fields=el('div',null,{class:'grid'});
    const pointSelect=select(this.points,this.form.point_id,value=>{this.form.point_id=value;this.invalidatePreview();});pointSelect.disabled=!!record;pointSelect.dataset.locked=record?'true':'false';
    fields.append(field(this.t('point'),pointSelect),field(this.t('assignedIdentity'),select(this.identityOptions(),this.form.identity_id,value=>{this.form.identity_id=value;this.invalidatePreview();})));
    for(const key of ['start','end']){
      const wrap=el('div'),control=input('datetime-local',this.form[key]);control.step='1';wrap.append(field(this.t(key==='start'?'from':'to'),control));
      const ambiguity=el('div');wrap.append(ambiguity);
      const choices=()=>{ambiguity.replaceChildren();let candidates=[];try{candidates=localCandidates(control.value,timezone);}catch{this.fail({code:'timezone'});}
        if(candidates.length>1){const chosen=this.form[key+'_choice'];ambiguity.append(field(this.t('offset'),select([{id:'',name:this.t('choose')},...candidates.map(id=>({id,name:id}))],chosen,value=>{this.form[key+'_choice']=value;this.invalidatePreview();})));}
      };
      control.addEventListener('input',()=>{this.form[key]=control.value;this.form[key+'_choice']='';this.invalidatePreview();choices();});choices();fields.append(wrap);
    }
    const energy=input('text',this.form.energy_kwh);energy.inputMode='decimal';energy.maxLength=100;energy.addEventListener('input',()=>{this.form.energy_kwh=energy.value.trim();this.invalidatePreview();});fields.append(field(this.t(record?'editEnergy':'manualEnergy'),energy));
    const cost=input('text',this.form.cost);cost.inputMode='decimal';cost.maxLength=100;cost.disabled=this.form.cost_mode!=='manual';cost.dataset.locked=cost.disabled?'true':'false';cost.addEventListener('input',()=>{this.form.cost=cost.value.trim();this.invalidatePreview();});
    fields.append(field(this.t('costBasis'),select([{id:'auto',name:this.t(record?'keepCost':'autoCost')},{id:'manual',name:this.t('manualAmount')},{id:'unknown',name:this.t('pending')}],this.form.cost_mode,value=>{this.form.cost_mode=value;cost.dataset.locked=value==='manual'?'false':'true';this.invalidatePreview();})),field(this.t('manualAmount'),cost));
    const note=el('textarea');note.value=this.form.note;note.maxLength=2000;note.addEventListener('input',()=>{this.form.note=note.value;this.invalidatePreview();});
    this.previewBox=el('div');this.content.append(fields,field(this.t('note'),note),this.previewBox);
    const actions=el('div',null,{class:'row dialog-actions'});
    actions.append(this.action('preview',()=>{try{const request=previewRequest(this.form,timezone,record);this.run(request,value=>{this.preview=value;this.requestId=crypto.randomUUID();this.renderPreview();});}catch(error){this.fail(error);}},'primary'));
    this.saveButton=this.action('save',()=>{if(this.preview)this.run(commitRequest(this.preview,this.requestId),()=>{this.onSaved();this.close();});},'primary');this.saveButton.disabled=true;actions.append(this.saveButton);this.content.append(actions);
    if(this.preview)this.renderPreview();
  }
  invalidatePreview(){this.preview=null;this.previewBox?.replaceChildren();this.updateButtons();}
  renderPreview(){
    const p=this.preview,box=el('div',null,{class:'preview stack'});box.append(el('h3',this.t('impact')));
    if(this.record)box.append(el('p',this.t('before')),summaryView(this.record,this.currency,this.language));
    box.append(el('p',this.t('after')),summaryView(p.record,this.currency,this.language),el('p',`${this.pointName(p.record.point_id)} · ${this.identityName(p.record.identity_id)}`),el('p',`${dateText(p.record.start,p.record.timezone)} → ${dateText(p.record.end,p.record.timezone)}`),el('p',`${this.t('source')}: ${tr(p.record.source==='manual'?'manual_source':p.record.source,this.language)}`),el('p',quality(p.record.quality,this.language),{class:'quality'}),segmentTable(p.segments,this.language,this.currency,p.record.timezone));
    box.append(el('h3',this.t('coverage')));
    if(p.coverage?.length)for(const span of p.coverage)box.append(el('p',`${span.start} → ${span.end} · ${quality(span.quality,this.language)}`));else box.append(el('p',this.t('noCoverage')));
    box.append(el('p',`${this.t('overlaps')}: ${p.overlaps?.join(', ')||this.t('none')}`));if(p.overlaps?.length)this.fail({code:'overlap'});
    this.previewBox.replaceChildren(box);
  }
}
