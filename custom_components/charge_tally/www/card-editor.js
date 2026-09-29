import {tr} from './card-i18n.js?v=0.1.2-5';
import {styles} from './card-styles.js?v=0.1.2-5';
import {Latest,errorMessage} from './card-state.js?v=0.1.2-5';
import {el,field,input} from './card-ui.js?v=0.1.2-5';
import {SelectControl} from './card-controls.js?v=0.1.2-5';
export class ChargeTallyEditor extends HTMLElement {
  constructor(){super();this.attachShadow({mode:'open'});this.latest=new Latest();this.config={};}
  setConfig(config){this.config={...config};this.render();}
  set hass(hass){const old=this._hass?.connection;this._hass=hass;if(this.language!==hass.language)this.render();if(this.isConnected&&old!==hass.connection)this.load();}
  connectedCallback(){this.load();}
  disconnectedCallback(){this.latest.invalidate();for(const control of Object.values(this.controls||{}))control.dispose();this.shadowRoot.replaceChildren();this.box=null;}
  load(){if(!this._hass)return;this.latest.run('snapshot',()=>this._hass.callWS({type:'charge_tally/snapshot'}),snapshot=>{this.snapshot=snapshot;this.error=null;this.render();},error=>{this.snapshot=null;this.error=error;this.render();});}
  update(key,value){const config={...this.config,[key]:value};if(value==='')delete config[key];this.config=config;this.dispatchEvent(new CustomEvent('config-changed',{detail:{config},bubbles:true,composed:true}));}
  render(){
    this.language=this._hass?.language||'en';const t=key=>tr(key,this.language);
    if(!this.box){
      this.box=el('div',null,{class:'editor stack'});this.titleInput=input('text');this.titleInput.addEventListener('input',()=>this.update('title',this.titleInput.value));this.titleInputLabel=field('',this.titleInput);this.errorNode=el('p',null,{class:'alert',role:'alert'});this.box.append(this.titleInputLabel,this.errorNode);this.controls={};this.labels={};this.checks={};
      for(const key of ['point_id','identity_id']){const control=new SelectControl({onChange:value=>this.update(key,value)});this.controls[key]=control;this.labels[key]=field('',control.node);this.box.append(this.labels[key]);}
      for(const key of ['show_records','show_chart']){const checkbox=input('checkbox');checkbox.addEventListener('change',()=>this.update(key,checkbox.checked));this.checks[key]=checkbox;this.labels[key]=field('',checkbox);this.labels[key].className='check';this.box.append(this.labels[key]);}
      this.shadowRoot.append(el('style',styles),this.box);
    }
    this.titleInputLabel.firstChild.textContent=t('title');if(this.shadowRoot.activeElement!==this.titleInput)this.titleInput.value=this.config.title||'';this.errorNode.hidden=!this.error;this.errorNode.textContent=this.error?errorMessage(this.error,this.language):'';
    const snapshot=this.snapshot||{points:[],identities:[]};
    for(const [key,label,items] of [['point_id','point',[...snapshot.points,...(snapshot.archived_points||[])]],['identity_id','identity',snapshot.identities]]){
      const options=[{id:'',name:t('all')},...items.map(item=>({...item,name:item.name+(item.active===false?` (${t('archived')})`:'')}))];
      if(this.config[key]&&!items.some(item=>item.id===this.config[key]))options.push({id:this.config[key],name:`${t('unavailable')}: ${this.config[key]}`});
      this.labels[key].firstChild.textContent=t(label);this.controls[key].update({options,value:this.config[key]});
    }
    for(const [key,label]of [['show_records','showRecords'],['show_chart','showChart']]){this.checks[key].checked=this.config[key]!==false;this.labels[key].firstChild.textContent=t(label);}
  }
}
if(!customElements.get('charge-tally-card-editor'))customElements.define('charge-tally-card-editor',ChargeTallyEditor);
