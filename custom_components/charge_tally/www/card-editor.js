import {tr} from './card-i18n.js?v=0.1.2-3';
import {styles} from './card-styles.js?v=0.1.2-3';
import {Latest,errorMessage} from './card-state.js?v=0.1.2-3';
import {el,field,select,input} from './card-ui.js?v=0.1.2-3';
export class ChargeTallyEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this.latest=new Latest();this.config={};}
  setConfig(config){this.config={...config};this.render();}
  set hass(hass){const old=this._hass?.connection;this._hass=hass;if(this.isConnected&&old!==hass.connection)this.load();else if(this.language!==hass.language)this.render();}
  connectedCallback(){this.load();}
  disconnectedCallback(){this.latest.invalidate();}
  load(){if(!this._hass)return;this.latest.run('snapshot',()=>this._hass.callWS({type:'charge_tally/snapshot'}),snapshot=>{this.snapshot=snapshot;this.error=null;this.render();},error=>{this.snapshot=null;this.error=error;this.render();});}
  update(key,value){const config={...this.config,[key]:value};if(value==='')delete config[key];this.config=config;this.dispatchEvent(new CustomEvent('config-changed',{detail:{config},bubbles:true,composed:true}));}
  render(){
    this.language=this._hass?.language||'en';const t=key=>tr(key,this.language),style=el('style',styles),box=el('div',null,{class:'editor stack'});
    const title=input('text',this.config.title||'');title.addEventListener('input',()=>this.update('title',title.value));box.append(field(t('title'),title));
    if(this.error)box.append(el('p',errorMessage(this.error,this.language),{class:'alert',role:'alert'}));
    const snapshot=this.snapshot||{points:[],identities:[]};
    for(const [key,label,items] of [['point_id','point',[...snapshot.points,...(snapshot.archived_points||[])]],['identity_id','identity',snapshot.identities]]){
      const options=[{id:'',name:t('all')},...items.map(item=>({...item,name:item.name+(item.active===false?` (${t('archived')})`:'')}))];
      if(this.config[key]&&!items.some(item=>item.id===this.config[key]))options.push({id:this.config[key],name:`${t('unavailable')}: ${this.config[key]}`});
      box.append(field(t(label),select(options,this.config[key],value=>this.update(key,value))));
    }
    for(const [key,label]of [['show_records','showRecords'],['show_chart','showChart']]){const checkbox=input('checkbox');checkbox.checked=this.config[key]!==false;checkbox.addEventListener('change',()=>this.update(key,checkbox.checked));const labelNode=field(t(label),checkbox);labelNode.className='check';box.append(labelNode);}
    this.shadowRoot.replaceChildren(style,box);
  }
}
if(!customElements.get('charge-tally-card-editor'))customElements.define('charge-tally-card-editor',ChargeTallyEditor);
