import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import {readFile} from 'node:fs/promises';
const ctx={setTimeout,clearTimeout,Date,Intl};vm.createContext(ctx);vm.runInContext(await readFile(new URL('../../chrome-bridge/panel/connectivity.js',import.meta.url),'utf8'),ctx);
const N=ctx.NexoConnectivity;
test('lectura transitoria reintenta hasta tres veces con esperas crecientes',async()=>{
 let calls=0;const delays=[];
 const result=await N.read(async()=>{if(++calls<3)throw Object.assign(Error('fallo ficticio'),{code:'unavailable'});return 'verified';},{pause:async ms=>delays.push(ms)});
 assert.equal(result,'verified');assert.equal(calls,3);assert.deepEqual(delays,[300,900]);
 calls=0;await assert.rejects(N.read(async()=>{calls++;throw Object.assign(Error('fallo'),{code:'unavailable'});},{pause:async()=>{}}));assert.equal(calls,3);
});
test('permiso, integridad, incompatibilidad y error desconocido no se repiten',async()=>{
 for(const cause of [Object.assign(Error('permiso'),{name:'NotAllowedError'}),Object.assign(Error('integridad'),{code:'integrity',retryable:true}),Object.assign(Error('versión'),{code:'incompatible'}),SyntaxError('incompleto'),Error('fallo desconocido')]){
  let calls=0;await assert.rejects(N.read(async()=>{calls++;throw cause;},{pause:async()=>{throw Error('No debe esperar');}}));assert.equal(calls,1);
 }
});
test('timeout no cancelable no abre otra operación; timeout abortado por HTTP sí admite reintento',async()=>{
 let calls=0;await assert.rejects(N.read(()=>{calls++;return new Promise(()=>{});},{timeout:5,pause:async()=>{}}),error=>error.code==='timeout'&&error.retryable===false);assert.equal(calls,1);
 calls=0;assert.equal(await N.read(async()=>{if(++calls===1)throw Object.assign(Error('HTTP abortado'),{code:'timeout',retryable:true});return true;},{pause:async()=>{}}),true);assert.equal(calls,2);
});
test('cambiar de contexto durante la espera cancela los siguientes intentos',async()=>{
 let current=true,calls=0;
 await assert.rejects(N.read(async()=>{calls++;throw Object.assign(Error('temporal'),{code:'unavailable'});},{isCurrent:()=>current,pause:async()=>{current=false;}}),error=>error.code==='cancelled');assert.equal(calls,1);
 let finish;current=true;const pending=N.read(()=>new Promise(resolve=>finish=resolve),{isCurrent:()=>current});current=false;finish('respuesta tardía');await assert.rejects(pending,error=>error.code==='cancelled');
});
test('diagnóstico admite sólo componentes y códigos conocidos, con ocho eventos y fecha local',()=>{
 const state=new N.State('3.8.0'),now=Date.parse('2026-10-20T18:04:05Z');
 state.record('drive','permission',1,now);assert.equal(state.label('drive'),'Permiso vencido');
 state.record('mini','stale',1,now);assert.match(state.label('mini'),/sin señal/);
 state.record('Paciente Ficticio','11111111-1',1,now);
 state.record('library',N.failure(Error('/private/expediente TOKEN-FICTICIO Paciente Ficticio 11111111-1')).code,1,now);
 const diagnostic=state.diagnostic();assert.match(diagnostic,/3.8.0/);assert.match(diagnostic,/20-10-2026/);assert.doesNotMatch(diagnostic,/Paciente|11111111|TOKEN|private/);
 for(let i=0;i<12;i++)state.record('mini','ok',99,now);assert.equal(state.events.length,8);assert.match(state.diagnostic(),/intento 1\/3/);
 assert.equal(new N.State('Paciente Ficticio').version,'desconocida');
});
