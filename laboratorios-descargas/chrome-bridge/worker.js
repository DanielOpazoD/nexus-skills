importScripts('agenda_core.js','agenda_worker.js','panel_worker.js','patient_context.js');
const LOCAL = 'http://127.0.0.1:8765/api/sessions';
const SOURCES = ['exalab', 'eloisa', 'rayen'];

async function validTab(pattern, origin, prefix) {
  const tabs = await chrome.tabs.query({url:pattern});
  const tab = tabs.find(item => {
    try { const url = new URL(item.url); return url.origin === origin && url.pathname.startsWith(prefix); }
    catch { return false; }
  });
  if (!tab?.id) throw new Error('Inicia sesión en ' + new URL(origin).hostname + ' en este perfil de Chrome.');
  return tab;
}

async function collectSource(source) {
  if (source === 'exalab') {
    await validTab('https://exalab.saludoriente.cl/*', 'https://exalab.saludoriente.cl', '/');
    const cookies = await chrome.cookies.getAll({url:'https://exalab.saludoriente.cl/web_ssmo/index.php'});
    const selected = cookies.filter(cookie => ['PHPSESSID','cf_clearance'].includes(cookie.name));
    if (!selected.some(cookie => cookie.name === 'PHPSESSID')) throw new Error('Exalab: inicia sesión en Chrome.');
    return {cookies:selected,user_agent:navigator.userAgent};
  }
  if (source === 'eloisa') {
    const tab = await validTab('https://clinicohangaroa.eloisa.cl/main*', 'https://clinicohangaroa.eloisa.cl', '/main');
    const [result] = await chrome.scripting.executeScript({target:{tabId:tab.id},func:() => {
      try { return JSON.parse(localStorage.getItem('userSession') || '{}').accessToken || null; }
      catch { return null; }
    }});
    if (typeof result?.result !== 'string' || !result.result) throw new Error('Eloísa: vuelve a iniciar sesión en Chrome.');
    return {access_token:result.result};
  }
  const tab = await validTab('https://fichamedico.rayensalud.cl/*', 'https://fichamedico.rayensalud.cl', '/dashboard/');
  const [result] = await chrome.scripting.executeScript({target:{tabId:tab.id},func:async () => {
    const response = await fetch('/api/auth/session',{cache:'no-store',signal:AbortSignal.timeout(10000)});
    if (!response.ok) return null;
    const data = await response.json();
    return data.ok && data.session?.token ? {token:data.session.token,facilityId:data.session.facilityId} : null;
  }});
  const session = result?.result;
  if (typeof session?.token !== 'string' || !session.token || !Number.isInteger(session.facilityId) || session.facilityId <= 0) {
    throw new Error('Epicrisis Rayen: inicia sesión en Registro Hospitalario.');
  }
  return session;
}

async function collect(message) {
  if (!Array.isArray(message.sources) || !message.sources.length || message.sources.length > 3 ||
      message.sources.some(name => !SOURCES.includes(name)) || typeof message.id !== 'string' || typeof message.nonce !== 'string') {
    throw new Error('Solicitud de sesiones inválida.');
  }
  const payload = {id:message.id,nonce:message.nonce};
  const failures = [];
  // Una pestaña vencida no invalida las otras sesiones. Enviar cada sesión lista
  // de inmediato; ni el DOM local ni el content script reciben credenciales.
  const accepted = [];
  for (const source of new Set(message.sources)) {
    try {
      const session = await collectSource(source);
      try {
        const response = await fetch(LOCAL,{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({...payload,[source]:session}),cache:'no-store',signal:AbortSignal.timeout(10000)});
        const body = await response.json();
        if (!response.ok) throw new Error('El trabajo ya no acepta sesiones; vuelve a abrirlo.');
        accepted.push(...(body.accepted || []));
      } finally { for (const key of Object.keys(session)) delete session[key]; }
    } catch (_) {
      failures.push(source + ': sesión no disponible. Inicia sesión y pulsa “Reintentar sesiones”.');
    }
  }
  return {ok:accepted.length > 0,accepted,errors:failures};
}

function allowedAgendaSender(sender) {
  try {
    const url = new URL(sender.url);
    const own=new URL(chrome.runtime.getURL('request/index.html'));
    return (url.origin === 'http://127.0.0.1:8765' && (!sender.frameId || sender.frameId===0)) ||
      (sender.id === chrome.runtime.id && url.protocol===own.protocol && url.host===own.host && url.pathname===own.pathname);
  } catch (_) { return false; }
}
chrome.action.onClicked.addListener(async tab => {
  try{await chrome.sidePanel.open({tabId:tab.id});}
  catch(_){await chrome.tabs.create({url:chrome.runtime.getURL('panel/index.html')});}
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if(message?.type==='nexo.panel.open'){
    if(!eloisaButton(sender) || Object.keys(message).length!==1)return false;
    // Invocar antes de cualquier await conserva el gesto del botón de Eloísa.
    const opening=chrome.sidePanel.open({tabId:sender.tab.id});
    (async()=>{try{await opening;sendResponse({ok:true});}catch(_){sendResponse({ok:false,error:'No se pudo abrir Nexo.'});}})();
    return true;
  }
  if(message?.type==='nexo.patient.changed'){
    if(!eloisaButton(sender)||Object.keys(message).length!==1)return false;
    (async()=>{
      try{
        const tabs=await chrome.tabs.query({active:true,lastFocusedWindow:true});
        if(tabs.length===1 && tabs[0].id===sender.tab.id)await chrome.runtime.sendMessage({type:'nexo.patient.invalidated'});
        sendResponse({ok:true});
      }catch(_){sendResponse({ok:false});}
    })();return true;
  }
  if(message?.type==='nexo.patient.context'){
    if(!ownPanel(sender)||Object.keys(message).length!==1)return false;
    (async()=>{try{sendResponse({ok:true,result:await currentPatient()});}catch(_){sendResponse({ok:true,result:{patient:null}});}})();return true;
  }
  if(['nexo.library.list','nexo.library.read','nexo.library.open','nexo.panel.tab','nexo.worker.health'].includes(message?.type)){
    if(!ownPanel(sender))return false;
    (async()=>{try{sendResponse({ok:true,result:await panelRequest(message)});}catch(error){const code=['unavailable','timeout','permission','integrity','incompatible'].includes(error.code)?error.code:'unknown';sendResponse({ok:false,code,retryable:message.type!=='nexo.library.open'&&error.retryable===true&&['unavailable','timeout'].includes(code),error:'Abre Nexo en este Mac o conecta tu carpeta Pacientes de Drive.'});}})();
    return true;
  }
  if (message?.type === 'labs.agenda') {
    if (!allowedAgendaSender(sender)) return false;
    (async () => {
      try { sendResponse({ok:true,result:await readAgenda(message)}); }
      catch (error) {
        const safe = /^(Selecciona|Solicitud|No se pudo identificar|Inicia sesión|Sesión de Eloísa|Eloísa|La agenda)/.test(error.message || '');
        sendResponse({ok:false,error:safe ? error.message : 'No se pudo cargar la agenda. Revisa la sesión de Eloísa y vuelve a intentar.'});
      }
    })();
    return true;
  }

  if (message?.type !== 'labs.collect') return false;
  try { if (new URL(sender.url).origin !== 'http://127.0.0.1:8765') return false; }
  catch { return false; }
  (async () => {
    try { sendResponse(await collect(message)); }
    catch (_) { sendResponse({ok:false,error:'No se pudo entregar la sesión al trabajo local.'}); }
  })();
  return true;
});
