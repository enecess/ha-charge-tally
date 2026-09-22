export class SelectControl {
  constructor({onChange}={}){
    this.node=document.createElement('select');this.onChange=onChange;this.editing=false;
    this.focus=()=>{this.editing=true;};
    this.blur=()=>{this.editing=false;if(this.pending){const next=this.pending;this.pending=null;this.update(next);}};
    this.change=()=>{
      if(this.node.disabled)return;
      // A local choice supersedes queued presentation values; later model updates can still reject it.
      if(this.pending)this.pending.value=this.node.value;
      this.onChange?.(this.node.value);
    };
    this.node.addEventListener('focus',this.focus);this.node.addEventListener('blur',this.blur);this.node.addEventListener('change',this.change);
  }
  update({options=[],value='',disabled=false}){
    const next={options:options.map(({id,name})=>({id:String(id),name:String(name)})),value:String(value??''),disabled:!!disabled};
    this.node.disabled=next.disabled;
    if(this.editing){this.pending=next;return;}
    const key=JSON.stringify(next.options);
    if(key!==this.optionsKey){
      this.node.replaceChildren(...next.options.map(item=>{const option=document.createElement('option');option.value=item.id;option.textContent=item.name;return option;}));this.optionsKey=key;
    }
    if(this.node.value!==next.value)this.node.value=next.value;
  }
  dispose(){this.pending=null;this.editing=false;this.node.removeEventListener('focus',this.focus);this.node.removeEventListener('blur',this.blur);this.node.removeEventListener('change',this.change);}
}
