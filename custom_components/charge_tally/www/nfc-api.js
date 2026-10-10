function failure(code) { return Object.assign(new Error(code), {code}); }

export class NfcClient {
  constructor(hass, entryId) { this.hass=hass;this.entryId=entryId;this.disposed=false; }
  check(native=false) {
    if(this.disposed||this.hass.connection?.connected===false)throw failure('disconnected');
    if(native&&!['config','automation'].every(key=>this.hass.config?.components?.includes(key)))throw failure('native_unavailable');
  }
  async ws(command,data={}) {
    this.check();
    const result=await this.hass.callWS({type:'charge_tally/nfc/'+command,entry_id:this.entryId,...data});
    this.check();return result;
  }
  catalog(){return this.ws('catalog');}
  list(){return this.ws('list');}
  async read(automationId) {
    this.check(true);
    try {
      const result=await this.hass.callApi('GET','config/automation/config/'+encodeURIComponent(automationId));
      this.check();return result;
    } catch(error) {
      this.check();
      if(error.status_code===404||error.status===404)return null;
      throw error;
    }
  }
  async inspect(rule) {
    const observed=await this.read(rule.automation_id);
    return this.ws('inspect',{rule_id:rule.rule_id,observed_config:observed});
  }
  async save({ruleId=null,draft=null,expectedRevision=null,operationId,kind=ruleId?'update':'create'}) {
    this.check(true);
    if(ruleId){
      const rule=(await this.list()).find(item=>item.rule_id===ruleId);
      if(!rule)throw failure('rule_missing');
      if(!rule.pending){
        const state=await this.inspect(rule);
        if(kind==='update'&&!['synced','invalid'].includes(state.config_status))throw failure(state.config_status==='missing'?'missing':'conflict');
        if(kind==='recreate'&&state.config_status!=='missing')throw failure('conflict');
      }
    }
    const prepared=await this.ws('prepare',{
      kind,rule_id:ruleId,draft,expected_revision:expectedRevision,operation_id:operationId,
    });
    return this.apply(prepared);
  }
  async apply(prepared) {
    this.check(true);
    const current=(await this.list()).find(item=>item.rule_id===prepared.rule_id);
    if(current&&current.pending?.operation_id!==prepared.operation_id&&current.applied?.version!==prepared.version)throw failure('conflict');
    const observed=await this.read(prepared.automation_id);
    if(!current){
      if(prepared.kind==='delete'&&observed===null)return this.ws('confirm',{operation_id:prepared.operation_id,observed_config:null});
      throw failure('rule_missing');
    }
    const state=await this.ws('inspect',{rule_id:prepared.rule_id,observed_config:observed});
    if(state.pending_state==='applied'||(!current.pending&&current.applied?.version===prepared.version&&state.config_status==='synced')){
      return this.ws('confirm',{operation_id:prepared.operation_id,observed_config:observed});
    }
    if(prepared.kind==='recreate'&&observed!==null)throw failure('conflict');
    if(prepared.kind==='create'&&observed!==null)throw failure('conflict');
    if(prepared.kind==='update'&&(observed===null||state.pending_state!=='unwritten'))throw failure('conflict');
    if(prepared.kind==='restore'&&observed===null)throw failure('missing');
    if(prepared.kind==='delete'&&observed!==null&&state.pending_state!=='unwritten')throw failure('conflict');
    const path='config/automation/config/'+encodeURIComponent(prepared.automation_id);
    this.check(true);
    if(prepared.kind==='delete'){
      if(observed!==null)await this.hass.callApi('DELETE',path);
    } else {
      const config=structuredClone(prepared.desired_config);
      if(observed)for(const key of ['alias','description','trace']){
        if(Object.hasOwn(observed,key))config[key]=structuredClone(observed[key]);
      }
      await this.hass.callApi('POST',path,config);
    }
    this.check();
    const verified=await this.read(prepared.automation_id);
    return this.ws('confirm',{operation_id:prepared.operation_id,observed_config:verified});
  }
  async resume(rule){
    this.check(true);
    if(!rule.pending)throw failure('conflict');
    return this.apply(rule.pending);
  }
  async remove(rule,operationId){
    this.check(true);
    const state=await this.inspect(rule);
    if(state.config_status==='external')throw failure('conflict');
    return this.save({ruleId:rule.rule_id,expectedRevision:rule.revision,operationId,kind:'delete'});
  }
  async cancel(rule){
    if(!rule.pending)throw failure('conflict');
    const observed=await this.read(rule.automation_id);
    return this.ws('cancel',{operation_id:rule.pending.operation_id,observed_config:observed});
  }
  dispose(){this.disposed=true;}
}
