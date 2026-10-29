import {SelectControl} from './card-controls.js?v=0.1.2-11';
import {tr} from './card-i18n.js?v=0.1.2-11';
import {styles} from './nfc-styles.js?v=0.1.2-11';

const node=(tag,className)=>{const el=document.createElement(tag);if(className)el.className=className;return el;};
const text=(tag,key,className)=>{const el=node(tag,className);el.dataset.i18n=key;return el;};
const button=(key,action,callback,primary=false)=>{
  const el=text('button',key,primary?'primary':'');el.type='button';el.dataset.action=action;el.addEventListener('click',callback);return el;
};
const statuses={synced:'nfcSynced',external:'nfcExternal',missing:'nfcMissing',invalid:'nfcInvalid',pending:'nfcPending',enabled:'nfcEnabled',paused:'nfcPaused',unavailable:'nfcUnavailable',native_unavailable:'nfcUnavailable'};

export class NfcView {
  constructor(root,handlers){
    this.root=root;this.handlers=handlers;this.rows=[];this.controls=[];
    const style=node('style');style.textContent=styles;root.append(style);
    this.main=node('main');root.append(this.main);
    this.main.append(text('h1','nfcTitle'),text('p','nfcIntro','muted'));
    const toolbar=node('div','toolbar');
    this.newButton=button('nfcNew','new',()=>this.openForm());
    this.refreshButton=button('nfcRefresh','refresh',()=>handlers.refresh());
    toolbar.append(this.newButton,this.refreshButton);this.main.append(toolbar);
    this.error=node('p','error');this.error.setAttribute('role','alert');this.main.append(this.error);
    this.empty=node('p','muted');this.main.append(this.empty);
    this.tagsLink=text('a','nfcManageTags');this.tagsLink.href='/config/tags';this.main.append(this.tagsLink);
    this.pointsLink=text('a','nfcManagePoints');this.pointsLink.href='/config/integrations/integration/charge_tally';this.main.append(this.pointsLink);
    this.editor=node('section','editor');this.editor.hidden=true;this.main.append(this.editor);
    this.list=node('section');this.main.append(this.list);
    this.dialog=node('dialog');this.main.append(this.dialog);
  }
  t(key){return tr(key,this.model?.language||'en');}
  name(kind,id){return this.model?.catalog?.[kind]?.find(x=>x.id===id)?.name||id||this.t('nfcNoDefault');}
  summary(draft){
    if(!draft)return '';
    return this.name('tags',draft.tag_id)+' → '+this.name('points',draft.point_id)+'\n'+
      draft.device_bindings.map(item=>this.name('devices',item.device_id)+' → '+this.name('identities',item.identity_id)).join('\n')+
      '\n'+this.t('nfcDefault')+': '+this.name('identities',draft.default_identity_id);
  }
  field(key,kind,parent,value='',optional=false){
    const label=node('label'),caption=text('span',key);label.append(caption);
    const control=new SelectControl();control.node.dataset.field=kind;
    label.append(control.node);parent.append(label);this.controls.push(control);
    control.update({options:[{id:value,name:value}],value});
    control.meta={kind,optional};return control;
  }
  openForm(rule=null,kind=null){
    if(this.model?.busy)return;
    this.closeForm();this.editRule=rule;this.editKind=kind;this.editor.hidden=false;
    this.editor.append(text('h2',rule?'nfcEdit':'nfcNew'));
    const grid=node('div','grid');this.editor.append(grid);
    const draft=rule?.applied?.draft||rule?.pending?.draft;
    this.tag=this.field('nfcTag','tag',grid,draft?.tag_id||'');
    this.point=this.field('nfcPoint','point',grid,draft?.point_id||'');
    this.default=this.field('nfcDefault','default',grid,draft?.default_identity_id||'',true);
    this.bindingBox=node('div');this.editor.append(this.bindingBox);
    for(const binding of draft?.device_bindings||[])this.addRow(binding);
    this.editor.append(button('nfcAddDevice','add-device',()=>this.addRow()));
    const actions=node('div','actions');
    actions.append(button('nfcSave','save',()=>this.handlers.save(this.editRule,this.read(),this.editKind),true),
      button('nfcCancel','cancel',()=>this.closeForm()));
    this.editor.append(actions);this.update(this.model);
  }
  addRow(binding={}){
    const element=node('div','binding');this.bindingBox.append(element);
    const row={element};
    row.device=this.field('nfcDevice','device',element,binding.device_id||'');
    row.identity=this.field('nfcIdentity','identity',element,binding.identity_id||'');
    element.append(button('nfcRemoveDevice','remove-device',()=>{
      row.device.dispose();row.identity.dispose();element.remove();
      this.controls=this.controls.filter(c=>c!==row.device&&c!==row.identity);
      this.rows=this.rows.filter(item=>item!==row);
    }));
    this.rows.push(row);if(this.model)this.updateControls();
  }
  read(){
    return {tag_id:this.tag.node.value,point_id:this.point.node.value,
      device_bindings:this.rows.map(row=>({device_id:row.device.node.value,identity_id:row.identity.node.value})),
      default_identity_id:this.default.node.value||null};
  }
  updateControls(){
    const kinds={tag:'tags',point:'points',device:'devices',identity:'identities',default:'identities'};
    for(const control of this.controls){
      const {kind,optional}=control.meta,value=control.node.value;
      const options=(this.model.catalog[kinds[kind]]||[]).filter(item=>item.active!==false).map(item=>({
        id:item.id,name:item.name+(['tag','device'].includes(kind)?' · '+item.id.slice(0,8):''),
      }));
      options.unshift({id:'',name:this.t(optional?'nfcNoDefault':'nfcChoose')});
      if(value&&!options.some(item=>item.id===value))options.push({id:value,name:this.t('nfcInvalid')+' · '+value});
      control.update({options,value,disabled:this.model.busy||!this.model.connected});
    }
    for(const el of this.root.querySelectorAll('[data-i18n]'))el.textContent=this.t(el.dataset.i18n);
  }
  closeForm(){
    for(const control of this.controls)control.dispose();
    this.controls=[];this.rows=[];this.editRule=null;this.editor.replaceChildren();this.editor.hidden=true;
  }
  confirm(title,draft,action,noteKey='nfcConfirmHint'){
    this.dialog.replaceChildren();
    const heading=node('h2');heading.textContent=title;
    const summary=node('p','summary');summary.textContent=this.summary(draft);
    const note=text('p',noteKey,'muted');const actions=node('div','actions');
    actions.append(button('nfcCancel','dismiss',()=>this.dialog.close()),
      button('nfcConfirm','confirm',()=>{this.dialog.close();action();},true));
    this.dialog.append(heading,summary,note,actions);
    this.updateControls();this.dialog.showModal();
  }
  update(model){
    if(!model)return;this.model=model;
    this.error.textContent=model.error?this.t(model.error):'';
    this.empty.textContent=!model.catalog.points.length?this.t('nfcNoPoints'):
      !model.catalog.tags.length?this.t('nfcNoTags'):!model.rules.length?this.t('nfcEmpty'):'';
    this.tagsLink.hidden=!!model.catalog.tags.length;
    this.pointsLink.hidden=!!model.catalog.points.length;
    this.list.replaceChildren();
    for(const rule of model.rules){
      const article=node('article'),draft=rule.pending?.draft||rule.applied?.draft;
      const title=node('h2');title.textContent=this.name('tags',draft?.tag_id)+' → '+this.name('points',draft?.point_id);
      const summary=node('p','summary');summary.textContent=this.summary(draft);
      const status=node('div','status');
      status.append(text('span',statuses[rule.inspection?.config_status]||'nfcUnavailable'),
        text('span',statuses[rule.inspection?.runtime_status]||'nfcUnavailable'));
      const actions=node('div','actions'),state=rule.inspection?.config_status;
      const add=(key,action)=>actions.append(button(key,action,()=>this.handlers.action(action,rule)));
      if(!rule.pending&&['synced','invalid'].includes(state))actions.append(button('nfcEdit','edit',()=>this.openForm(rule)));
      if(state==='external'&&rule.applied&&!rule.deleting)actions.append(button('nfcRestore','restore',()=>this.openForm(rule,'restore')));
      if(state==='missing'&&!rule.pending)actions.append(button('nfcRecreate','recreate',()=>this.openForm(rule,'recreate')));
      if(rule.pending&&state!=='external'){
        add('nfcResume','resume');
        if(['create','update'].includes(rule.pending.kind)&&rule.inspection?.pending_state==='unwritten')add('nfcDiscard','discard');
      }
      if(rule.pending?.kind==='delete'&&state!=='missing'&&rule.inspection?.pending_state!=='applied')add('nfcDiscard','discard');
      if(!rule.pending&&state!=='external')add('nfcDelete','delete');
      if(rule.inspection?.automation_entity_id){
        const link=text('a','nfcOpen');
        link.href='/config/automation/edit/'+encodeURIComponent(rule.automation_id);
        actions.append(link);
      }
      article.append(title,status,summary,actions);this.list.append(article);
    }
    this.updateControls();
    for(const el of this.root.querySelectorAll('button'))el.disabled=model.busy||!model.connected;
    this.newButton.disabled||=!model.catalog.points.length||!model.catalog.tags.length||!!model.error&&model.error==='nfcErrorUnavailable';
  }
  dispose(){for(const control of this.controls)control.dispose();this.dialog.close();}
}
