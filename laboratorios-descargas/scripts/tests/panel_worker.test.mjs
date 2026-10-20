import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import {readFile} from 'node:fs/promises';
const root=new URL('../../chrome-bridge/',import.meta.url);
const code=(await readFile(new URL('panel_worker.js',root),'utf8'))+'\n'+(await readFile(new URL('worker.js',root),'utf8'));
function setup({failOpen=false,failFetch=false,status=200,raw=null,contentType='application/json',fetchError=null}={}){
 let listener,action;const opened=[],requests=[],tabs=[],broadcasts=[];
 const chrome={runtime:{id:'fixture',sendMessage:async message=>broadcasts.push(message),getURL:path=>'chrome-extension://fixture/'+path,onMessage:{addListener:fn=>listener=fn}},
   action:{onClicked:{addListener:fn=>action=fn}},tabs:{query:async()=>[{id:7}],create:async arg=>tabs.push(arg)},
   sidePanel:{open:arg=>{opened.push(arg);return failOpen?Promise.reject(Error('private error')):Promise.resolve();}}};
 const ctx={chrome,importScripts(){},URL,AbortSignal,fetch:async(url,options)=>{
   requests.push({url,options});if(fetchError)throw fetchError;if(failFetch)throw Error('private-token-error');
   return new Response(raw??JSON.stringify({version:1,patients:[],available:true}),{status,headers:{'content-type':contentType}});
 }};vm.runInNewContext(code,ctx);
 return {opened,requests,tabs,broadcasts,action:tab=>action(tab),message:(message,sender)=>new Promise(resolve=>{const keep=listener(message,sender,result=>resolve(result));if(!keep)resolve(null);})};
}
const panel={id:'fixture',url:'chrome-extension://fixture/panel/index.html'};
test('el círculo abre el panel sólo desde Eloísa y el frame principal',async()=>{
 const ui=setup();const good={id:'fixture',url:'https://clinicohangaroa.eloisa.cl/main',frameId:0,tab:{id:7}};
 assert.equal((await ui.message({type:'nexo.panel.open'},good)).ok,true);assert.equal(ui.opened[0].tabId,7);
 for(const sender of [{...good,url:'https://evil.invalid/main'},{...good,frameId:1},{...good,id:'other'},{...good,url:'https://clinicohangaroa.eloisa.cl/login'}])assert.equal(await ui.message({type:'nexo.panel.open'},sender),null);
 assert.equal(await ui.message({type:'nexo.panel.open',tabId:9},good),null);assert.equal(ui.opened.length,1);
});
test('la barra de Chrome abre panel y dispone de una pestaña como alternativa',async()=>{
 const ui=setup();await ui.action({id:7});assert.equal(ui.opened.length,1);assert.equal(ui.tabs.length,0);
 const fallback=setup({failOpen:true});await fallback.action({id:7});assert.equal(fallback.tabs[0].url,'chrome-extension://fixture/panel/index.html');
});
test('el sitio y otras páginas no pueden solicitar la biblioteca',async()=>{
 const ui=setup();
 for(const sender of [{id:'fixture',url:'https://clinicohangaroa.eloisa.cl/main'},{id:'other',url:'chrome-extension://other/panel/index.html'},{id:'fixture',url:'chrome-extension://fixture/request/index.html'},{}])assert.equal(await ui.message({type:'nexo.library.list'},sender),null);
 assert.equal(ui.requests.length,0);
 assert.equal((await ui.message({type:'nexo.library.list'},panel)).ok,true);assert.equal(ui.requests[0].url,'http://127.0.0.1:8765/api/library');
 assert.equal(ui.requests[0].options.redirect,'error');assert.equal(ui.requests[0].options.credentials,'omit');
});
test('las rutas son fijas: rechaza URL libre, traversal y campos extra',async()=>{
 const ui=setup();
 for(const message of [{type:'nexo.library.list',url:'https://evil.invalid/'},{type:'nexo.library.read',id:'../secret',sha256:'a'.repeat(64)},{type:'nexo.library.read',id:'a'.repeat(64),sha256:'bad'}])assert.equal((await ui.message(message,panel)).ok,false);
 assert.equal(ui.requests.length,0);
 assert.equal((await ui.message({type:'nexo.library.read',id:'a'.repeat(64),sha256:'b'.repeat(64)},panel)).ok,true);
 assert.match(ui.requests[0].url,/^http:\/\/127\.0\.0\.1:8765\/api\/library\/read\?id=a+&sha256=b+$/);
});
test('errores locales no filtran detalles y abrir la vista no transmite pacientes por URL',async()=>{
 const ui=setup({failFetch:true});const failed=await ui.message({type:'nexo.library.list'},panel);
 assert.equal(failed.ok,false);assert.doesNotMatch(JSON.stringify(failed),/private-token/);
 const tab=setup();await tab.message({type:'nexo.panel.tab',view:'library'},panel);
 assert.equal(tab.tabs[0].url,'chrome-extension://fixture/panel/index.html?view=library');
});
test('salud del Mini sólo accesible desde el panel propio y con ruta fija',async()=>{
 const ui=setup();assert.equal((await ui.message({type:'nexo.worker.health'},panel)).ok,true);
 assert.equal(ui.requests[0].url,'http://127.0.0.1:8765/api/health');
 assert.equal(await ui.message({type:'nexo.worker.health'},{id:'fixture',url:'https://clinicohangaroa.eloisa.cl/main'}),null);
});
test('abrir expediente admite sólo ID y permiso efímero del panel propio',async()=>{
 const ui=setup();const request={type:'nexo.library.open',id:'a'.repeat(64),token:'b'.repeat(43)};
 assert.equal((await ui.message(request,panel)).ok,true);assert.equal(ui.requests[0].url,'http://127.0.0.1:8765/api/library/open');
 assert.equal(ui.requests[0].options.method,'POST');assert.equal(JSON.parse(ui.requests[0].options.body).token,request.token);
 assert.equal((await ui.message({...request,path:'/private/elsewhere'},panel)).ok,false);
 assert.equal(await ui.message(request,{id:'fixture',url:'https://clinicohangaroa.eloisa.cl/main'}),null);
});

