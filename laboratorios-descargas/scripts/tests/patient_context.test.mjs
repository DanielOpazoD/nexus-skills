import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import {readFile} from 'node:fs/promises';
const core=await readFile(new URL('../../chrome-bridge/agenda_core.js',import.meta.url),'utf8'),code=await readFile(new URL('../../chrome-bridge/patient_context.js',import.meta.url),'utf8');
function setup({headers=[{name:'Paciente Ficticio',rut:'11.111.111-1'}],url='https://clinicohangaroa.eloisa.cl/main/ficha'}={}){
 const requests=[];const ctx={URL,chrome:{tabs:{query:async args=>{requests.push(args);return [{id:4,url}];}},scripting:{executeScript:async args=>{requests.push(args.target);return [{result:headers}];}}}};
 vm.createContext(ctx);vm.runInContext(core+'\n'+code,ctx);return {ctx,requests};
}
test('sugerir exige una sola identidad de paciente con nombre y RUT válido',async()=>{
 const {ctx}=setup();assert.equal((await ctx.currentPatient()).patient.rut,'11111111-1');
 for(const headers of [[],[{name:'Paciente Ficticio',rut:'11111111-2'}],[{name:'Paciente Ficticio',rut:'11111111-1'},{name:'Otra Persona',rut:'22222222-2'}]])assert.equal(setup({headers}).ctx.normalizePatientRows(headers),null);
});
test('no elige otra pestaña de Eloísa cuando la activa pertenece a otro sitio',async()=>{
 const {ctx,requests}=setup({url:'https://otro.invalid/main'});assert.equal((await ctx.currentPatient()).patient,null);assert.equal(requests.length,1);
});
test('el lector sólo usa filas del componente de paciente y omite elementos ocultos',()=>{
 const {ctx}=setup();let label='RUN',hidden=false;
 const value={textContent:'11.111.111-1',getClientRects:()=>[{}]},region={querySelectorAll:()=>[{textContent:label,parentElement:{querySelector:()=>value}}]};
 const name={textContent:'Paciente Ficticio',getClientRects:()=>hidden?[]:[{}],closest:selector=>selector.includes('[hidden]')?null:{parentElement:{parentElement:region}}};
 ctx.document={querySelectorAll:selector=>{assert.equal(selector,'.patient-name-div');return [name];}};ctx.getComputedStyle=()=>({visibility:'visible'});
 assert.equal(ctx.patientHeaderRows().length,1);label='Profesional';assert.equal(ctx.patientHeaderRows().length,0);label='RUN';hidden=true;assert.equal(ctx.patientHeaderRows().length,0);
});
