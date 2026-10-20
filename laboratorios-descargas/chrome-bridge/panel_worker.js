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
  const allowed=message.type==='nexo.library.read'?['type','id','sha256']:message.type==='nexo.panel.tab'?['type','view']:['type'];
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
  const response=await fetch('http://127.0.0.1:8765'+path,{cache:'no-store',credentials:'omit',redirect:'error',signal:AbortSignal.timeout(8000)});
  if(!response.ok || !response.headers.get('content-type')?.includes('application/json'))throw Error('Biblioteca local no disponible.');
  const raw=await response.text();if(raw.length>2097152)throw Error('Biblioteca demasiado grande.');
  return JSON.parse(raw);
}
