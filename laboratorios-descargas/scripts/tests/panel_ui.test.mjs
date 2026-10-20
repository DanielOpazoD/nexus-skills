import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import {readFile} from 'node:fs/promises';import {webcrypto} from 'node:crypto';
const base=new URL('../../',import.meta.url);
const catalog=JSON.parse(await readFile(new URL('assets/clinical_catalog.json',base),'utf8'));
const script=(await readFile(new URL('chrome-bridge/panel/library_core.js',base),'utf8'))+'\n'+(await readFile(new URL('chrome-bridge/panel/panel.js',base),'utf8'));
const document={id:'a'.repeat(64),sha256:'b'.repeat(64),date:'20-10-2026',referenceDate:'19-10-2026',status:'current'};
const patient={id:'p1',name:'Paciente Ficticio',rut:'11111111-1',documents:[document]};
const body='Paciente: Paciente Ficticio\nRUT: 11111111-1\nFecha de referencia: 19-10-2026\n\nAntecedentes documentados.';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
class Node{
 constructor(tag='div'){this.tag=tag;this.children=[];this.events={};this.hidden=false;this.value='';this.textContent='';this.disabled=false;this.attributes={};}
 append(...nodes){for(const node of nodes)this.children.push(...(node.tag==='#fragment'?node.children:[node]));}
 replaceChildren(...nodes){this.children=[];this.append(...nodes);}
 addEventListener(type,fn){this.events[type]=fn;}
 setAttribute(key,value){this.attributes[key]=value;}
 focus(){this.focused=true;}select(){this.selected=true;}
}
function setup({read,clipboard=async()=>{},patients=[patient]}={}){
 const nodes=new Map(),copies=[],events={},get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
 const doc={hidden:false,getElementById:get,createElement:tag=>new Node(tag),createDocumentFragment:()=>new Node('#fragment'),addEventListener:(type,fn)=>{events[type]=fn;}};
 const reads=[];const response=()=>({id:document.id,sha256:document.sha256,text:body,status:'current',name:patient.name,rut:patient.rut});
 const chrome={runtime:{sendMessage:async message=>{
  if(message.type==='nexo.library.list')return {ok:true,result:{version:1,available:true,patients,issues:0}};
  if(message.type==='nexo.library.read'){reads.push(message);return {ok:true,result:await(read?read(message):response())};}
  return {ok:true,result:{opened:true}};
 }},tabs:{onActivated:{addListener:fn=>events.tab=fn}}};
 const ctx={ClinicalCatalog:catalog,chrome,document:doc,location:{search:''},URLSearchParams,TextEncoder,TextDecoder,Uint8Array,crypto:webcrypto,
  NexoDriveLibrary:{savedHandle:async()=>undefined},navigator:{clipboard:{writeText:async text=>{copies.push(text);await clipboard(text);}}},window:{document:doc,addEventListener:(type,fn)=>events[type]=fn}};
 vm.createContext(ctx);vm.runInContext(script,ctx);
 return {$:get,copies,reads,events,doc,ctx,async open(){get('tab-library').events.click();await tick();await tick();},async patient(){get('patient-list').children[0].children[0].events.click();await tick();await tick();},async copy(){await get('copy-summary').events.click();}};
}
test('elegir paciente muestra texto y copiar exige nueva comprobación; no copia al abrir',async()=>{
 const ui=setup();await ui.open();await ui.patient();assert.equal(ui.$('summary-text').value,body);assert.equal(ui.copies.length,0);assert.equal(ui.reads.length,1);
 await ui.copy();assert.equal(ui.reads.length,2);assert.equal(ui.copies[0],body);assert.equal(ui.$('copy-status').textContent,'Copiado');
 ui.events.tab();assert.equal(ui.$('summary-text').value,'');assert.equal(ui.$('copy-summary').disabled,true);
});
test('copiar rechazado selecciona el texto sin afirmar éxito',async()=>{
 const ui=setup({clipboard:async()=>{throw Error('denied');}});await ui.open();await ui.patient();await ui.copy();
 assert.equal(ui.$('summary-text').selected,true);assert.match(ui.$('copy-status').textContent,/⌘C/);assert.doesNotMatch(ui.$('copy-status').textContent,/^Copiado/);
});
test('identidad equivocada o actualización pendiente impiden copiar',async()=>{
 for(const change of [{text:body.replace('11111111-1','22222222-2')},{status:'stale'}]){
  const ui=setup({read:async()=>({id:document.id,sha256:document.sha256,text:body,status:'current',...change})});await ui.open();await ui.patient();
  assert.equal(ui.$('copy-summary').disabled,true);assert.equal(ui.copies.length,0);
 }
});
test('respuesta tardía no repone el paciente después de cambiar de mundo',async()=>{
 let finish;const waiting=new Promise(resolve=>finish=resolve),ui=setup({read:()=>waiting});
 await ui.open();ui.$('patient-list').children[0].children[0].events.click();ui.$('tab-request').events.click();
 finish({id:document.id,sha256:document.sha256,text:body,status:'current'});await tick();await tick();
 assert.equal(ui.$('summary-text').value,'');assert.equal(ui.copies.length,0);
});
test('el texto modificado entre vista y copia no llega al portapapeles',async()=>{
 let calls=0;const ui=setup({read:async()=>({id:document.id,sha256:++calls===1?document.sha256:'c'.repeat(64),text:body,status:'current'})});
 await ui.open();await ui.patient();await ui.copy();assert.equal(ui.copies.length,0);assert.equal(ui.$('summary-text').value,'');assert.equal(ui.$('copy-summary').disabled,true);
});
test('volver desde la conexión de Drive recupera la lista y sus controles',async()=>{
 const ui=setup();await ui.open();ui.$('connect-drive').events.click();assert.equal(ui.$('drive-setup').hidden,false);
 ui.$('cancel-drive').events.click();await tick();await tick();
 assert.equal(ui.$('drive-setup').hidden,true);assert.equal(ui.$('library-list-view').hidden,false);
 assert.equal(ui.$('patient-list').children.length,1);assert.equal(ui.$('refresh-library').disabled,false);
});
