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
$('request-preview').addEventListener('toggle',() => {
  if (!$('request-preview').open) return;
  try { prepareRequest(); } catch (cause) { $('request-text').value = '';displayRequestError(cause); }
});
updatePeriod();updateFields();clearPreparedView();

$('new-request').addEventListener('click',() => {
  requestTracker.reset();prepared = null;clearPreparedView();
  $('new-request').hidden = true;
});
