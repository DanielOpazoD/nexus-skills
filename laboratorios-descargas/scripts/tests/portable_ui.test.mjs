import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';
const packetCode=await readFile(new URL('../../assets/request_packet.js',import.meta.url),'utf8');
const controllerCode=await readFile(new URL('../../assets/portable_app.js',import.meta.url),'utf8');
function setup(writeText) {
  const nodes=new Map(),listeners={};
  const $=id=>{
    if (!nodes.has(id)) nodes.set(id,{disabled:false,hidden:true,value:'',textContent:'',open:false,focus(){this.focused=true;},select(){this.selected=true;},addEventListener(type,fn){listeners[id+':'+type]=fn;}});
    return nodes.get(id);
  };
  const form={addEventListener(type,fn){listeners['form:'+type]=fn;}};
  const selection={schema:2,ruts:['11111111-1'],source:'rayen',period:'3m',sourcePeriods:{rayen:'10y'},deliveryModel:'documents',eloisaScope:'medicos',mmradMode:'reports',mmradImageTypes:[],merge:false,patientMerge:false};
  const ctx={$,form,navigator:{clipboard:writeText?{writeText}:undefined},crypto:webcrypto,updatePeriod(){},updateFields(){},requestSelection:()=>selection};
  vm.createContext(ctx);vm.runInContext(packetCode+'\n'+controllerCode,ctx);
  return {$,listeners,selection,submit:()=>listeners['form:submit']({preventDefault(){}})};
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
