import test from 'node:test';
import assert from 'node:assert/strict';
import {NfcClient} from '../../custom_components/charge_tally/www/nfc-api.js';

function fixture() {
  const expected={id:'a',alias:'Old',description:'Managed',actions:[{event:'old'}]};
  const desired={id:'a',alias:'Generated',description:'Generated',actions:[{event:'new'}]};
  const prepared={rule_id:'r',automation_id:'a',operation_id:'op',kind:'update',version:2,expected_config:expected,desired_config:desired};
  const rule={rule_id:'r',automation_id:'a',revision:2,applied:{version:1,automation_config:expected},pending:prepared};
  const state={config:structuredClone(expected),posts:0,deletes:0,confirmed:0,lost:false,readError:null,external:false,closed:false};
  const executable = value=>JSON.stringify(value?.actions);
  const hass={
    config:{components:['config','automation']},
    connection:{connected:true},
    callApi:async(method,path,config)=>{
      assert.equal(path,'config/automation/config/a');
      if(method==='GET'){
        if(state.readError)throw state.readError;
        if(state.config===null)throw {status_code:404};
        return structuredClone(state.config);
      }
      if(method==='POST'){
        state.posts++;state.config=structuredClone(config);
        if(state.lost){state.lost=false;throw Error('Network response lost');}
      } else if(method==='DELETE'){state.deletes++;state.config=null;}
    },
    callWS:async msg=>{
      assert.equal(msg.entry_id,'entry');
      switch(msg.type.split('/').at(-1)){
        case 'prepare':return prepared;
        case 'list':return [rule];
        case 'inspect':{
          const applied=executable(msg.observed_config)===executable(prepared.desired_config);
          const unwritten=executable(msg.observed_config)===executable(prepared.expected_config);
          return {config_status:state.external?'external':applied||unwritten?'pending':'external',
            pending_state:applied?'applied':unwritten?'unwritten':'conflict',runtime_status:'paused'};
        }
        case 'confirm':
          assert.equal(msg.operation_id,'op');
          assert.equal(executable(msg.observed_config),executable(prepared.desired_config));
          state.confirmed++;rule.applied={version:2,automation_config:msg.observed_config};rule.pending=null;return rule;
        default:throw Error(msg.type);
      }
    },
  };
  return {client:new NfcClient(hass,'entry'),hass,state,rule,prepared};
}

test('native save preserves user copy and confirms verified content',async()=>{
  const {client,state}=fixture();
  state.config.alias='My name';state.config.description='My description';state.config.trace={stored_traces:10};
  await client.save({ruleId:'r',draft:{},expectedRevision:2,operationId:'op',kind:'update'});
  assert.equal(state.posts,1);assert.equal(state.confirmed,1);
  assert.equal(state.config.alias,'My name');
  assert.equal(state.config.description,'My description');
  assert.deepEqual(state.config.trace,{stored_traces:10});
});

test('lost POST response resumes readback without posting a second time',async()=>{
  const {client,state,rule}=fixture();
  state.lost=true;
  await assert.rejects(client.save({ruleId:'r',draft:{},expectedRevision:2,operationId:'op',kind:'update'}));
  await client.resume(rule);
  assert.equal(state.posts,1);assert.equal(state.confirmed,1);
});

test('external executable changes stop before a native write',async()=>{
  const {client,state,rule}=fixture();
  state.external=true;state.config.actions=[{event:'user-custom'}];
  await assert.rejects(client.resume(rule),e=>e.code==='conflict');
  assert.equal(state.posts,0);assert.equal(state.confirmed,0);
});

test('permission and unavailable API are never interpreted as missing automation',async()=>{
  const {client,state,rule,hass}=fixture();
  state.readError={status_code:401};
  await assert.rejects(client.resume(rule));
  assert.equal(state.posts,0);
  state.readError=null;hass.config.components=[];
  await assert.rejects(client.resume(rule),e=>e.code==='native_unavailable');
  assert.equal(state.posts,0);
});

test('disposed or disconnected clients cannot create mutations',async()=>{
  const {client,state,rule,hass}=fixture();
  hass.connection.connected=false;
  await assert.rejects(client.resume(rule),e=>e.code==='disconnected');
  hass.connection.connected=true;client.dispose();
  await assert.rejects(client.resume(rule),e=>e.code==='disconnected');
  assert.equal(state.posts,0);
});

test('delete verifies disappearance before completing metadata cleanup',async()=>{
  const {client,state,rule,prepared}=fixture();
  prepared.kind='delete';prepared.desired_config=null;
  await client.remove(rule,'op');
  assert.equal(state.deletes,1);assert.equal(state.confirmed,1);assert.equal(state.posts,0);
});
