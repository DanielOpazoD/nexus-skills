'use strict';
const $=id=>document.getElementById(id),C=NexoLibraryCore,D=NexoDriveLibrary;
const T=globalThis.NexoTransport;
let activeView='request',provider=null,patients=[],selected=null,selectedDocument=null,sequence=0,loading=false;
let contextSelection=false,reconnectHandle=null,followContext=true,lastContext,contextBusy=false;
const readContext=()=>T?T.bounded(bridge({type:'nexo.patient.context'})):bridge({type:'nexo.patient.context'});
async function bridge(message){
  const response=await chrome.runtime.sendMessage(message);
  if(!response?.ok)throw Error(response?.error||'Biblioteca no disponible.');
  return response.result;
}
function clearSummary(){sequence++;selectedDocument=null;$('summary-text').value='';$('copy-summary').disabled=true;$('copy-status').textContent='';$('summary-status').textContent='';}
function listView(){clearSummary();selected=null;contextSelection=false;loading=false;$('refresh-library').disabled=false;$('summary-view').hidden=true;$('library-list-view').hidden=false;$('drive-setup').hidden=true;}
function switchView(view,focus=false){
  if(activeView===view){if(focus)$('tab-'+view).focus();return;}
  if(activeView!==view)listView();activeView=view;
  for(const id of ['request','library']){
    $('tab-'+id).setAttribute('aria-selected',String(id===view));$('tab-'+id).tabIndex=id===view?0:-1;$('view-'+id).hidden=id!==view;
  }
  if(focus)$('tab-'+view).focus();
  if(view==='library'){followContext=true;lastContext=undefined;void refresh();}
}
for(const id of ['request','library']){
  $('tab-'+id).addEventListener('click',()=>switchView(id));
  $('tab-'+id).addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();switchView(event.key==='Home'?'request':event.key==='End'?'library':id==='request'?'library':'request',true);
  });
}
function renderPatients(){
  const matching=patients.filter(patient=>C.matches(patient,$('patient-search').value));
  const fragment=document.createDocumentFragment();
  for(const patient of matching.slice(0,100)){
    const li=document.createElement('li'),button=document.createElement('button'),name=document.createElement('strong'),detail=document.createElement('small');
    button.type='button';name.textContent=patient.name;const dates=patient.documents.map(d=>d.date).filter(Boolean).sort((a,b)=>b.split('-').reverse().join('').localeCompare(a.split('-').reverse().join('')));
    detail.textContent=patient.rut+(patient.documents.length?(dates[0]?' · '+dates[0]:''):' · Sin resumen TXT');
    button.append(name,detail);button.addEventListener('click',()=>selectPatient(patient));li.append(button);fragment.append(li);
  }
  $('patient-list').replaceChildren(fragment);
  if(!loading)$('library-status').textContent=!matching.length?'Sin coincidencias':matching.length>100?'100 de '+matching.length+' pacientes · precisa la búsqueda':matching.length+' paciente'+(matching.length===1?'':'s');
}
async function chooseProvider(){
  try{
    const handle=await D.savedHandle();
    if(handle && await handle.queryPermission({mode:'read'})==='granted'){const drive=new D.DriveLibrary(handle);drive.kind='drive';return drive;}
  }catch(_){/* El acceso local sigue disponible si falla IndexedDB. */}
  const local={kind:'mini',token:null,list:async()=>{const catalog=await bridge({type:'nexo.library.list'});local.token=catalog.openToken;return catalog;},read:(id,sha256)=>bridge({type:'nexo.library.read',id,sha256}),open:id=>bridge({type:'nexo.library.open',id,token:local.token})};return local;
}
async function refresh(){
  clearSummary();const request=sequence;
  loading=true;$('refresh-library').disabled=true;$('library-status').textContent='Cargando resúmenes…';
  try{
    const next=await chooseProvider(),catalog=await (T?T.bounded(next.list()):next.list());
    if(request!==sequence || activeView!=='library')return;
    if(!catalog.available)throw Error('Conecta tu carpeta Pacientes de Drive.');
    if(catalog.version!==1 || !Array.isArray(catalog.patients))throw Error('Biblioteca no compatible.');
    for(const patient of catalog.patients){C.rut(patient.rut);if(typeof patient.name!=='string'||!Array.isArray(patient.documents))throw Error('Biblioteca pendiente de revisión.');}
    provider=next;$('library-origin').textContent=next.kind==='drive'?'Drive · carpeta sincronizada':'Mini · archivo local';$('connect-drive').textContent=next.kind==='drive'?'Cambiar conexión de Drive':'Conectar carpeta de Drive';patients=catalog.patients.sort((a,b)=>a.name.localeCompare(b.name,'es',{sensitivity:'base'}));loading=false;renderPatients();
    if(catalog.issues)$('library-status').textContent+=' · '+catalog.issues+' archivo(s) requieren revisión';
    void followCurrentPatient();
  }catch(error){if(request===sequence){patients=[];provider=null;$('library-origin').textContent='';loading=false;renderPatients();$('library-status').textContent=error.message||'No se pudo cargar la biblioteca.';}}
  finally{if(request===sequence){loading=false;$('refresh-library').disabled=false;}}
}
function selectPatient(patient,fromContext=false){
  clearSummary();selected=patient;contextSelection=fromContext;$('library-list-view').hidden=true;$('summary-view').hidden=false;
  $('open-patient-folder').hidden=!(patient.folderUrl||patient.openable&&provider?.open);
  $('patient-name').textContent=patient.name;$('patient-rut').textContent=patient.rut;$('summary-date').textContent='';
  $('summary-version').replaceChildren();$('version-control').hidden=patient.documents.length<2;
  if(!patient.documents.length){$('summary-status').textContent='No hay un resumen TXT disponible para este paciente.';return;}
  const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Elegir versión';$('summary-version').append(placeholder);
  for(const document of patient.documents){const option=window.document.createElement('option');option.value=document.id;option.textContent=document.date||'Archivo existente';$('summary-version').append(option);}
  if(patient.documents.length===1)void readSummary(patient.documents[0]);
}
async function readSummary(document){
  clearSummary();const turn=sequence,patient=selected;$('summary-status').textContent='Cargando…';
  try{
    const result=await (T?T.bounded(provider.read(document.id,document.sha256)):provider.read(document.id,document.sha256));
    if(turn!==sequence || selected!==patient || activeView!=='library')return;
    if(contextSelection)await ensureContext(patient);
    if(turn!==sequence||selected!==patient)return;
    const identity=C.documentIdentity(result.text,patient.name);
    if(result.id!==document.id || result.sha256!==document.sha256 || identity.rut!==patient.rut || !C.sameName(identity.name,patient.name))throw Error('La identidad del resumen no coincide.');
    selectedDocument={...document,status:result.status};$('summary-text').value=result.text;
    $('summary-date').textContent=[document.date?'Guardado '+document.date:'Archivo existente',document.referenceDate?'Referencia '+document.referenceDate:''].filter(Boolean).join(' · ');
    $('summary-status').textContent=C.canCopy(selectedDocument)?'':result.status==='stale'?'Documentos nuevos o distintos · resumen pendiente de revisión.':'Archivo modificado · revisión pendiente.';
    $('copy-summary').disabled=!C.canCopy(selectedDocument);
  }catch(error){if(turn===sequence){$('summary-text').value='';$('summary-status').textContent=error.message||'No se pudo leer el resumen.';$('copy-summary').disabled=true;}}
}
$('summary-version').addEventListener('change',()=>{const document=selected?.documents.find(d=>d.id===$('summary-version').value);if(document)void readSummary(document);else clearSummary();});
$('patient-search').addEventListener('input',renderPatients);$('change-patient').addEventListener('click',()=>{followContext=false;listView();});$('refresh-library').addEventListener('click',()=>{listView();void refresh();});
$('copy-summary').addEventListener('click',async()=>{
  const document=selectedDocument,patient=selected,turn=sequence;
  if(!C.canCopy(document)||!patient)return;$('copy-summary').disabled=true;$('copy-status').textContent='Comprobando…';
  try{
    if(contextSelection)await ensureContext(patient);if(turn!==sequence)return;
    const result=await (T?T.bounded(provider.read(document.id,document.sha256)):provider.read(document.id,document.sha256));
    if(turn!==sequence || selected!==patient)return;
    const identity=C.documentIdentity(result.text,patient.name);
    if(result.id!==document.id || result.sha256!==document.sha256 || identity.rut!==patient.rut || !C.sameName(identity.name,patient.name) || !C.canCopy(result))throw Error('El resumen cambió. Actualiza la lista.');
    if(contextSelection)await ensureContext(patient);
    if(turn!==sequence||selected!==patient)return;
    $('summary-text').value=result.text;
    try{await navigator.clipboard.writeText(result.text);if(turn===sequence)$('copy-status').textContent='Copiado';}
    catch(_){if(turn===sequence){$('summary-text').focus();$('summary-text').select();$('copy-status').textContent='Texto seleccionado · pulsa ⌘C';}}
  }catch(error){if(turn===sequence){clearSummary();$('summary-status').textContent=error.message||'No se pudo comprobar el resumen.';}}
  finally{if(turn===sequence)$('copy-summary').disabled=!C.canCopy(selectedDocument);}
});
$('open-full').addEventListener('click',async()=>{try{await bridge({type:'nexo.panel.tab',view:activeView});}catch(_){$('library-status').textContent='No se pudo abrir la pestaña.';}});
$('connect-drive').addEventListener('click',async()=>{
  listView();const turn=sequence;reconnectHandle=null;$('reconnect-drive').hidden=true;$('setup-status').textContent='';$('library-list-view').hidden=true;$('drive-setup').hidden=false;
  try{const handle=await D.savedHandle();if(turn!==sequence)return;reconnectHandle=handle||null;$('reconnect-drive').hidden=!handle;}
  catch(_){/* Se puede seleccionar otra carpeta si no se recupera el permiso. */}
});
$('reconnect-drive').addEventListener('click',async()=>{
  if(!reconnectHandle)return;const turn=sequence;
  try{
    const permission=await reconnectHandle.requestPermission({mode:'read'});
    if(turn!==sequence)return;
    if(permission!=='granted')throw Error('Permiso pendiente. Puedes seleccionar otra carpeta.');
    listView();void refresh();
  }catch(error){if(turn===sequence)$('setup-status').textContent=error.message||'No se pudo reconectar la carpeta.';}
});
$('cancel-drive').addEventListener('click',()=>{listView();void refresh();});
$('choose-drive').addEventListener('click',async()=>{
  const turn=sequence;
  try{
    if(!globalThis.showDirectoryPicker)throw Error('Abre Nexo en una pestaña para seleccionar la carpeta.');
    const handle=await showDirectoryPicker({id:'nexo-patients',mode:'read'});
    if(turn!==sequence)return;
    if(handle.name!==ClinicalCatalog.library.patientsFolder)throw Error('Selecciona la carpeta «Pacientes».');
    await D.savedHandle(handle);if(turn!==sequence)return;$('setup-status').textContent='Carpeta conectada';listView();void refresh();
  }catch(error){if(turn===sequence&&error.name!=='AbortError')$('setup-status').textContent=error.name==='SecurityError'?'Abre Nexo en una pestaña para seleccionar la carpeta.':error.message||'No se pudo conectar la carpeta.';}
});
$('forget-drive').addEventListener('click',async()=>{try{await D.savedHandle(null);listView();void refresh();}catch(_){$('setup-status').textContent='No se pudo desconectar la carpeta.';}});
document.addEventListener('visibilitychange',()=>{if(document.hidden)listView();else if(activeView==='library')void refresh();});
function invalidateContext(){
  if(activeView!=='library'||document.hidden)return;
  listView();followContext=true;lastContext=undefined;void followCurrentPatient();
}
chrome.tabs?.onActivated?.addListener(invalidateContext);
chrome.tabs?.onUpdated?.addListener((_id,change)=>{if(change.url)void followCurrentPatient();});
chrome.runtime.onMessage?.addListener((message,sender)=>{
  if(sender.id===chrome.runtime.id&&!sender.tab&&message?.type==='nexo.patient.invalidated'&&Object.keys(message).length===1)invalidateContext();
});
window.addEventListener('pagehide',clearSummary);
if(new URLSearchParams(location.search).get('view')==='library')switchView('library');
function matchingPatient(current){
  if(!current)return null;
  const found=patients.filter(patient=>samePatient(patient,current));return found.length===1?found[0]:null;
}
function samePatient(one,two){
  if(!one||!two)return !one&&!two;
  try{return C.rut(one.rut)===C.rut(two.rut)&&C.sameName(one.name,two.name);}catch(_){return false;}
}
async function ensureContext(patient){
  const current=await readContext();
  if(!samePatient(current.patient,patient))throw Error('La ficha cambió. Vuelve a elegir al paciente.');
}
async function followCurrentPatient(){
  if(contextBusy||activeView!=='library'||document.hidden||!$('drive-setup').hidden)return;
  contextBusy=true;const turn=sequence;
  try{
    const current=await readContext();if(turn!==sequence||activeView!=='library')return;
    const changed=lastContext!==undefined&&!samePatient(lastContext,current.patient);
    lastContext=current.patient||null;
    if(changed || contextSelection&&!samePatient(selected,current.patient)){listView();followContext=true;}
    const found=matchingPatient(current.patient);$('use-current-patient').hidden=!found;
    if(followContext&&!selected&&found)selectPatient(found,true);
  }catch(_){if(turn===sequence&&contextSelection){listView();$('library-status').textContent='No se pudo comprobar la ficha abierta.';}}
  finally{contextBusy=false;}
}
const contextTimer=setInterval(followCurrentPatient,2000);
window.addEventListener('pagehide',()=>clearInterval(contextTimer));
$('use-current-patient').addEventListener('click',async()=>{
 const turn=sequence;
 try{const current=await readContext();if(turn!==sequence||activeView!=='library')return;
  const found=patients.find(patient=>current.patient&&patient.rut===C.rut(current.patient.rut)&&C.sameName(patient.name,current.patient.name));
  if(!found)throw Error('La ficha cambió o no tiene un expediente identificado.');selectPatient(found,true);
 }catch(error){$('library-status').textContent=error.message||'No se pudo identificar la ficha.';$('use-current-patient').hidden=true;}
});
$('open-patient-folder').addEventListener('click',async()=>{
 const patient=selected,turn=sequence;if(!patient)return;
 try{
  if(patient.folderUrl){if(!/^https:\/\/drive\.google\.com\/drive\/folders\/[A-Za-z0-9_-]{10,200}$/.test(patient.folderUrl))throw Error('Enlace no verificable.');await chrome.tabs.create({url:patient.folderUrl});}
  else await provider.open(patient.id);
 }catch(_){if(turn===sequence)$('summary-status').textContent='No se pudo abrir el expediente.';}
});
let healthBusy=false;
async function refreshWorker(){
 if(!T||healthBusy||document.hidden)return;healthBusy=true;
 try{
  try{
   const local=await bridge({type:'nexo.worker.health'});
   if(local.app==='laboratorios-descargas'&&local.version===1&&local.queue&&local.worker?.running){$('worker-status').textContent=local.worker.drive?'Mini disponible':'Mini · Drive pendiente';return;}
  }catch(_){/* En el Air se comprueba la señal de Drive. */}
  const inbox=await T.connection('inbox');
  if(!inbox||await inbox.queryPermission({mode:'read'})!=='granted'){$('worker-status').textContent='Mini · sin comprobar';return;}
  $('worker-status').textContent=T.worker(await T.read(inbox,'worker.json')).label;
 }catch(_){$('worker-status').textContent='Mini · sin señal reciente';}
 finally{healthBusy=false;}
}
if(T){void refreshWorker();const healthTimer=setInterval(refreshWorker,30000);window.addEventListener('pagehide',()=>clearInterval(healthTimer));}
