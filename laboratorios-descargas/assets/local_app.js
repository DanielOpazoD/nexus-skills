const states = {queued:'En cola',running:'Descargando',waiting:'Esperando acceso',interrupted:'Recuperando avance',
  cancelling:'Cancelando; se conservará lo obtenido',cancelled:'Cancelado; documentos conservados',complete:'Fuentes completadas',
  needs_codex:'Pendiente en Codex',attention:'Quedan fuentes o documentos pendientes',needs_session:'Necesita sesión de Chrome',needs_credentials:'Necesita credenciales'};
const requestTracker = ClinicalRequest.tracker();
let submittedSelection = '';
let activeJob = null, lastStatus = null, pendingBridge = null;
let attemptedBridge = new Set(), historySignature = '', fileSignature = '', receiptSignature = '', pollBusy = false;

async function api(path,body) {
  const response = await fetch('/api/'+path,{cache:'no-store',...(body === undefined ? {} : {
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'No se pudo completar la solicitud.');
  return result;
}
function showError(message) { $('error').textContent = message; $('error').hidden = !message; }
function displayDate(value) {
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat('es-CL',{timeZone:'Pacific/Easter',day:'2-digit',month:'2-digit',year:'numeric'}).formatToParts(date);
  const part = name => parts.find(item => item.type === name)?.value;
  return `${part('day')}-${part('month')}-${part('year')}`;
}
async function refreshHistory() {
  const {jobs,quarantined=[]} = await api('jobs');
  const signature = JSON.stringify([jobs,quarantined]);
  if (signature !== historySignature) {
    historySignature = signature;
    $('history').replaceChildren();
    for (const job of jobs) {
      const li = document.createElement('li'), button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${displayDate(job.started_at)} · ${job.patients} paciente(s) · ${job.sources.map(s => labels[s]).join(', ')} · ${job.delivery?.label || 'Sólo documentos originales'} · ${states[job.status] || job.status}`;
      button.addEventListener('click',() => selectJob(job.id));
      li.append(button);$('history').append(li);
    }
    if (!jobs.length) $('history').textContent = 'Aún no hay trabajos guardados.';
    if (quarantined.length) {
      const note = document.createElement('li');
      note.textContent = `${quarantined.length} trabajo(s) apartado(s) para revisión. Los demás continúan disponibles.`;
      $('history').append(note);
    }
  }
  if (!activeJob && jobs.length) selectJob(jobs[0].id);
}
function selectJob(id) {
  activeJob = id;lastStatus = null;$('delivery-prompt').value = '';$('delivery-prompt').hidden = true;$('copy-delivery').textContent = 'Copiar solicitud para Codex';fileSignature = '';receiptSignature = '';pendingBridge = null;
  $('result').hidden = false;showError('');
  // El ciclo regular mantiene un único sondeo; elegir otro trabajo invalida el anterior.
  void poll();
}
function requestBridge(force = false) {
  if (!pendingBridge || bridgeVersion < 2) return;
  const key = JSON.stringify(pendingBridge);
  if (!force && attemptedBridge.has(key)) return;
  attemptedBridge.add(key);
  window.postMessage({type:'labs.bridge-request',...pendingBridge},location.origin);
}
window.addEventListener('message',event => {
  if (event.source !== window || event.origin !== location.origin) return;
  if (event.data?.type === 'labs.bridge-ready') {
    bridgeVersion = Number(event.data.version || 1);updateFields();requestBridge();
  }
  if (event.data?.type === 'labs.bridge-result' && event.data.id === activeJob) showError(event.data.error || '');
});
window.postMessage({type:'labs.bridge-ping'},location.origin);

function render(body) {
  if (lastStatus?.id !== body.id) { $('delivery-prompt').hidden = true;$('delivery-prompt').value = ''; }
  if (lastStatus?.id !== body.id) { $('mail-prompt').value='';$('mail-prompt').hidden=true;$('copy-mail').textContent='Consultar correo en Codex'; }
  lastStatus = body;
  $('mail-step').hidden = !Object.hasOwn(body.source_states,'email') || body.source_states.email === 'complete';
  const receiptKey=JSON.stringify([body.id,body.receipts]);
  if (receiptKey !== receiptSignature) {
    receiptSignature=receiptKey;$('receipts').replaceChildren();
    $('receipt-copy-status').textContent='';
    for (const item of body.receipts || []) {
      const block=document.createElement('pre'),link=document.createElement('a');
      block.textContent=item.text;
      link.href='/api/receipt?id='+encodeURIComponent(body.id)+'&index='+item.index+'&sha256='+encodeURIComponent(item.sha256);
      link.textContent='Guardar resumen TXT · '+item.rut;
      $('receipts').append(block,link);
    }
  }
  const total=Object.keys(body.source_states).length;
  const done=Object.values(body.source_states).filter(s=>s==='complete').length;
  const overview=`${done}/${total} fuentes completadas · ${body.files.length} archivo(s) verificado(s)`;
  if ($('result-count').textContent !== overview) $('result-count').textContent=overview;
  $('receipt-panel').hidden=!(body.receipts || []).length;
  const delivery = body.delivery;
  $('delivery-result').hidden = !delivery || delivery.id === 'documents';
  $('delivery-state').textContent = delivery && delivery.id !== 'documents' ? delivery.label+(delivery.id === 'custom' ? ' · Redacción pendiente en Codex' : ' · Plantilla pendiente') : '';
  const stateLabel=states[body.status] || body.status;
  if ($('state').textContent !== stateLabel) $('state').textContent=stateLabel;
  $('progress').textContent = body.lines.join('\n');
  const stopped = ['cancelled','cancelling','complete'].includes(body.status);
  pendingBridge = body.need.length && !stopped ? {id:body.id,nonce:body.nonce,sources:body.need} : null;
  $('bridge-info').hidden = true;
  $('retry-bridge').hidden = !pendingBridge;
  $('cancel').hidden = stopped;
  $('retry-job').hidden = !['attention','waiting','interrupted','cancelled'].includes(body.status);
  $('rescue').hidden = !['attention','waiting'].includes(body.status);
  $('source-states').replaceChildren();
  for (const [source,status] of Object.entries(body.source_states)) {
    const item = document.createElement('li');
    const rows = body.summary.filter(row => row.source.replace('mmrad_images','mmrad') === source);
    const notices = [...new Set(rows.filter(row => row.notice).map(row => row.notice))];
    const exclusions = rows.flatMap(row => row.excluded_images || []);
    if (exclusions.length) notices.push(`${exclusions.length} estudio(s) con imágenes excluidas por la selección o por ser ecocardiografías`);
    const sourcePeriod = [...periods,{value:'latest',label:'Último registro'}].find(p => p.value === (body.source_periods?.[source] || body.period));
    item.textContent = `${labels[source]}${sourcePeriod ? ' · '+sourcePeriod.label : ''}: ${states[status] || status}${notices.length ? '. '+notices.join(' ') : ''}`;
    $('source-states').append(item);
  }
  $('pending-reports').replaceChildren();
  for (const row of body.summary || []) for (const report of row.unavailable_records || []) {
    if (report.report_type !== 'record' || !report.viewer_url) continue;
    try {
      const url = new URL(report.viewer_url);
      if (url.origin !== 'https://fichamedico.rayensalud.cl' || url.pathname !== '/dashboard/reports' || url.searchParams.get('report') !== 'GetHospitalizedEncounterHistory') continue;
      const li = document.createElement('li'), link = document.createElement('a');
      link.href = url.href;link.target = '_blank';link.rel = 'noopener noreferrer';
      link.textContent = `Abrir ficha completa · ${report.patient_name || row.rut} · episodio ${report.episode}`;
      li.append(link,document.createTextNode(' · PDF pendiente de descargar y verificar'));$('pending-reports').append(li);
    } catch (_) { /* No renderizar enlaces ajenos al visor oficial. */ }
  }
  $('pending-reports').hidden = !$('pending-reports').children.length;
  const signature = JSON.stringify(body.files);
  if (signature !== fileSignature) {
    fileSignature = signature;$('files').replaceChildren();
    for (const item of body.files) {
      const li = document.createElement('li'), link = document.createElement('a');
      link.href = '/api/file?id='+encodeURIComponent(body.id)+'&index='+item.index+'&sha256='+encodeURIComponent(item.sha256);link.textContent = item.name;
      li.append(link);$('files').append(li);
    }
  }
  const archive = body.archive || {}, copies = (archive.files || []).filter(f => f.copy === 'verified').length;
  $('archive-state').textContent = `Drive: ${copies} archivo(s) con copia verificada. `+
    (archive.sync === 'confirmed' ? 'Contenido comprobado en la nube.' : 'Sincronización en la nube pendiente de comprobar.')+
    ((archive.pending || []).length ? ' '+archive.pending.join(' ') : '');
  $('verify-archive').hidden = ['running','cancelling'].includes(body.status) || (!body.files.length && !(body.receipts || []).length);
  requestBridge();
}
async function poll() {
  if (pollBusy) return;
  pollBusy = true;
  const id = activeJob;
  try {
    if (id) {
      const body = await api('status?id='+encodeURIComponent(id));
      if (activeJob === id) render(body);
    }
    await refreshHistory();
  } catch (cause) {
    if (activeJob) showError(cause.message+' El historial guardado se recuperará al volver a conectar.');
  } finally { pollBusy = false; }
}
const credentialFields = {syslab:['syslabUser','syslabPassword'],mmrad:['mmradUser','mmradPassword'],his:['hisUser','hisPassword']};
function credentials() {
  const value = {};
  for (const [source,[user,password]] of Object.entries(credentialFields)) {
    const pair = {username:form.elements[user].value.trim(),password:form.elements[password].value};
    if (pair.username || pair.password) value[source] = pair;
  }
  return value;
}
async function refreshCredentials() {
  try {
    const status = await api('credentials/status');
    $('credential-status').textContent = Object.keys(credentialFields).map(source => labels[source]+': '+
      (status[source] === true ? 'guardadas' : status[source] === false ? 'sin guardar' : 'llavero no disponible')).join(' · ');
  } catch (_) { $('credential-status').textContent = 'No se pudo consultar el llavero.'; }
}
$('credential-panel').addEventListener('toggle',() => { if ($('credential-panel').open) void refreshCredentials(); });
$('save-credentials').addEventListener('click',async () => {
  $('save-credentials').disabled = true;
  try {
    const {saved} = await api('credentials',credentials());
    for (const source of saved) for (const field of credentialFields[source]) form.elements[field].value = '';
    await refreshCredentials();
  } catch (cause) { $('credential-status').textContent = cause.message; }
  finally { $('save-credentials').disabled = false; }
});
form.addEventListener('submit',async event => {
  event.preventDefault();
  if (submitting) return;
  $('result').hidden = false;showError('');
  const selected = selectedSources();
  if (!selected.length) { showError('Selecciona al menos una fuente.');return; }
  const patients = patientSelection(), imaging = mmradSelection();
  if (!patients.valid.length || patients.invalid || patients.all.length>200 || (selected.includes('mmrad') && imaging.empty)) {
    $('form-error').textContent = 'Revisa los RUT y selecciona qué descargar de MMRAD.';$('form-error').hidden = false;return;
  }
  submitting = true;updateFields();
  try {
    const selection = requestSelection(), packet = requestTracker.prepare(selection);
    const body = await api('jobs',{...packet.request,requestId:packet.id,asOf:packet.asOf,remember:form.elements.remember.checked,credentials:credentials()});
    submittedSelection = JSON.stringify(selection);
    $('run').textContent = 'Ver solicitud';$('new-request').hidden = false;
    for (const [,password] of Object.values(credentialFields)) form.elements[password].value = '';
    selectJob(body.id);
  } catch (cause) { showError(cause.message);$('form-error').textContent = cause.message;$('form-error').hidden = false; }
  finally { submitting = false;updateFields(); }
});
for (const [button,endpoint] of [['cancel','cancel'],['retry-job','retry'],['verify-archive','archive']]) {
  $(button).addEventListener('click',async () => {
    if (!activeJob) return;
    $(button).disabled = true;showError('');
    try { await api(endpoint,{id:activeJob});if (endpoint === 'retry') attemptedBridge.clear();await poll(); }
    catch (cause) { showError(cause.message); }
    finally { $(button).disabled = false; }
  });
}
$('retry-bridge').addEventListener('click',() => { showError('');requestBridge(true); });
$('rescue').addEventListener('click',async () => {
  if (!lastStatus) return;
  try {
    const text = lastStatus.summary.map(row => `${row.source}: ${row.status}; ${(row.errors || []).join('; ')}`).join('\n');
    await navigator.clipboard.writeText(`Rescate de descarga clínica. ID: ${activeJob}\n${text}`);
    $('rescue').textContent = 'Diagnóstico copiado';
  } catch (_) { showError('No se pudo copiar; puedes seleccionar los detalles del avance.'); }
});
$('copy-delivery').addEventListener('click',async () => {
  if (!activeJob) return;
  const id = activeJob;
  $('copy-delivery').disabled = true;
  try {
    const body = await api('delivery?id='+encodeURIComponent(id));
    if (activeJob !== id) return;
    $('delivery-prompt').value = body.prompt;
    try { await navigator.clipboard.writeText(body.prompt);$('copy-delivery').textContent = 'Solicitud copiada'; }
    catch (_) { $('delivery-prompt').hidden = false;$('delivery-prompt').focus();$('delivery-prompt').select(); }
  } catch (cause) { showError(cause.message); }
  finally { $('copy-delivery').disabled = false; }
});
(async () => {
  updatePeriod();updateFields();
  try { const config = await api('config');$('extension-path').textContent = config.extension_dir; }
  catch (_) { $('bridge-status').textContent = 'El servicio local no está disponible.'; }
  await poll();setInterval(poll,1500);
})();

$('history-link').addEventListener('click',() => { $('history-panel').open = true; });

$('copy-mail').addEventListener('click',async () => {
  const id=activeJob;if (!id) return;
  $('copy-mail').disabled=true;
  try {
    const body=await api('mail?id='+encodeURIComponent(id));if(activeJob!==id)return;
    $('mail-prompt').value=body.prompt;
    try { await navigator.clipboard.writeText(body.prompt);$('copy-mail').textContent='Solicitud copiada'; }
    catch (_) { $('mail-prompt').hidden=false;$('mail-prompt').focus();$('mail-prompt').select(); }
  } catch(error) { showError(error.message); }
  finally { $('copy-mail').disabled=false; }
});

$('copy-receipts').addEventListener('click',async () => {
  if (!lastStatus?.receipts?.length) return;
  const id=activeJob, text=lastStatus.receipts.map(item=>item.text).join('\n');
  try {
    await navigator.clipboard.writeText(text);
    if (activeJob===id) $('receipt-copy-status').textContent='Resumen copiado';
  } catch (_) {
    if (activeJob!==id) return;
    const range=document.createRange();range.selectNodeContents($('receipts'));
    const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
    $('receipt-copy-status').textContent='Texto seleccionado. Pulsa ⌘C para copiar.';
  }
});

function updateSubmissionLabel() {
  try { $('run').textContent = JSON.stringify(requestSelection()) === submittedSelection ? 'Ver solicitud' : 'Agregar solicitud →'; }
  catch (_) { $('run').textContent = 'Agregar solicitud →'; }
}
form.addEventListener('input',updateSubmissionLabel);
form.addEventListener('change',updateSubmissionLabel);
form.addEventListener('click',updateSubmissionLabel);
$('new-request').addEventListener('click',() => {
  if (submitting) return;
  requestTracker.reset();submittedSelection = '';
  $('new-request').hidden = true;updateSubmissionLabel();
});
