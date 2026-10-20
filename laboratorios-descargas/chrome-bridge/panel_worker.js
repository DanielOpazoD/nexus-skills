/* Mensajes de la biblioteca: sólo páginas propias, rutas fijas y lectura local. */
function ownPanel(sender){
  try{
    const url=new URL(sender.url),expected=new URL(chrome.runtime.getURL('panel/index.html'));
    return sender.id===chrome.runtime.id && url.protocol===expected.protocol && url.host===expected.host && url.pathname===expected.pathname;
  }catch(_){return false;}
}
function eloisaButton(sender){
  try{return sender.id===chrome.runtime.id && sender.frameId===0 && Number.isInteger(sender.tab?.id) && new URL(sender.url).origin==='https://clinicohangaroa.eloisa.cl' && /^\/main(?:\/|$)/.test(new URL(sender.url).pathname);}
  catch(_){return false;}
}
async function panelRequest(message){
  const allowed=message.type==='nexo.library.read'?['type','id','sha256']:message.type==='nexo.library.open'?['type','id','token']:message.type==='nexo.panel.tab'?['type','view']:['type'];
  if(Object.keys(message).some(key=>!allowed.includes(key)))throw Error('Solicitud no válida.');
  if(message.type==='nexo.panel.tab'){
    if(!['request','library'].includes(message.view))throw Error('Vista no válida.');
    await chrome.tabs.create({url:chrome.runtime.getURL('panel/index.html')+'?view='+message.view});return {opened:true};
  }
  let path=message.type==='nexo.worker.health'?'/api/health':'/api/library';
  if(message.type==='nexo.library.read'){
    if(!/^[a-f0-9]{64}$/.test(message.id)||!/^[a-f0-9]{64}$/.test(message.sha256))throw Error('Documento no válido.');
    path+='/read?id='+encodeURIComponent(message.id)+'&sha256='+encodeURIComponent(message.sha256);
  }
  let options={cache:'no-store',credentials:'omit',redirect:'error',signal:AbortSignal.timeout(message.type==='nexo.library.open'?8000:4000)};
  if(message.type==='nexo.library.open'){
    if(!/^[a-f0-9]{64}$/.test(message.id)||typeof message.token!=='string'||!/^[A-Za-z0-9_-]{32,128}$/.test(message.token))throw Error('Expediente no válido.');
    path='/api/library/open';options={...options,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:message.id,token:message.token})};
  }
  let response,raw;
  const fail=(code,retryable=false)=>Object.assign(Error('Biblioteca local no disponible.'),{code,retryable});
  try{
    response=await fetch('http://127.0.0.1:8765'+path,options);
    raw=await response.text();
  }catch(error){throw fail(error.name==='TimeoutError'?'timeout':'unavailable',true);}
  if(!response.ok){
    if([408,429,500,502,503,504].includes(response.status))throw fail('unavailable',true);
    throw fail([401,403].includes(response.status)?'permission':[404,409,426].includes(response.status)?'incompatible':'integrity');
  }
  if(!response.headers.get('content-type')?.includes('application/json')||raw.length>2097152)throw fail('integrity');
  try{return JSON.parse(raw);}catch(_){throw fail('integrity');}
}
