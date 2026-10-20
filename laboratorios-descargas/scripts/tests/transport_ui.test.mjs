import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import {readFile} from 'node:fs/promises';
const context={setTimeout,clearTimeout,Date};vm.createContext(context);vm.runInContext(await readFile(new URL('../../assets/drive_status.js',import.meta.url),'utf8'),context);const T=context.NexoTransport;
const now=Date.parse('2026-10-20T12:00:00Z'),observedAt=new Date(now).toISOString(),order={id:'a'.repeat(32),sha256:'b'.repeat(64),sources:2,patients:3};
const status={version:1,kind:'nexo-request-progress',id:order.id,sha256:order.sha256,status:'documents_partial',observedAt,sourceCounts:{completed:1,pending:1,total:2},summary:{ready:0,total:3},fileCount:2,archive:{copy:'partial',sync:'pending'}};
test('la señal del Mini vence y un reloj futuro no acredita disponibilidad',()=>{
 const data={version:1,kind:'nexo-worker-status',role:'mac-mini',status:'ready',observedAt,expiresAt:new Date(now+90000).toISOString()};
 assert.equal(T.worker(data,now).status,'ready');assert.equal(T.worker(data,now+90001).status,'stale');assert.equal(T.worker(data,now-90000).status,'unknown');
 assert.throws(()=>T.worker({...data,expiresAt:new Date(now+999999).toISOString()},now));
});
test('avance ligado a ID/hash, conteos y sincronización; recibir no equivale a terminar',()=>{
 assert.match(T.progress(status,order,now).label,/parcial.*Drive por confirmar/);
 for(const change of [{id:'c'.repeat(32)},{sha256:'d'.repeat(64)},{sourceCounts:{completed:2,pending:1,total:2}},{summary:{ready:9,total:3}},{status:'summary_ready'}])assert.throws(()=>T.progress({...status,...change},order,now));
 const done={...status,status:'summary_ready',summary:{ready:3,total:3}};assert.match(T.progress(done,order,now).label,/fuentes pendientes/);
 assert.match(T.progress(status,order,now+100000).label,/^Último estado/);
});
test('búsqueda vacía completa no anuncia documentos inexistentes',()=>{
 const empty={...status,status:'documents_ready',fileCount:0,sourceCounts:{completed:2,pending:0,total:2}};
 assert.match(T.progress(empty,order,now).label,/sin documentos/);
});
test('lectura de Drive tiene límite de tamaño y tiempo; cancelar limpia la espera',async()=>{
 const directory={getFileHandle:async()=>({getFile:async()=>({size:20000,text:async()=>'{"private":true}'})})};
 await assert.rejects(T.read(directory,'test.json'),/grande/);
 await assert.rejects(T.bounded(new Promise(()=>{}),undefined,5),/tarda/);
 const abort=new AbortController(),waiting=T.bounded(new Promise(()=>{}),abort.signal);abort.abort();await assert.rejects(waiting,/cancelada/);
 const pauseAbort=new AbortController(),paused=T.pause(60000,pauseAbort.signal);pauseAbort.abort();await paused;
});
