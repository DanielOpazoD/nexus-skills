import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const read=name=>readFile(new URL('../../'+name,import.meta.url),'utf8');
const core=await read('assets/agenda_core.js');
const worker=(await read('chrome-bridge/agenda_worker.js'))+'\n'+(await read('chrome-bridge/worker.js'));
const ctx={};vm.runInNewContext(core,ctx);const A=ctx.ClinicalAgenda;
const identity={officerId:777,nodeId:5576},date='2026-10-19';
const row=(changes={})=>({Id:1,FechaHoraInicio:'20261019 090000',UsuarioAps:{Id:10,Rut:'11111111-1',NombreFormateado:'Paciente de prueba'},Tag:{Nombre:'Confirmada'},...changes});
const normalize=rows=>A.normalize(rows,date,identity);
test('contexto requiere prestador y establecimiento inequívocos; nunca usa IDs genéricos',()=>{
  assert.equal(A.context({idNodo:5576,usuario:{IdFuncionarioPrestador:777}}).officerId,777);
  for(const session of [{id:777,idNodo:5576},{idFuncionario:777,idNodo:1},{idFuncionario:777,idPrestador:888,idNodo:5576},{idFuncionarioRegistrador:777,idNodoOrigen:5576}]) assert.throws(()=>A.context(session));
});
test('URL de un día exacto y fecha calendario válida',()=>{
  assert.match(A.url(date,identity),/FechaHoraInicio=20261019%20000000;FechaHoraTermino=20261019%20235959;IdsDeRecursos=777/);
  for(const value of ['2026-02-29','2026-13-01','19-10-2026','2026-10-19;IdsDeRecursos=1']) assert.throws(()=>A.day(value));
  assert.equal(A.day('2024-02-29'),'2024-02-29');assert.throws(()=>A.url(date,{officerId:1,nodeId:1}));
});
test('duplicados se agrupan; homónimos con RUT diferente permanecen separados',()=>{
  const r=normalize([row(),row(),row({Id:2,FechaHoraInicio:'20261019 110000'}),row({Id:3,UsuarioAps:{Id:11,Rut:'22222222-2',NombreFormateado:'Paciente de prueba'}})]);
  assert.equal(r.patients.length,2);assert.equal(r.patients[0].times.length,2);assert.equal(r.patients[0].appointmentIds.length,2);assert.equal(r.status,'complete');
  assert.ok(r.patients.every(p=>p.selectable));assert.equal('patientId' in r.patients[0],false);
});
test('fecha, RUT, establecimiento o prestador incorrectos dan parcial sin descartar los válidos',()=>{
  const r=normalize([row(),row({Id:2,FechaHoraInicio:'20261018 090000'}),row({Id:3,IdNodo:1}),row({Id:4,IdFuncionarioPrestador:888}),row({Id:5,UsuarioAps:{Id:10,Rut:'11111111-2',NombreFormateado:'Otro'}})]);
  assert.equal(r.patients.length,1);assert.equal(r.rejected,4);assert.equal(r.status,'partial');assert.equal(r.patients[0].selectable,true);
});
test('identidad o cita contradictoria se bloquea; incluye cambio de estado del mismo ID',()=>{
  const variants=[row({Id:2,UsuarioAps:{Id:10,Rut:'11111111-1',NombreFormateado:'Otra persona'}}),row({UsuarioAps:{Id:11,Rut:'22222222-2',NombreFormateado:'Otra persona'}}),row({Tag:{Nombre:'Anulada'}})];
  for(const variant of variants){const r=normalize([row(),variant]);assert.equal(r.status,'partial');assert.ok(r.patients.every(p=>!p.selectable));}
});
test('anuladas no seleccionables; una cita activa distinta sí permite el paciente',()=>{
  assert.equal(normalize([row({EsAnulado:true})]).patients[0].selectable,false);
  assert.equal(normalize([row({Tag:{Nombre:'Anulada'}}),row({Id:2})]).patients[0].selectable,true);
  assert.equal(normalize([]).patients.length,0);
  assert.throws(()=>normalize({items:[row()]}));
});
async function transport({sender,session={idFuncionario:777,idNodo:5576},status=200,body=[row()],message={},contentType='application/json'}={}) {
  let listener;const requests=[],tabs=[];
  const chrome={runtime:{id:'fixture',getURL:p=>'chrome-extension://fixture/'+p,onMessage:{addListener:fn=>listener=fn}},
    action:{onClicked:{addListener(){}}},tabs:{query:async()=>[{id:7,url:'https://clinicohangaroa.eloisa.cl/main'}],create:async value=>tabs.push(value)},
    scripting:{executeScript:async({func})=>[{result:vm.runInNewContext('('+func.toString()+')()', {localStorage:{getItem:()=>JSON.stringify({accessToken:'test-secret',...session})}})}]}};
  const context={chrome,URL,AbortSignal,TextDecoder,Uint8Array,importScripts(){},fetch:async(url,options)=>{requests.push({url,options});return new Response(JSON.stringify(body),{status,headers:{'content-type':contentType}});}};
  vm.runInNewContext(core+'\n'+worker,context);
  const result=await new Promise(resolve=>{if(!listener({type:'labs.agenda',id:'a'.repeat(32),date,...message},sender??{url:'chrome-extension://fixture/request/index.html',id:'fixture'},resolve))resolve(null);});
  return {result,requests};
}
test('transporte devuelve sólo agenda normalizada; token nunca llega al formulario',async()=>{
  const r=await transport({body:[row({Telefono:'private-phone',Motivo:'private-reason'})]});
  assert.equal(r.requests.length,1);assert.equal(r.result.ok,true);assert.equal(r.requests[0].options.headers.Authorization,'Bearer test-secret');
  assert.doesNotMatch(JSON.stringify(r.result),/test-secret|private-phone|private-reason/);
});
test('rechaza emisor ajeno, subframe y petición con campos adicionales antes de consultar',async()=>{
  for(const sender of [{url:'https://evil.invalid/',id:'fixture'},{url:'chrome-extension://other/request/index.html',id:'other'},{url:'http://127.0.0.1:8765/',frameId:1}]){
    const r=await transport({sender});assert.equal(r.requests.length,0);assert.equal(r.result,null);
  }
  for(const message of [{date:'2026-02-30'},{officerId:1}]){const r=await transport({message});assert.equal(r.requests.length,0);assert.equal(r.result.ok,false);}
});
test('sesión vencida, contexto ambiguo y respuesta inesperada no generan agenda vacía exitosa',async()=>{
  for(const options of [{status:401},{session:{idFuncionario:777,idNodo:1}},{contentType:'text/html'},{body:{error:'failure'}}]){
    const r=await transport(options);assert.equal(r.result.ok,false);assert.doesNotMatch(JSON.stringify(r.result),/test-secret/);
  }
});

test('sesión real: nodo y funcionarioPrestador serializados; no adopta el id de otros objetos',async()=>{
  const r=await transport({session:{nodo:JSON.stringify({id:5576}),funcionarioPrestador:JSON.stringify({id:777}),otraEntidad:{id:999}}});
  assert.equal(r.result.ok,true);assert.match(r.requests[0].url,/IdsDeRecursos=777/);
  const bad=await transport({session:{nodo:JSON.stringify({id:5576}),funcionarioPrestador:'invalid'}});assert.equal(bad.result.ok,false);assert.equal(bad.requests.length,0);
});
test('citas grupales y contexto ajeno quedan pendientes; estados anulados estructurados se respetan',()=>{
  const r=normalize([row(),row({Id:2,EsGrupal:true}),row({Id:3,Nodo:{Id:1}}),row({Id:4,FuncionarioPrestador:{Id:888}})]);
  assert.equal(r.rejected,3);assert.equal(r.patients.length,1);
  for(const changes of [{Tag:{EsAnulado:true}},{EsBorrado:true},{Tag:{EsBloqueado:true}}]) assert.equal(normalize([row(changes)]).patients[0].selectable,false);
});
