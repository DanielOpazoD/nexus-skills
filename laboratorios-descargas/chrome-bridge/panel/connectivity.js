/* Lecturas acotadas y diagnóstico por lista permitida; sin datos de pacientes. */
(function(root){
 'use strict';
 const codes=new Set(['ok','retrying','unknown','unavailable','timeout','permission','integrity','incompatible','cancelled','not_connected','stale','attention','clock']);
 const components=new Set(['drive','mini','library','context']);
 function failure(error){
  let code=codes.has(error?.code)?error.code:'unknown';
  if(['NotAllowedError','SecurityError'].includes(error?.name))code='permission';
  else if(['NotReadableError','NetworkError'].includes(error?.name))code='unavailable';
  else if(error?.name==='NotFoundError'||error?.name==='SyntaxError')code='integrity';
  return {code,retryable:code==='unavailable'||code==='timeout'&&error?.retryable===true};
 }
 function error(code){return Object.assign(Error(code==='timeout'?'La lectura tarda en responder. Vuelve a intentar.':'Lectura cancelada.'),{code,retryable:false});}
 function wait(ms){return new Promise(resolve=>setTimeout(resolve,ms));}
 async function bounded(operation,ms){
  let timer;
  try{return await Promise.race([operation,new Promise((_,reject)=>{timer=setTimeout(()=>reject(error('timeout')),ms);})]);}
  finally{clearTimeout(timer);}
 }
 async function read(operation,{isCurrent=()=>true,pause=wait,timeout=6000,onAttempt=()=>{}}={}){
  for(let attempt=1;attempt<=3;attempt++){
   if(!isCurrent())throw error('cancelled');
   onAttempt(attempt);
   try{
    const value=await bounded(operation(),timeout);
    if(!isCurrent())throw error('cancelled');
    return value;
   }catch(cause){
    if(!isCurrent())throw error('cancelled');
    if(attempt===3||!failure(cause).retryable)throw cause;
    await pause(attempt===1?300:900);
   }
  }
 }
 function stamp(at){
  if(!Number.isFinite(at))return 'Sin comprobar';
  const parts=new Intl.DateTimeFormat('es-CL',{timeZone:'Pacific/Easter',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(at);
  const p=name=>parts.find(item=>item.type===name)?.value;
  return `${p('day')}-${p('month')}-${p('year')} ${p('hour')}:${p('minute')}:${p('second')}`;
 }
 class State{
  constructor(version){this.version=typeof version==='string'&&/^\d{1,4}(?:\.\d{1,4}){1,3}$/.test(version)?version:'desconocida';this.events=[];this.current={};}
  record(component,code,attempt=1,at=Date.now()){
   if(!components.has(component))return;
   const event={component,code:codes.has(code)?code:'unknown',attempt:Number.isInteger(attempt)&&attempt>=1&&attempt<=3?attempt:1,at:Number.isFinite(at)?at:Date.now()};
   this.current[component]=event;this.events.push(event);if(this.events.length>8)this.events.shift();
  }
  label(component){
   const code=this.current[component]?.code||'unknown';
   if(component==='drive')return ({ok:'Carpeta disponible',permission:'Permiso vencido',not_connected:'Carpeta sin conectar',retrying:'Reintentando lectura',timeout:'Lectura lenta',unavailable:'Carpeta no disponible',integrity:'Revisión pendiente'})[code]||'Sin comprobar';
   return ({ok:'Mini disponible',stale:'Mini · sin señal reciente',attention:'Mini requiere atención',clock:'Mini · hora por revisar',retrying:'Mini · reintentando',timeout:'Mini · sin respuesta',unavailable:'Mini · no disponible',incompatible:'Mini · versión incompatible'})[code]||'Mini · sin comprobar';
  }
  diagnostic(){
   const lines=['Nexo · diagnóstico de conexión','Extensión: '+this.version,'Zona horaria: Pacific/Easter'];
   for(const component of ['mini','drive']){const state=this.current[component];lines.push(component+': '+(state?.code||'unknown')+' · '+stamp(state?.at));}
   lines.push('Eventos recientes:');
   for(const event of this.events)lines.push(`${stamp(event.at)} · ${event.component} · ${event.code} · intento ${event.attempt}/3`);
   return lines.join('\n');
  }
 }
 root.NexoConnectivity={failure,read,State,stamp};
})(globalThis);
