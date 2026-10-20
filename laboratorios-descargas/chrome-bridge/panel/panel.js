'use strict';
const $=id=>document.getElementById(id),C=NexoLibraryCore,D=NexoDriveLibrary;
const T=globalThis.NexoTransport,N=NexoConnectivity;
const connectionState=new N.State(chrome.runtime.getManifest?.().version);
let activeView='request',provider=null,patients=[],selected=null,selectedDocument=null,sequence=0,loading=false;
let contextSelection=false,reconnectHandle=null,followContext=true,lastContext,contextBusy=false;
let pendingUpdate=null,updateBusy=false,copyLock=false,copyBusy=false,returnPatient=null,summarySuspended=false;
const readContext=()=>T?T.bounded(bridge({type:'nexo.patient.context'})):bridge({type:'nexo.patient.context'});
async function bridge(message){
  const response=await chrome.runtime.sendMessage(message);
  if(!response?.ok)throw Object.assign(Error(response?.error||'Biblioteca no disponible.'),{code:response?.code,retryable:response?.retryable===true});
  return response.result;
}
async function readLibrary(operation,turn=sequence,component=provider?.kind==='drive'?'drive':'library'){
 let attempt=1;
 try{
  const result=await N.read(operation,{isCurrent:()=>turn===sequence&&!document.hidden&&activeView==='library',onAttempt:n=>{attempt=n;if(n>1)connectionRecord(component,'retrying',n);}});
  connectionRecord(component,'ok',attempt);return result;
 }catch(error){const code=N.failure(error).code;if(code!=='cancelled')connectionRecord(component,code,attempt);throw error;}
}
function clearSummary(){sequence++;selectedDocument=null;pendingUpdate=null;copyLock=false;copyBusy=false;summarySuspended=false;showNotice('');$('summary-text').value='';$('copy-summary').disabled=true;$('copy-status').textContent='';$('summary-status').textContent='';}
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
    if(handle){if(await handle.queryPermission({mode:'read'})==='granted'){const drive=new D.DriveLibrary(handle);drive.kind='drive';return drive;}connectionRecord('drive','permission');}
  }catch(_){/* El acceso local sigue disponible si falla IndexedDB. */}
  const local={kind:'mini',token:null,list:async()=>{const catalog=await bridge({type:'nexo.library.list'});local.token=catalog.openToken;return catalog;},read:(id,sha256)=>bridge({type:'nexo.library.read',id,sha256}),open:id=>bridge({type:'nexo.library.open',id,token:local.token}),patient:async id=>(await local.list()).patients.find(patient=>patient.id===id)};return local;
}
async function refresh(){
  clearSummary();$('retry-library').hidden=true;const request=sequence;
  loading=true;$('refresh-library').disabled=true;$('library-status').textContent='Cargando resúmenes…';
  try{
    const next=await chooseProvider(),catalog=await readLibrary(()=>next.list(),request,next.kind==='drive'?'drive':'library');
    if(request!==sequence || activeView!=='library')return;
    if(!catalog.available)throw Error('Conecta tu carpeta Pacientes de Drive.');
    if(catalog.version!==1 || !Array.isArray(catalog.patients))throw Object.assign(Error('Biblioteca no compatible.'),{code:'incompatible'});
    for(const patient of catalog.patients){C.rut(patient.rut);if(typeof patient.name!=='string'||!Array.isArray(patient.documents))throw Error('Biblioteca pendiente de revisión.');}
    provider=next;$('library-origin').textContent=next.kind==='drive'?'Drive · carpeta sincronizada':'Mini · archivo local';$('connect-drive').textContent=next.kind==='drive'?'Cambiar conexión de Drive':'Conectar carpeta de Drive';patients=catalog.patients.sort((a,b)=>a.name.localeCompare(b.name,'es',{sensitivity:'base'}));loading=false;renderPatients();
    if(catalog.issues)$('library-status').textContent+=' · '+catalog.issues+' archivo(s) requieren revisión';
    const resume=returnPatient;returnPatient=null;
    const previous=resume&&patients.find(patient=>patient.id===resume.patient.id&&samePatient(patient,resume.patient));
    if(previous)selectPatient(previous,resume.context);else void followCurrentPatient();
  }catch(error){if(request===sequence){patients=[];provider=null;$('library-origin').textContent='';loading=false;renderPatients();$('library-status').textContent=error.message||'No se pudo cargar la biblioteca.';$('retry-library').hidden=false;}}
  finally{if(request===sequence){loading=false;$('refresh-library').disabled=false;}}
}
function selectPatient(patient,fromContext=false){
  clearSummary();selected=patient;contextSelection=fromContext;$('library-list-view').hidden=true;$('summary-view').hidden=false;
  $('open-patient-folder').hidden=!(patient.folderUrl||patient.openable&&provider?.open);
  $('patient-name').textContent=patient.name;$('patient-rut').textContent=patient.rut;$('summary-date').textContent='';
  $('summary-version').replaceChildren();$('version-control').hidden=patient.documents.length<2;
  if(!patient.documents.length){showNotice('Resumen aún no disponible');return;}
  const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Elegir versión';$('summary-version').append(placeholder);
  for(const document of patient.documents){const option=window.document.createElement('option');option.value=document.id;option.textContent=document.date||'Archivo existente';$('summary-version').append(option);}
  if(patient.documents.length===1)void readSummary(patient.documents[0]);
}
async function readSummary(document){
  clearSummary();const turn=sequence,patient=selected,context=contextSelection?selected:lastContext;$('summary-status').textContent='Cargando…';
  try{
    const result=await readLibrary(()=>provider.read(document.id,document.sha256),turn);
    if(turn!==sequence || selected!==patient || activeView!=='library')return;
    if(context!==undefined)await ensureContext(context);
    if(turn!==sequence||selected!==patient)return;
    const identity=C.documentIdentity(result.text,patient.name);
    if(result.id!==document.id || result.sha256!==document.sha256 || identity.rut!==patient.rut || !C.sameName(identity.name,patient.name))throw Error('La identidad del resumen no coincide.');
    selectedDocument={...document,status:result.status};$('summary-text').value=result.text;
    $('summary-date').textContent=[document.date?'Guardado '+document.date:'Archivo existente',document.referenceDate?'Referencia '+document.referenceDate:''].filter(Boolean).join(' · ');
    $('summary-status').textContent=C.canCopy(selectedDocument)?'':result.status==='stale'?'Documentos nuevos o distintos · resumen pendiente de revisión.':'Archivo modificado · revisión pendiente.';
    $('copy-summary').disabled=!canCopySelected();
    if(!C.canCopy(selectedDocument))showNotice(result.status==='stale'?'Resumen pendiente de revisión':'Archivo modificado · revisión pendiente');
  }catch(error){if(turn===sequence){if(error.code==='context'){invalidateContext();return;}$('summary-text').value='';$('summary-status').textContent=error.message||'No se pudo leer el resumen.';$('copy-summary').disabled=true;showNotice('Revisa la conexión o actualiza el resumen.',provider?.kind==='drive'?'connect':'update');}}
}
function canCopySelected(){return !copyBusy&&!copyLock&&C.canCopy(selectedDocument);}
function showNotice(message,action='update'){
  $('summary-notice').hidden=!message;$('summary-notice-text').textContent=message;
  $('apply-update').hidden=!message||action!=='update';$('summary-reconnect').hidden=!message||action!=='connect';
}
async function checkForUpdate(){
  if(summarySuspended||updateBusy||copyBusy||activeView!=='library'||document.hidden||!selected||!selectedDocument)return;
  updateBusy=true;const turn=sequence,patient=selected,previous=selectedDocument,context=contextSelection?selected:lastContext;
  try{
    const fresh=await readLibrary(()=>provider.patient(patient.id),turn);
    if(turn!==sequence||selected!==patient)return;
    if(!fresh||fresh.id!==patient.id||!samePatient(fresh,patient)||!Array.isArray(fresh.documents))throw Error('Expediente no verificable.');
    if(context!==undefined)await ensureContext(context);
    if(turn!==sequence||selected!==patient)return;
    patients=patients.map(item=>item.id===fresh.id?fresh:item);
    const unchanged=fresh.documents.find(item=>item.id===previous.id&&item.sha256===previous.sha256&&item.status===previous.status);
    if(unchanged){copyLock=false;pendingUpdate=null;showNotice('');}
    else{
      pendingUpdate=fresh;copyLock=true;$('copy-status').textContent='';
      const different=fresh.documents.some(item=>item.id!==previous.id||item.sha256!==previous.sha256);
      showNotice(different?'Nuevo resumen disponible':'Resumen pendiente de revisión · texto anterior conservado');
    }
    $('copy-summary').disabled=!canCopySelected();
  }catch(error){
    if(turn===sequence){
      if(error.code==='context'){invalidateContext();return;}
      summarySuspended=true;copyLock=true;$('copy-status').textContent='';$('copy-summary').disabled=true;
      showNotice('No se pudo comprobar '+(provider?.kind==='drive'?'Drive':'la biblioteca')+' · texto conservado',provider?.kind==='drive'?'connect':'update');
    }
  }finally{updateBusy=false;}
}
$('apply-update').addEventListener('click',async()=>{
  if(!selected)return;const patient=selected,turn=sequence,context=contextSelection;
  $('apply-update').disabled=true;
  try{
    const fresh=pendingUpdate||await readLibrary(()=>provider.patient(patient.id),turn);
    if(turn!==sequence||selected!==patient)return;
    if(!fresh||fresh.id!==patient.id||!samePatient(fresh,patient))throw Error('Expediente no verificable.');
    if(context)await ensureContext(patient);
    if(turn!==sequence||selected!==patient)return;
    const updated=patients.map(item=>item.id===fresh.id?fresh:item);patients=updated;
    selectPatient(fresh,context);
  }catch(error){if(turn===sequence){if(error.code==='context')invalidateContext();else showNotice('No se pudo actualizar. Texto anterior conservado.',provider?.kind==='drive'?'connect':'update');}}
  finally{$('apply-update').disabled=false;}
});
const summaryTimer=setInterval(checkForUpdate,15000);
window.addEventListener('pagehide',()=>clearInterval(summaryTimer));
window.addEventListener('focus',()=>{void followCurrentPatient();void checkForUpdate();});
$('summary-version').addEventListener('change',()=>{const document=selected?.documents.find(d=>d.id===$('summary-version').value);if(document)void readSummary(document);else clearSummary();});
$('patient-search').addEventListener('input',renderPatients);$('change-patient').addEventListener('click',()=>{followContext=false;listView();});$('refresh-library').addEventListener('click',()=>{listView();void refresh();});
$('copy-summary').addEventListener('click',async()=>{
  const document=selectedDocument,patient=selected,turn=sequence,context=contextSelection?selected:lastContext;
  if(!canCopySelected()||!patient)return;const copyOperation={};copyBusy=copyOperation;$('copy-summary').disabled=true;$('copy-status').textContent='Comprobando…';
  try{
    if(context!==undefined)await ensureContext(context);if(turn!==sequence)return;
    const result=await readLibrary(()=>provider.read(document.id,document.sha256),turn);
    if(turn!==sequence || selected!==patient)return;
    const identity=C.documentIdentity(result.text,patient.name);
    if(result.id!==document.id || result.sha256!==document.sha256 || identity.rut!==patient.rut || !C.sameName(identity.name,patient.name) || !C.canCopy(result))throw Error('El resumen cambió. Actualiza la lista.');
    if(context!==undefined)await ensureContext(context);
    if(turn!==sequence||selected!==patient)return;
    $('summary-text').value=result.text;
    try{await navigator.clipboard.writeText(result.text);if(turn===sequence)$('copy-status').textContent='Copiado';}
    catch(_){if(turn===sequence){$('summary-text').focus();$('summary-text').select();$('copy-status').textContent='Texto seleccionado · pulsa ⌘C';}}
  }catch(error){if(turn===sequence){if(error.code==='context'){clearSummary();$('summary-status').textContent=error.message;}else{copyLock=true;$('copy-status').textContent='';const changed=/cambió|identidad/.test(error.message||'');showNotice(changed?'El resumen cambió · texto anterior conservado':'No se pudo comprobar el resumen. Texto anterior conservado.',changed?'update':provider?.kind==='drive'?'connect':'update');}}}
  finally{if(copyBusy===copyOperation)copyBusy=false;if(turn===sequence)$('copy-summary').disabled=!canCopySelected();}
});
$('open-full').addEventListener('click',async()=>{try{await bridge({type:'nexo.panel.tab',view:activeView});}catch(_){$('library-status').textContent='No se pudo abrir la pestaña.';}});
async function connectDrive(){
  listView();const turn=sequence;reconnectHandle=null;$('reconnect-drive').hidden=true;$('setup-status').textContent='';$('library-list-view').hidden=true;$('drive-setup').hidden=false;
  try{const handle=await D.savedHandle();if(turn!==sequence)return;reconnectHandle=handle||null;$('reconnect-drive').hidden=!handle;}
  catch(_){/* Se puede seleccionar otra carpeta si no se recupera el permiso. */}
}
$('connect-drive').addEventListener('click',()=>{returnPatient=null;return connectDrive();});
$('summary-reconnect').addEventListener('click',()=>{returnPatient=selected?{patient:selected,context:contextSelection}:null;return connectDrive();});
$('retry-library').addEventListener('click',()=>void refresh());
$('reconnect-drive').addEventListener('click',async()=>{
  if(!reconnectHandle)return;const turn=sequence;
  try{
    const permission=await reconnectHandle.requestPermission({mode:'read'});
    if(turn!==sequence)return;
    if(permission!=='granted')throw Error('Permiso pendiente. Puedes seleccionar otra carpeta.');
    resetDriveProbe();listView();void refresh();
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
    await D.savedHandle(handle);if(turn!==sequence)return;resetDriveProbe();$('setup-status').textContent='Carpeta conectada';listView();void refresh();
  }catch(error){if(turn===sequence&&error.name!=='AbortError')$('setup-status').textContent=error.name==='SecurityError'?'Abre Nexo en una pestaña para seleccionar la carpeta.':error.message||'No se pudo conectar la carpeta.';}
});
$('forget-drive').addEventListener('click',async()=>{try{await D.savedHandle(null);resetDriveProbe();listView();void refresh();}catch(_){$('setup-status').textContent='No se pudo desconectar la carpeta.';}});
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
  if(!samePatient(current.patient,patient))throw Object.assign(Error('La ficha cambió. Vuelve a elegir al paciente.'),{code:'context'});
}
async function followCurrentPatient(){
  if(contextBusy||loading||!provider||activeView!=='library'||document.hidden||!$('drive-setup').hidden)return;
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
let healthBusy=false,driveBusy=false,driveProbe=null,driveGeneration=0;
function resetDriveProbe(){driveGeneration++;driveProbe=null;void checkDriveConnection();}
function connectionRecord(component,code,attempt=1){connectionState.record(component,code,attempt);renderConnection();}
function renderConnection(){
 $('worker-status').textContent=connectionState.label('mini');
 $('mini-connection').textContent=connectionState.label('mini');$('drive-connection').textContent=connectionState.label('drive');
 for(const component of ['mini','drive'])$(component+'-checked').textContent=N.stamp(connectionState.current[component]?.at);
 $('connection-reconnect').hidden=!['permission','not_connected','unavailable','timeout'].includes(connectionState.current.drive?.code);
}
async function checkDriveConnection(){
 if(driveBusy||document.hidden)return;driveBusy=true;const generation=driveGeneration;let attempt=1;
 try{
  const handle=await D.savedHandle();
  if(!handle){connectionRecord('drive','not_connected');return;}
  if(await handle.queryPermission({mode:'read'})!=='granted'){connectionRecord('drive','permission');return;}
  await N.read(()=>{
   // Si una lectura no cancelable tarda, reutilizarla sin abrir sondeos paralelos.
   if(!driveProbe){const probe={};driveProbe=probe;probe.promise=(async()=>{
    if(handle.kind!=='directory'||handle.name!==ClinicalCatalog.library.patientsFolder)throw Object.assign(Error('Carpeta no válida.'),{code:'integrity'});
    const entries=handle.entries();try{await entries.next();}finally{await entries.return?.();}
   })().finally(()=>{if(driveProbe===probe)driveProbe=null;});}
   return driveProbe.promise;
  },{isCurrent:()=>!document.hidden,onAttempt:n=>{attempt=n;if(n>1)connectionRecord('drive','retrying',n);}});
  if(generation===driveGeneration)connectionRecord('drive','ok',attempt);
 }catch(error){if(generation===driveGeneration&&N.failure(error).code!=='cancelled')connectionRecord('drive',N.failure(error).code,attempt);}
 finally{driveBusy=false;if(generation!==driveGeneration)void checkDriveConnection();}
}
async function refreshWorker(){
 if(!T||healthBusy||document.hidden)return;healthBusy=true;let localAttempt=1,signalAttempt=1;
 try{
  try{
   const local=await N.read(()=>bridge({type:'nexo.worker.health'}),{isCurrent:()=>!document.hidden,onAttempt:n=>{localAttempt=n;if(n>1)connectionRecord('mini','retrying',n);}});
   if(local.app!=='laboratorios-descargas'||local.version!==1)throw Object.assign(Error('Versión local no compatible.'),{code:'incompatible'});
   if(local.queue&&local.worker?.running){connectionRecord('mini','ok',localAttempt);return;}
  }catch(error){
   if(N.failure(error).code==='cancelled')return;
   if(N.failure(error).code==='incompatible'){connectionRecord('mini','incompatible');return;}
   if(N.failure(error).code!=='cancelled')connectionRecord('mini',N.failure(error).code,localAttempt);
  }
  const inbox=await T.connection('inbox');
  if(!inbox||await inbox.queryPermission({mode:'read'})!=='granted'){connectionRecord('mini','unknown');return;}
  const worker=T.worker(await N.read(()=>T.read(inbox,'worker.json'),{isCurrent:()=>!document.hidden,onAttempt:n=>{signalAttempt=n;}}));
  connectionRecord('mini',({ready:'ok',stale:'stale',attention:'attention',unknown:'clock'})[worker.status]||'unknown',signalAttempt);
 }catch(error){if(N.failure(error).code!=='cancelled')connectionRecord('mini',N.failure(error).code,signalAttempt);}
 finally{healthBusy=false;}
}
$('connection-details').addEventListener('toggle',()=>{if($('connection-details').open){void checkDriveConnection();void refreshWorker();}});
$('connection-reconnect').addEventListener('click',()=>{
 const previous=selected?{patient:selected,context:contextSelection}:null;
 $('connection-details').open=false;switchView('library');returnPatient=previous;void connectDrive();
});
$('copy-diagnostic').addEventListener('click',async()=>{
 const text=connectionState.diagnostic();$('diagnostic-text').value=text;
 try{await navigator.clipboard.writeText(text);$('diagnostic-status').textContent='Diagnóstico copiado';$('diagnostic-text').hidden=true;}
 catch(_){$('diagnostic-text').hidden=false;$('diagnostic-text').focus();$('diagnostic-text').select();$('diagnostic-status').textContent='Texto seleccionado · pulsa ⌘C';}
});
renderConnection();void checkDriveConnection();
if(T){void refreshWorker();const healthTimer=setInterval(()=>{void refreshWorker();void checkDriveConnection();},30000);window.addEventListener('pagehide',()=>clearInterval(healthTimer));}
