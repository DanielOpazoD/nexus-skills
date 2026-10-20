import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';
import {TextEncoder} from 'node:util';
const packetCode=await readFile(new URL('../../assets/request_packet.js',import.meta.url),'utf8');
const controllerCode=await readFile(new URL('../../assets/portable_app.js',import.meta.url),'utf8');
const transportCode=await readFile(new URL('../../assets/drive_status.js',import.meta.url),'utf8');
function setup(writeText) {
  const nodes=new Map(),listeners={};
  const $=id=>{
    if (!nodes.has(id)) nodes.set(id,{disabled:false,hidden:true,value:'',textContent:'',open:false,focus(){this.focused=true;},select(){this.selected=true;},addEventListener(type,fn){listeners[id+':'+type]=fn;}});
    return nodes.get(id);
  };
  const form={addEventListener(type,fn){listeners['form:'+type]=fn;}};
  const selection={schema:2,ruts:['11111111-1'],source:'rayen',period:'3m',sourcePeriods:{rayen:'10y'},deliveryModel:'documents',eloisaScope:'medicos',mmradMode:'reports',mmradImageTypes:[],merge:false,patientMerge:false};
  const ctx={$,form,window:{addEventListener(){}},AbortController,setTimeout,clearTimeout,navigator:{clipboard:writeText?{writeText}:undefined},crypto:webcrypto,TextEncoder,updatePeriod(){},updateFields(){},requestSelection:()=>selection};
  vm.createContext(ctx);vm.runInContext(transportCode+'\n'+packetCode+'\n'+controllerCode,ctx);
  return {$,listeners,selection,ctx,submit:()=>listeners['form:submit']({preventDefault(){}})};
}
test('copia rechazada o no disponible muestra texto seleccionable sin confirmar copia',async()=>{
  for (const writer of [undefined,async()=>{throw Error('denied');}]) {
    const ui=setup(writer);await ui.submit();
    assert.equal(ui.$('request-preview').open,true);
    assert.equal(ui.$('request-text').selected,true);
    assert.match(ui.$('request-text').value,/"rayen": "10y"/);
    assert.match(ui.$('copy-status').textContent,/⌘C/);
    assert.doesNotMatch(ui.$('copy-status').textContent,/^Copiada/);
  }
});
test('copia y vista previa reutilizan ID; una selección distinta cambia la solicitud',async()=>{
  const copies=[];const ui=setup(async text=>copies.push(text));
  await ui.submit();await ui.submit();assert.equal(copies[0],copies[1]);
  ui.selection.period='10y';await ui.submit();assert.notEqual(copies[2],copies[0]);
  assert.match(ui.$('copy-status').textContent,/^Copiada/);
});

test('Nuevo pedido crea otro ID aunque conserve la misma selección',async()=>{
  const copies=[];const ui=setup(async text=>copies.push(text));
  await ui.submit();ui.listeners['new-request:click']();await ui.submit();
  assert.notEqual(copies[0],copies[1]);
});
test('Drive escribe datos antes del marcador y rehúsa sobrescribir otro pedido con el mismo ID',async()=>{
  const ui=setup();const files=new Map(),events=[];
  const directory={name:'_Solicitudes Nexo',async getFileHandle(name,options){
    if (!files.has(name) && !options?.create) throw Object.assign(new Error('missing'),{name:'NotFoundError'});
    if (!files.has(name)) files.set(name,'');
    return {async getFile(){return {text:async()=>files.get(name)};},async createWritable(){let value='';return {
      async write(part){value+=part;},async close(){files.set(name,value);events.push(name);}
    };}};
  }};
  const packet=ui.ctx.ClinicalRequest.build(ui.selection,new Date('2026-10-20T16:00:00Z'),'a'.repeat(32));
  const digest=await ui.ctx.writeDriveRequest(directory,packet);
  assert.deepEqual(events,[`solicitud-${packet.id}.json`,`solicitud-${packet.id}.ready`]);
  assert.equal(files.get(`solicitud-${packet.id}.ready`).trim(),digest);
  assert.equal(await ui.ctx.writeDriveRequest(directory,packet),digest);
  const modified={...packet,request:{...packet.request,period:'10y'}};
  await assert.rejects(ui.ctx.writeDriveRequest(directory,modified),/ID ya existe/);
});
test('pedido ficticio recorre acuse y progreso hasta resumen sin declarar sincronización',async()=>{
 const ui=setup();ui.ctx.prepareRequest();const packet=vm.runInContext('prepared',ui.ctx),digest='b'.repeat(64),signal=new AbortController().signal;
 const files={};files[`acuse-${packet.id}.json`]={id:packet.id,sha256:digest,status:'imported'};
 files[`progreso-${packet.id}.json`]={version:1,kind:'nexo-request-progress',id:packet.id,sha256:digest,status:'summary_ready',
  observedAt:new Date().toISOString(),sourceCounts:{completed:1,pending:0,total:1},summary:{ready:1,total:1},fileCount:1,archive:{copy:'complete',sync:'pending'}};
 const acuses={getFileHandle:async name=>({getFile:async()=>({size:1000,text:async()=>JSON.stringify(files[name])})})};
 ui.ctx.NexoTransport.pause=async()=>{};
 await ui.ctx.awaitDriveReceipt({getDirectoryHandle:async()=>acuses},packet,digest,signal);
 assert.equal(ui.$('copy-status').textContent,'Resumen preparado · Drive por confirmar');
});
