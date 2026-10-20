let prepared = null;
const requestTracker = ClinicalRequest.tracker();
function prepareRequest() {
  prepared = requestTracker.prepare(requestSelection());
  $('new-request').hidden = false;
  const text = ClinicalRequest.prompt(prepared);
  $('request-text').value = text;
  return text;
}
function clearPreparedView() {
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
async function awaitDriveReceipt(directory, packet, digest) {
  for (let attempt=0;attempt<40;attempt++) {
    await new Promise(resolve=>setTimeout(resolve,3000));
    try {
      const acuses = await directory.getDirectoryHandle('acuses');
      const file = await acuses.getFileHandle(`acuse-${packet.id}.json`);
      const receipt = JSON.parse(await (await file.getFile()).text());
      if (receipt.sha256 !== digest) continue;
      if (prepared?.id !== packet.id) return;
      $('copy-status').textContent = receipt.status === 'imported'
        ? 'Recibida por el Mac mini e importada en la cola.'
        : 'El Mac mini rechazó la solicitud: '+(receipt.error || 'revisa el archivo.');
      return;
    } catch (error) { if (error.name !== 'NotFoundError' && !(error instanceof SyntaxError)) break; }
  }
  if (prepared?.id === packet.id) $('copy-status').textContent = 'Solicitud guardada en Drive; acuse del Mac mini aún pendiente.';
}
$('send-drive').addEventListener('click',async () => {
  try {
    const packet = requestTracker.prepare(requestSelection());prepared = packet;
    const directory = await globalThis.showDirectoryPicker({id:'nexo-drive-inbox',mode:'readwrite'});
    const digest = await writeDriveRequest(directory,packet);
    $('copy-status').textContent = 'Solicitud guardada en Drive; esperando acuse del Mac mini.';
    void awaitDriveReceipt(directory,packet,digest);
  } catch (error) {
    if (error.name !== 'AbortError') displayRequestError(error);
  }
});
$('request-preview').addEventListener('toggle',() => {
  if (!$('request-preview').open) return;
  try { prepareRequest(); } catch (cause) { $('request-text').value = '';displayRequestError(cause); }
});
updatePeriod();updateFields();clearPreparedView();

$('new-request').addEventListener('click',() => {
  requestTracker.reset();prepared = null;clearPreparedView();
  $('new-request').hidden = true;
});
