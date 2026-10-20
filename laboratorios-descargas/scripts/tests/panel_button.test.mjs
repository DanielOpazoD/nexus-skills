import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import {readFile} from 'node:fs/promises';
const code=await readFile(new URL('../../chrome-bridge/eloisa_panel.js',import.meta.url),'utf8');
function setup({origin='https://clinicohangaroa.eloisa.cl',path='/main',frame=false}={}){
 const nodes=[],messages=[],observers=[],events={},location={origin,pathname:path};let version='3.4.0';
 class Element{
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.isConnected=false;nodes.push(this);}
  append(...children){for(const node of children){this.children.push(node);node.isConnected=true;}}
  attachShadow(){this.shadow=new Element('shadow');return this.shadow;}
  setAttribute(){}addEventListener(name,fn){this.events[name]=fn;}
  remove(){this.isConnected=false;}
 }
 const document={createElement:tag=>new Element(tag),getElementById:id=>nodes.find(node=>node.id===id&&node.isConnected),documentElement:new Element('html')};
 const window={addEventListener:(name,fn)=>events[name]=fn,removeEventListener:name=>delete events[name]};window.top=frame?{}:window;
 const ctx={document,window,location,chrome:{runtime:{getManifest:()=>({version}),sendMessage:async message=>{messages.push(message);return {ok:true};}}},
  MutationObserver:class{constructor(fn){this.fn=fn;observers.push(this);}observe(){}disconnect(){this.disconnected=true;}},requestAnimationFrame:fn=>fn()};
 vm.createContext(ctx);const run=()=>vm.runInContext(code,ctx);run();
 return {nodes,messages,events,location,observers,run,setVersion:v=>version=v,host:()=>document.getElementById('nexo-clinical-panel-host'),button:()=>nodes.find(n=>n.tag==='button')};
}
test('el botón aparece una sola vez y solo en el portal oficial principal',()=>{
 const ui=setup();assert.ok(ui.host());ui.run();assert.equal(ui.observers.length,1);
 assert.equal(setup({origin:'https://otro.invalid'}).host(),undefined);assert.equal(setup({frame:true}).host(),undefined);
});
test('entrar y salir de main oculta el botón; un render de la SPA lo recupera',()=>{
 const ui=setup({path:'/login'});assert.equal(ui.host().hidden,true);
 ui.location.pathname='/main/atenciones';ui.events.popstate();assert.equal(ui.host().hidden,false);
 const host=ui.host();host.remove();ui.observers[0].fn();assert.equal(ui.host(),host);
 ui.location.pathname='/main-otro';ui.events.popstate();assert.equal(host.hidden,true);
});
test('al actualizar se retira el observador anterior, sin duplicar el círculo',()=>{
 const ui=setup(),old=ui.host();ui.setVersion('3.4.1');ui.run();
 assert.equal(old.isConnected,false);assert.equal(ui.observers[0].disconnected,true);assert.notEqual(ui.host(),old);
});
test('pulsar sólo pide abrir el panel y no transmite datos de la ficha',async()=>{
 const ui=setup();await ui.button().events.click();
 assert.equal(JSON.stringify(ui.messages),JSON.stringify([{type:'nexo.panel.open'}]));
});
