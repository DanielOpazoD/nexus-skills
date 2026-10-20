/* Botón sin datos clínicos; el panel pertenece a Chrome, fuera del DOM de Eloísa. */
(function(){
  'use strict';
  if(location.origin!=='https://clinicohangaroa.eloisa.cl' || window.top!==window)return;
  const version=chrome.runtime.getManifest().version;
  if(globalThis.__nexoPanel?.version===version)return;
  globalThis.__nexoPanel?.destroy();
  document.getElementById('nexo-clinical-panel-host')?.remove();
  const host=document.createElement('div');host.id='nexo-clinical-panel-host';
  const root=host.attachShadow({mode:'closed'}),style=document.createElement('style');
  style.textContent=':host{all:initial;position:fixed;right:20px;bottom:20px;z-index:2147483600}:host([hidden]){display:none!important}button{width:44px;height:44px;border:0;border-radius:50%;color:#fff;font:700 22px/1 -apple-system,BlinkMacSystemFont,sans-serif;background:linear-gradient(135deg,#3474ed,#7150d9);box-shadow:0 4px 16px #352f7a35;cursor:pointer}button:hover{filter:brightness(1.08)}button:focus-visible{outline:3px solid #aba6ff;outline-offset:3px}span{position:absolute;right:0;bottom:52px;min-width:150px;border-radius:9px;padding:8px 10px;background:white;color:#555;font:12px/1.4 -apple-system,BlinkMacSystemFont,sans-serif;box-shadow:0 3px 12px #0002}span:empty{display:none}@media(max-width:460px){:host{right:12px;bottom:12px}}';
  const button=document.createElement('button');button.type='button';button.textContent='N';button.setAttribute('aria-label','Abrir Nexo');button.title='Nexo';
  const status=document.createElement('span');status.setAttribute('role','status');root.append(style,status,button);
  let scheduled=false;
  async function open(){
    status.textContent='';
    try{const result=await chrome.runtime.sendMessage({type:'nexo.panel.open'});if(!result?.ok)throw Error();}
    catch(_){status.textContent='Recarga la extensión y esta pestaña.';}
  }
  function synchronize(){
    scheduled=false;host.hidden=!/^\/main(?:\/|$)/.test(location.pathname);
    if(!host.isConnected)document.documentElement.append(host);
  }
  function queueSynchronize(){if(!scheduled){scheduled=true;requestAnimationFrame(synchronize);}}
  button.addEventListener('click',open);window.addEventListener('popstate',synchronize);window.addEventListener('hashchange',synchronize);
  const observer=new MutationObserver(queueSynchronize);observer.observe(document.documentElement,{childList:true,subtree:true});
  globalThis.__nexoPanel={version,destroy(){observer.disconnect();host.remove();window.removeEventListener('popstate',synchronize);window.removeEventListener('hashchange',synchronize);}};
  synchronize();
})();
