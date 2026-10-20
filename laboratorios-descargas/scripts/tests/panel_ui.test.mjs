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
function setup({read,clipboard=async()=>{},patients=[patient],context=()=>null,drive=null,check}={}){
 const timers=new Map(),nodes=new Map(),copies=[],events={},get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
 const doc={hidden:false,getElementById:get,createElement:tag=>new Node(tag),createDocumentFragment:()=>new Node('#fragment'),addEventListener:(type,fn)=>{events[type]=fn;}};
 const reads=[],requests=[];const response=()=>({id:document.id,sha256:document.sha256,text:body,status:'current',name:patient.name,rut:patient.rut});
 const chrome={runtime:{id:'fixture',onMessage:{addListener:fn=>events.message=fn},sendMessage:async message=>{
  if(message.type==='nexo.library.list')return {ok:true,result:{version:1,available:true,patients:check&&requests.length?await Promise.all(patients.map(p=>check(p.id))):patients,issues:0}};
  requests.push(message);
  if(message.type==='nexo.patient.context')return {ok:true,result:{patient:context()}};
  if(message.type==='nexo.library.read'){reads.push(message);return {ok:true,result:await(read?read(message):response())};}
  return {ok:true,result:{opened:true}};
 }},tabs:{onActivated:{addListener:fn=>events.tab=fn}}};
 const ctx={ClinicalCatalog:catalog,chrome,document:doc,location:{search:''},URLSearchParams,setInterval:(fn,ms)=>{timers.set(ms,fn);return ms;},clearInterval:ms=>timers.delete(ms),TextEncoder,TextDecoder,Uint8Array,crypto:webcrypto,
  NexoDriveLibrary:{savedHandle:async()=>drive,DriveLibrary:class{async list(){return {version:1,available:true,patients,issues:0};}async patient(id){return check?check(id):patients.find(p=>p.id===id);}}},navigator:{clipboard:{writeText:async text=>{copies.push(text);await clipboard(text);}}},window:{document:doc,addEventListener:(type,fn)=>events[type]=fn}};
 vm.createContext(ctx);vm.runInContext(script,ctx);
 return {$:get,copies,reads,requests,events,doc,ctx,timers,async open(){get('tab-library').events.click();await tick();await tick();},async patient(){get('patient-list').children[0].children[0].events.click();await tick();await tick();},async copy(){await get('copy-summary').events.click();}};
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
 await ui.open();await ui.patient();await ui.copy();assert.equal(ui.copies.length,0);assert.equal(ui.$('summary-text').value,body);assert.equal(ui.$('copy-summary').disabled,true);assert.match(ui.$('summary-notice-text').textContent,/conservado/);
});
test('volver desde la conexión de Drive recupera la lista y sus controles',async()=>{
 const ui=setup();await ui.open();ui.$('connect-drive').events.click();assert.equal(ui.$('drive-setup').hidden,false);
 ui.$('cancel-drive').events.click();await tick();await tick();
 assert.equal(ui.$('drive-setup').hidden,true);assert.equal(ui.$('library-list-view').hidden,false);
 assert.equal(ui.$('patient-list').children.length,1);assert.equal(ui.$('refresh-library').disabled,false);
});
test('usar ficha requiere coincidencia y cambiarla antes de copiar bloquea el texto anterior',async()=>{
 let current={name:patient.name,rut:patient.rut};const ui=setup({context:()=>current});await ui.open();assert.equal(ui.$('use-current-patient').hidden,false);
 await ui.$('use-current-patient').events.click();await tick();await tick();assert.equal(ui.$('summary-text').value,body);
 current={name:'Otra Persona',rut:'22222222-2'};await ui.copy();assert.equal(ui.copies.length,0);assert.equal(ui.$('summary-text').value,'');assert.match(ui.$('summary-status').textContent,/ficha cambió/);
});
test('abrir expediente es una acción explícita, independiente de leer o copiar',async()=>{
 const ui=setup({patients:[{...patient,openable:true}]});await ui.open();await ui.patient();
 assert.equal(ui.requests.some(r=>r.type==='nexo.library.open'),false);assert.equal(ui.$('open-patient-folder').hidden,false);
 await ui.$('open-patient-folder').events.click();assert.equal(ui.requests.some(r=>r.type==='nexo.library.open'),true);assert.equal(ui.copies.length,0);
});

test('Drive muestra procedencia y reconecta el permiso recordado sin elegir otra carpeta',async()=>{
 let granted=false,requests=0;const handle={async queryPermission(){return granted?'granted':'prompt';},async requestPermission(options){assert.equal(options.mode,'read');requests++;granted=true;return 'granted';}};
 const ui=setup({drive:handle});await ui.open();assert.match(ui.$('library-origin').textContent,/Mini/);
 await ui.$('connect-drive').events.click();assert.equal(ui.$('reconnect-drive').hidden,false);
 await ui.$('reconnect-drive').events.click();await tick();await tick();
 assert.equal(requests,1);assert.match(ui.$('library-origin').textContent,/Drive/);assert.equal(ui.$('drive-setup').hidden,true);
});
test('volver a Resúmenes actualiza la biblioteca sin restaurar texto oculto',async()=>{
 const ui=setup();await ui.open();await ui.patient();ui.doc.hidden=true;ui.events.visibilitychange();
 assert.equal(ui.$('summary-text').value,'');ui.doc.hidden=false;ui.events.visibilitychange();await tick();await tick();
 assert.equal(ui.$('library-list-view').hidden,false);assert.equal(ui.$('patient-list').children.length,1);assert.equal(ui.$('summary-text').value,'');
});

