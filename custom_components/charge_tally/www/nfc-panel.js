import {NfcClient} from './nfc-api.js?v=0.1.2-11';
import {NfcView} from './nfc-view.js?v=0.1.2-11';
import {newRequestId} from './request-id.js?v=0.1.2-11';

const errorKey=error=>({
  conflict:'nfcErrorConflict',pending:'nfcErrorConflict',duplicate_rule:'nfcErrorDuplicate',
  duplicate_device:'nfcErrorDuplicate',invalid_reference:'nfcErrorReference',
  native_unavailable:'nfcErrorUnavailable',runtime_unavailable:'nfcErrorUnavailable',
  unauthorized:'nfcErrorUnavailable',disconnected:'nfcErrorDisconnected',
  invalid_request:'nfcErrorRequired',empty_rule:'nfcErrorRequired',
}[error?.code]||'nfcErrorFailed');

class NfcPanel extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:'open'});this.generation=0;
    this.model={language:'en',catalog:{points:[],tags:[],devices:[],identities:[]},rules:[],busy:false,connected:true,error:null};
  }
  set hass(value){
    this._hass=value;this.model.language=value.language||'en';
    this.model.connected=value.connection?.connected!==false&&!!value.user?.is_admin;
    if(!value.user?.is_admin){
      this.client?.dispose();this.client=null;this.generation++;
      this.model.rules=[];this.model.catalog={points:[],tags:[],devices:[],identities:[]};
      this.model.busy=false;this.model.error='nfcErrorUnavailable';this.view?.closeForm();
    }
    for(const rule of this.model.rules){
      const state=value.states?.[rule.inspection?.automation_entity_id];
      if(state)rule.inspection.runtime_status=({on:'enabled',off:'paused'})[state.state]||'unavailable';
    }
    if(this.client)this.client.hass=value;
    if(this.isConnected)this.start();this.view?.update(this.model);
  }
  get hass(){return this._hass;}
  connectedCallback(){
    this.view=new NfcView(this.shadowRoot,{
      refresh:()=>this.refresh(),save:(rule,draft,kind)=>this.save(rule,draft,kind),
      action:(action,rule)=>this.action(action,rule),
    });
    this.start();this.view.update(this.model);
  }
  start(){
    if(!this.hass||!this.view)return;
    const entryId=new URL(location.href).searchParams.get('entry_id');
    if(!entryId||!this.hass.user?.is_admin){this.model.error='nfcErrorUnavailable';return;}
    if(this.client?.entryId===entryId)return;
    this.client?.dispose();this.generation++;
    this.client=new NfcClient(this.hass,entryId);this.refresh();
  }
  async refresh(){
    if(!this.client||this.model.busy)return;
    const client=this.client,generation=this.generation;
    this.model.busy=true;this.view.update(this.model);
    try {
      const [catalog,rules]=await Promise.all([client.catalog(),client.list()]);
      await Promise.all(rules.map(async rule=>{
        try{rule.inspection=await client.inspect(rule);}
        catch(error){rule.inspection={config_status:'unavailable',runtime_status:'unavailable'};rule.loadError=errorKey(error);}
      }));
      client.check(true);
      if(generation!==this.generation)return;
      this.model.catalog=catalog;this.model.rules=rules;
      this.model.error=rules.find(rule=>rule.loadError)?.loadError||null;
    } catch(error){if(generation===this.generation)this.model.error=errorKey(error);}
    finally{if(generation===this.generation){this.model.busy=false;this.view.update(this.model);}}
  }
  save(rule,draft,kind){
    if(this.model.busy)return;
    const signature=JSON.stringify([rule?.rule_id,draft,kind]);
    if(this.intent?.signature!==signature)this.intent={signature,operationId:newRequestId()};
    const intent={ruleId:rule?.rule_id||null,draft,expectedRevision:rule?.revision??null,operationId:this.intent.operationId};
    if(kind)intent.kind=kind;
    this.view.confirm(this.view.t({restore:'nfcRestore',recreate:'nfcRecreate'}[kind]||'nfcSave'),draft,()=>this.run(()=>this.client.save(intent)),kind==='restore'?'nfcRestoreHint':'nfcConfirmHint');
  }
  action(action,rule){
    if(this.model.busy)return;
    if(action==='resume'){this.run(()=>this.client.resume(rule));return;}
    const draft=rule.applied?.draft||rule.pending?.draft;
    const key={delete:'nfcDelete',restore:'nfcRestore',recreate:'nfcRecreate',discard:'nfcDiscard'}[action];
    this.view.confirm(this.view.t(key),draft,()=>this.run(()=>{
      if(action==='delete')return this.client.remove(rule,newRequestId());
      if(action==='discard')return this.client.cancel(rule);
      return this.client.save({ruleId:rule.rule_id,expectedRevision:rule.revision,operationId:newRequestId(),kind:action});
    }));
  }
  async run(operation){
    if(this.model.busy)return;
    const generation=this.generation;
    this.model.busy=true;this.model.error=null;this.view.update(this.model);
    let error=null;
    try{
      await operation();
      if(generation===this.generation){this.view.closeForm();this.intent=null;}
    }catch(err){error=errorKey(err);}
    finally{
      if(generation===this.generation){
        this.model.busy=false;await this.refresh();
        if(error){this.model.error=error;this.view.update(this.model);}
      }
    }
  }
  disconnectedCallback(){
    this.generation++;this.client?.dispose();this.client=null;this.view?.dispose();
    this.view=null;this.shadowRoot.replaceChildren();this.model.busy=false;
  }
}
customElements.define('charge-tally-nfc-panel',NfcPanel);
