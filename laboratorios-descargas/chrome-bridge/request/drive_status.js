/* Protocolo de estado y conexión a Drive; nunca guarda RUT ni texto clínico. */
(function(root){
 'use strict';
 const phases={received:'Recibida por el Mini',downloading:'Descargando',documents_partial:'Documentos disponibles · parcial',documents_ready:'Documentos disponibles',summary_ready:'Resumen preparado',cancelled:'Cancelada · documentos conservados',attention:'Requiere atención'};
 function instant(value){const n=typeof value==='string'?Date.parse(value):NaN;if(!Number.isFinite(n))throw Error('Fecha de estado no válida.');return n;}
 function worker(data,now=Date.now()){
  if(data?.version!==1||data.kind!=='nexo-worker-status'||data.role!=='mac-mini'||!['ready','attention','stopped'].includes(data.status))throw Error('Estado del Mini no compatible.');
  const observed=instant(data.observedAt),expires=instant(data.expiresAt);
  if(observed>now+60000)return {status:'unknown',label:'Hora del Mini por revisar'};
  if(expires<observed||expires-observed>90000)throw Error('Vigencia no válida.');
  if(expires<=now||data.status==='stopped')return {status:'stale',label:'Sin señal reciente del Mini'};
  return {status:data.status,label:data.status==='ready'?'Mini disponible':'Mini requiere atención'};
 }
 function progress(data,order,now=Date.now()){
  if(data?.version!==1||data.kind!=='nexo-request-progress'||data.id!==order.id||data.sha256!==order.sha256||!phases[data.status])throw Error('Avance de otra solicitud o no compatible.');
  const source=data.sourceCounts,summary=data.summary;
  const count=n=>Number.isSafeInteger(n)&&n>=0;
  if(!source||!summary||![source.total,source.completed,source.pending,summary.total,summary.ready,data.fileCount].every(count)||source.total!==order.sources||summary.total!==order.patients||source.completed+source.pending!==source.total||summary.ready>summary.total)throw Error('Conteos de avance no válidos.');
  if(!['complete','partial','pending'].includes(data.archive?.copy)||!['confirmed','pending'].includes(data.archive?.sync))throw Error('Archivo no compatible.');
  const observed=instant(data.observedAt);if(observed>now+60000)throw Error('Hora de avance por revisar.');
  const stale=now-observed>90000;
  let label=phases[data.status];
  if(data.status==='documents_ready'&&!data.fileCount)label='Fuentes consultadas · sin documentos';
  if(data.status==='summary_ready'&&summary.ready!==summary.total)throw Error('Resumen aún pendiente.');
  if(data.status==='documents_ready'&&source.pending)throw Error('Fuentes aún pendientes.');
  if(data.status==='summary_ready'&&source.pending)label+=' · fuentes pendientes';
  if(['summary_ready','documents_ready','documents_partial'].includes(data.status)&&data.archive.sync!=='confirmed')label+=' · Drive por confirmar';
  return {status:data.status,label:(stale?'Último estado: ':'')+label,stale};
 }
 async function connection(key,value){
  if(key!=='inbox')throw Error('Conexión no válida.');
  const db=await new Promise((resolve,reject)=>{const req=indexedDB.open('nexo-connections',1);req.onupgradeneeded=()=>req.result.createObjectStore('handles');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(Error('No se pudo recordar la conexión.'));req.onblocked=()=>reject(Error('Cierra otras ventanas de Nexo.'));});
  try{return await new Promise((resolve,reject)=>{const tx=db.transaction('handles',value===undefined?'readonly':'readwrite'),store=tx.objectStore('handles');const req=value===undefined?store.get(key):value===null?store.delete(key):store.put(value,key);let result;req.onsuccess=()=>result=req.result;tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(Error('No se pudo guardar la conexión.'));});}finally{db.close();}
 }
 async function bounded(operation,signal,ms=6000){
  let timer,abort;
  const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Drive tarda en responder. Vuelve a intentar.')),ms);abort=()=>reject(Error('Lectura cancelada.'));if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});});
  try{return await Promise.race([operation,timeout]);}finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
 }
 async function read(directory,name,signal){
  return bounded((async()=>{const handle=await directory.getFileHandle(name),file=await handle.getFile();if(file.size>16384)throw Error('Estado demasiado grande.');return JSON.parse(await file.text());})(),signal);
 }
 function pause(ms,signal){return new Promise(resolve=>{let timer;const done=()=>{clearTimeout(timer);signal?.removeEventListener('abort',done);resolve();};timer=setTimeout(done,ms);if(signal?.aborted)done();else signal?.addEventListener('abort',done,{once:true});});}
 root.NexoTransport={worker,progress,connection,bounded,read,pause};
})(globalThis);
