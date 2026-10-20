/* Lectura acotada del componente público de identificación de Eloísa. */
function patientHeaderRows(){
 const rows=[];
 for(const name of [...document.querySelectorAll('.patient-name-div')].slice(0,8)){
  if(!name.getClientRects().length||name.closest('[hidden],[aria-hidden="true"]')||getComputedStyle(name).visibility!=='visible')continue;
  const region=name.closest('.info-pacient-by-rut')?.parentElement?.parentElement;
  if(!region)continue;
  const labels=[...region.querySelectorAll('.info-titles-paciente-by-rut')];if(labels.length>40)continue;
  for(const label of labels){
   if(!/^(RUT|RUN)\s*:?$/i.test(label.textContent.trim()))continue;
   const value=label.parentElement?.querySelector('.info-pacient-by-rut');
   if(value&&value.getClientRects().length)rows.push({name:name.textContent.trim().slice(0,200),rut:value.textContent.trim().slice(0,30)});
  }
 }
 return rows;
}
function normalizePatientRows(rows){
 if(!Array.isArray(rows)||!rows.length||rows.length>8)return null;
 const names=value=>value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().split(/\s+/).sort().join('|');
 const found=[];
 try{for(const row of rows){if(typeof row.name!=='string'||row.name.trim().split(/\s+/).length<2)return null;found.push({rut:ClinicalAgenda.rut(row.rut),name:row.name.trim()});}}
 catch(_){return null;}
 const first=found[0];return found.every(row=>row.rut===first.rut&&names(row.name)===names(first.name))?first:null;
}
async function currentPatient(){
 const tabs=await chrome.tabs.query({active:true,lastFocusedWindow:true});
 if(tabs.length!==1)return {patient:null};
 const tab=tabs[0];let url;try{url=new URL(tab.url);}catch(_){return {patient:null};}
 if(url.origin!=='https://clinicohangaroa.eloisa.cl'||!/^\/main(?:\/|$)/.test(url.pathname))return {patient:null};
 const [result]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:patientHeaderRows});
 return {patient:normalizePatientRows(result?.result)};
}
