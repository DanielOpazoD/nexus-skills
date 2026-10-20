let prepared = null;
let trackingAbort=null;
const requestTracker = ClinicalRequest.tracker();
function prepareRequest() {
  prepared = requestTracker.prepare(requestSelection());
  $('new-request').hidden = false;
  const text = ClinicalRequest.prompt(prepared);
  $('request-text').value = text;
  return text;
}
function clearPreparedView() {
  trackingAbort?.abort();trackingAbort=null;
  $('copy-status').textContent = '';
  $('request-text').value = '';
  $('request-preview').open = false;
  $('save-request').disabled = $('run').disabled;
  $('send-drive').disabled = $('run').disabled || !globalThis.showDirectoryPicker || !crypto.subtle;
}
form.addEventListener('input',clearPreparedView);
form.addEventListener('change',clearPreparedView);
form.addEventListener('click',event => {
  if (event.target.closest('[data-period], [data-reset-period], #apply-period-all, #select-all, #select-none')) clearPreparedView();
});
function displayRequestError(cause) {
  $('form-error').textContent = cause.message;$('form-error').hidden = false;
}
form.addEventListener('submit',async event => {
  event.preventDefault();
  try {
    const text = prepareRequest();
    try {
      if (!navigator.clipboard?.writeText) throw new Error('manual-copy');
      await navigator.clipboard.writeText(text);
      $('copy-status').textContent = 'Copiada. Pégala en Codex del Mac mini.';
    } catch (_) {
      $('request-preview').open = true;$('request-text').focus();$('request-text').select();
      $('copy-status').textContent = 'Texto seleccionado. Pulsa ⌘C y pégalo en Codex del Mac mini.';
    }
  } catch (cause) { displayRequestError(cause); }
});
$('save-request').addEventListener('click',() => {
  try {
    const text = prepareRequest();
    const blob = new Blob([text],{type:'text/plain;charset=utf-8'}), url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;link.download = `Solicitud clínica ${ClinicalRequest.displayDate(prepared.asOf)} ${prepared.id.slice(0,8)}.txt`;
    document.body.append(link);link.click();link.remove();
    setTimeout(() => URL.revokeObjectURL(url),30000);
    $('copy-status').textContent = 'Archivo preparado. Guárdalo en Drive y ábrelo con Codex del Mac mini.';
  } catch (cause) { displayRequestError(cause); }
});
async function writeDriveRequest(directory, packet) {
  if (directory.name !== '_Solicitudes Nexo') throw new Error('Selecciona la carpeta «_Solicitudes Nexo» de Google Drive.');
  const raw = JSON.stringify(packet,null,2)+'\n';
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw))),
    byte => byte.toString(16).padStart(2,'0')).join('');
  const stem = `solicitud-${packet.id}`;
  try {
    const existing = await directory.getFileHandle(stem+'.ready');
    const prior = (await (await existing.getFile()).text()).trim();
    if (prior !== digest) throw new Error('Ese ID ya existe con otro contenido. Pulsa «Nuevo pedido».');
  } catch (error) { if (error.name !== 'NotFoundError') throw error; }
  const data = await directory.getFileHandle(stem+'.json',{create:true});
  const stream = await data.createWritable();
  await stream.write(raw);await stream.close();
  const ready = await directory.getFileHandle(stem+'.ready',{create:true});
  const marker = await ready.createWritable();
  await marker.write(digest+'\n');await marker.close();
  return digest;
}
async function awaitDriveReceipt(directory, packet, digest, signal) {
  const order={id:packet.id,sha256:digest,patients:packet.request.ruts.length,sources:packet.request.source.split(',').length};
  for (let attempt=0;attempt<200&&!signal.aborted;attempt++) {
    await NexoTransport.pause(3000,signal);
    if(signal.aborted||prepared?.id!==packet.id)return;
    try {
      const acuses = await NexoTransport.bounded(directory.getDirectoryHandle('acuses'),signal);
      const receipt = await NexoTransport.read(acuses,`acuse-${packet.id}.json`,signal);
      if (receipt.id!==packet.id || receipt.sha256 !== digest) continue;
      if (prepared?.id !== packet.id) return;
      if(receipt.status==='rejected'){$('copy-status').textContent='El Mini rechazó la solicitud: '+(receipt.error||'revisa el archivo.');return;}
      if(receipt.status!=='imported')continue;
      $('copy-status').textContent='Recibida por el Mini';
      try{
        const state=NexoTransport.progress(await NexoTransport.read(acuses,`progreso-${packet.id}.json`,signal),order);
        if(signal.aborted||prepared?.id!==packet.id)return;
        $('copy-status').textContent=state.label;
        if(['summary_ready','cancelled'].includes(state.status))return;
      }catch(error){if(signal.aborted)return;if(error.name!=='NotFoundError')$('copy-status').textContent='Recibida · avance por confirmar';}
    } catch (error) { if (error.name !== 'NotFoundError' && !(error instanceof SyntaxError)) break; }
  }
  if (!signal.aborted&&prepared?.id === packet.id) $('copy-status').textContent+=' · seguimiento en pausa';
}
$('send-drive').addEventListener('click',async () => {
  try {
    const packet = requestTracker.prepare(requestSelection());prepared = packet;
    const directory = await globalThis.showDirectoryPicker({id:'nexo-drive-inbox',mode:'readwrite'});
    const digest = await writeDriveRequest(directory,packet);
    try{await NexoTransport.connection('inbox',directory);}catch(_){/* El envío no depende de recordar la carpeta. */}
    trackingAbort?.abort();trackingAbort=new AbortController();
    $('copy-status').textContent = 'Solicitud guardada en Drive; esperando acuse del Mac mini.';
    void awaitDriveReceipt(directory,packet,digest,trackingAbort.signal);
  } catch (error) {
    if (error.name !== 'AbortError') displayRequestError(error);
  }
});
$('request-preview').addEventListener('toggle',() => {
  if (!$('request-preview').open) return;
  try { prepareRequest(); } catch (cause) { $('request-text').value = '';displayRequestError(cause); }
});
updatePeriod();updateFields();clearPreparedView();
window.addEventListener('pagehide',()=>trackingAbort?.abort());

$('new-request').addEventListener('click',() => {
  requestTracker.reset();prepared = null;clearPreparedView();
  $('new-request').hidden = true;
});
