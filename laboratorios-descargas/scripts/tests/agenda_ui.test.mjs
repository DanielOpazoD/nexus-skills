import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';
const code=await readFile(new URL('../../assets/agenda_ui.js',import.meta.url),'utf8');
function setup(){
  class Node {
    constructor(){this.value='';this.children=[];this.listeners={};this.dataset={};}
    addEventListener(type,fn){this.listeners[type]=fn;}
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this.children=children.flatMap(c=>c.fragment?c.children:[c]);}
    setAttribute(k,v){this[k]=v;}
    querySelectorAll(){return this.children.flatMap(n=>n.children).filter(n=>n.type==='checkbox'&&!n.disabled);}
    dispatchEvent(e){this.listeners[e.type]?.(e);}
    focus(){}
  }
  const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
  const buttons=['manual','agenda'].map(value=>{const n=new Node();n.dataset.patientMode=value;return n;});
  const pending=[],timers=new Map();let next=1;
  const ctx={location:{protocol:'chrome-extension:'},chrome:{runtime:{id:'fixture',sendMessage:msg=>new Promise(resolve=>pending.push({msg,resolve}))}},
    document:{getElementById:get,querySelectorAll:()=>buttons,createElement:()=>new Node(),createDocumentFragment:()=>Object.assign(new Node(),{fragment:true})},
    window:{addEventListener(){}},ClinicalRequest:{displayDate:v=>v.split('-').reverse().join('-'),referenceDate:()=> '2026-10-20'},ClinicalAgenda:{day:v=>v},crypto:webcrypto,Uint8Array,Event,
    setTimeout:fn=>{const id=next++;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(code,ctx);
  const result=(date='2026-10-20')=>({ok:true,result:{date,identity:{officerId:1},patients:[{rut:'11111111-1',name:'Prueba Uno',states:[],times:['09:00'],selectable:true},{rut:'22222222-2',name:'Prueba Dos',states:['Anulada'],times:['10:00'],selectable:false}],status:'complete'}});
  return{get,pending,result,buttons,timers};
}
test('agenda no preselecciona ni ejecuta; selección conserva RUT escritos y deduplica',async()=>{
  const ui=setup();const loading=ui.get('agenda-load').listeners.click();ui.pending[0].resolve(ui.result());await loading;
  assert.equal(ui.get('agenda-apply').disabled,true);assert.equal(ui.get('ruts').value,'');
  ui.get('agenda-all').checked=true;ui.get('agenda-all').listeners.change();
  assert.equal(ui.get('agenda-apply').textContent,'Agregar 1 paciente(s)');
  ui.get('ruts').value='11.111.111-1\n33333333-3';let changes=0;ui.get('ruts').addEventListener('input',()=>changes++);
  ui.get('agenda-apply').listeners.click();assert.equal(ui.get('ruts').value,'11111111-1\n33333333-3');assert.equal(changes,1);assert.equal(ui.get('agenda-panel').hidden,true);
});
test('cambiar fecha invalida respuesta en vuelo y vacía selección visible',async()=>{
  const ui=setup();const loading=ui.get('agenda-load').listeners.click();ui.get('agenda-date').value='2026-10-21';ui.get('agenda-date').listeners.change();
  ui.pending[0].resolve(ui.result());await loading;assert.equal(ui.get('agenda-results').hidden,true);assert.equal(ui.get('agenda-rows').children.length,0);assert.equal(ui.get('agenda-apply').disabled,true);
});
test('reintento fallido conserva lista y selección de la misma fecha',async()=>{
  const ui=setup();let loading=ui.get('agenda-load').listeners.click();ui.pending[0].resolve(ui.result());await loading;
  ui.get('agenda-all').checked=true;ui.get('agenda-all').listeners.change();loading=ui.get('agenda-load').listeners.click();ui.pending[1].resolve({ok:false,error:'Sesión vencida'});await loading;
  assert.equal(ui.get('agenda-apply').disabled,false);assert.equal(ui.get('agenda-rows').children.length,2);assert.match(ui.get('agenda-status').textContent,/conserva/);
});
test('timeout libera control e ignora una respuesta tardía',async()=>{
  const ui=setup();const loading=ui.get('agenda-load').listeners.click();[...ui.timers.values()][0]();
  assert.equal(ui.get('agenda-load').disabled,false);ui.pending[0].resolve(ui.result());await loading;assert.equal(ui.get('agenda-rows').children.length,0);
});