test('sólo un cambio de la pestaña activa oficial se retransmite al panel, sin identidad',async()=>{
 const ui=setup(),sender={id:'fixture',url:'https://clinicohangaroa.eloisa.cl/main',frameId:0,tab:{id:7}};
 assert.equal((await ui.message({type:'nexo.patient.changed'},sender)).ok,true);
 assert.equal(JSON.stringify(ui.broadcasts),JSON.stringify([{type:'nexo.patient.invalidated'}]));
 await ui.message({type:'nexo.patient.changed'},{...sender,tab:{id:8}});
 assert.equal(ui.broadcasts.length,1);
 assert.equal(await ui.message({type:'nexo.patient.changed',rut:'11111111-1'},sender),null);
 assert.equal(await ui.message({type:'nexo.patient.changed'},{...sender,url:'https://evil.invalid/main'}),null);
});

test('el puente distingue errores transitorios de permisos, versión y contenido sin filtrar respuesta',async()=>{
 for(const [status,code,retryable] of [[503,'unavailable',true],[401,'permission',false],[404,'incompatible',false],[400,'integrity',false]]){
  const ui=setup({status,raw:'PRIVATE-RESPONSE'}),result=await ui.message({type:'nexo.library.list'},panel);
  assert.equal(result.code,code);assert.equal(result.retryable,retryable);assert.doesNotMatch(JSON.stringify(result),/PRIVATE/);
 }
 for(const options of [{raw:'not-json'},{contentType:'text/html'}]){
  const result=await setup(options).message({type:'nexo.library.list'},panel);assert.equal(result.code,'integrity');assert.equal(result.retryable,false);
 }
 const timeout=await setup({fetchError:Object.assign(Error('PRIVATE'),{name:'TimeoutError'})}).message({type:'nexo.library.list'},panel);assert.equal(timeout.code,'timeout');assert.equal(timeout.retryable,true);
 const open=await setup({status:503}).message({type:'nexo.library.open',id:'a'.repeat(64),token:'b'.repeat(43)},panel);assert.equal(open.retryable,false);
});
