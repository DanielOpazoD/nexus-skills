// Solo estados y solicitudes sin credenciales cruzan el DOM local.
function announce() { window.postMessage({type:'labs.bridge-ready',version:3},location.origin); }
announce();
window.addEventListener('message', event => {
  if (event.source !== window || event.origin !== 'http://127.0.0.1:8765') return;
  if (event.data?.type === 'labs.bridge-ping') { announce(); return; }
  if (event.data?.type === 'labs.agenda-request') {
    const {id,date} = event.data;
    if (typeof id !== 'string' || !/^[a-f0-9]{32}$/.test(id) || typeof date !== 'string') return;
    (async () => {
      try {
        const result = await chrome.runtime.sendMessage({type:'labs.agenda',id,date});
        window.postMessage({type:'labs.agenda-result',id,...result},location.origin);
      } catch (_) {
        window.postMessage({type:'labs.agenda-result',id,ok:false,error:'Recarga la extensión y esta página.'},location.origin);
      }
    })();
    return;
  }
  if (event.data?.type !== 'labs.bridge-request') return;
  const {id,nonce,sources} = event.data;
  if (typeof id !== 'string' || typeof nonce !== 'string' || !Array.isArray(sources)) return;
  (async () => {
    try {
      const response = await chrome.runtime.sendMessage({type:'labs.collect',id,nonce,sources});
      window.postMessage({type:'labs.bridge-result',id,ok:!!response?.ok,
        error:response?.error || (response?.errors || []).join(' ')},location.origin);
    } catch (_) {
      window.postMessage({type:'labs.bridge-result',id,ok:false,error:'Recarga el puente y esta página de Chrome.'},location.origin);
    }
  })();
});