test('la ficha coincidente abre automáticamente sin copiar y un cambio limpia antes de releer',async()=>{
 let current={name:patient.name,rut:patient.rut};const ui=setup({context:()=>current});await ui.open();await tick();
 assert.equal(ui.$('summary-view').hidden,false);assert.equal(ui.$('summary-text').value,body);assert.equal(ui.copies.length,0);
 current={name:'Otro Ficticio',rut:'22222222-2'};
 ui.events.message({type:'nexo.patient.invalidated'},{id:'fixture'});
 assert.equal(ui.$('summary-text').value,'');await tick();await tick();assert.equal(ui.$('summary-view').hidden,true);
});
test('la selección manual no es reemplazada por un sondeo de la misma ficha',async()=>{
 const ui=setup({context:()=>({name:patient.name,rut:patient.rut})});await ui.open();await tick();
 ui.$('change-patient').events.click();await ui.timers.get(2000)();await tick();
 assert.equal(ui.$('library-list-view').hidden,false);assert.equal(ui.$('summary-text').value,'');
});
test('cambiar de paciente durante la lectura o comprobación final impide mostrar o copiar el anterior',async()=>{
 for(const duringCopy of [false,true]){
  let current={name:patient.name,rut:patient.rut},calls=0;
  const ui=setup({context:()=>current,read:async()=>{
   if(++calls===(duringCopy?2:1))current={name:'Otro Ficticio',rut:'22222222-2'};
   return {id:document.id,sha256:document.sha256,text:body,status:'current'};
  }});
  await ui.open();await tick();if(duringCopy)await ui.copy();
  assert.equal(ui.$('summary-text').value,'');assert.equal(ui.copies.length,0);assert.equal(ui.$('copy-summary').disabled,true);
 }
});
test('un mensaje de un sitio o un remitente ajeno no invalida la vista',async()=>{
 const ui=setup();await ui.open();await ui.patient();
 for(const sender of [{id:'other'},{id:'fixture',tab:{id:2}}])ui.events.message({type:'nexo.patient.invalidated'},sender);
 assert.equal(ui.$('summary-text').value,body);
});

test('una nueva versión avisa sin reemplazar texto ni posición; sólo se aplica al pulsar',async()=>{
 let newer=false;
 const nextDoc={...document,id:'c'.repeat(64),sha256:'d'.repeat(64),date:'21-10-2026'},nextBody=body+'\nNueva evaluación documentada.';
 const ui=setup({check:()=>({...patient,documents:[newer?nextDoc:document]}),read:async message=>({id:message.id,sha256:message.sha256,text:message.id===nextDoc.id?nextBody:body,status:'current'})});
 await ui.open();await ui.patient();await ui.copy();assert.equal(ui.$('copy-status').textContent,'Copiado');ui.$('summary-text').scrollTop=123;newer=true;
 await ui.timers.get(15000)();await tick();
 assert.equal(ui.$('summary-text').value,body);assert.equal(ui.$('summary-text').scrollTop,123);assert.equal(ui.$('patient-name').textContent,patient.name);
 assert.equal(ui.$('summary-notice-text').textContent,'Nuevo resumen disponible');assert.equal(ui.$('copy-status').textContent,'');assert.equal(ui.$('copy-summary').disabled,true);
 await ui.$('apply-update').events.click();await tick();await tick();
 assert.equal(ui.$('summary-text').value,nextBody);assert.equal(ui.$('summary-notice').hidden,true);assert.equal(ui.$('copy-summary').disabled,false);assert.equal(ui.copies.length,1);
});
test('desconexión conserva texto y ofrece reconectar; no afirma que haya una versión nueva',async()=>{
 let failing=false;const drive={queryPermission:async()=> 'granted'};
 const ui=setup({drive,check:()=>{if(failing)throw Error('Permiso revocado');return patient;}});
 // El doble de Drive usa lectura explícita para probar la recuperación del panel.
 ui.ctx.NexoDriveLibrary.DriveLibrary.prototype.read=async()=>({id:document.id,sha256:document.sha256,text:body,status:'current'});
 await ui.open();await ui.patient();failing=true;
 await ui.timers.get(15000)();assert.equal(ui.$('summary-text').value,body);assert.equal(ui.$('copy-summary').disabled,true);
 assert.equal(ui.$('summary-reconnect').hidden,false);assert.doesNotMatch(ui.$('summary-notice-text').textContent,/Nuevo resumen/);
});
test('un sondeo tardío de otra selección no muestra avisos ni restaura texto',async()=>{
 let finish;const ui=setup({check:()=>new Promise(resolve=>finish=resolve)});await ui.open();await ui.patient();
 const checking=ui.timers.get(15000)();ui.$('tab-request').events.click();finish({...patient,documents:[]});await checking;
 assert.equal(ui.$('summary-text').value,'');assert.equal(ui.$('summary-notice').hidden,true);
});

test('cambiar la ficha durante una copia manual también invalida la selección anterior',async()=>{
 let current=null,calls=0;const ui=setup({context:()=>current,read:async message=>{
  if(++calls===2)current={name:'Otro Ficticio',rut:'22222222-2'};
  return {id:document.id,sha256:document.sha256,text:body,status:'current'};
 }});await ui.open();await ui.patient();await ui.copy();
 assert.equal(ui.copies.length,0);assert.equal(ui.$('summary-text').value,'');assert.equal(ui.$('copy-summary').disabled,true);
});
