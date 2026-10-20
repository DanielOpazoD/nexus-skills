/* Mismo selector para el panel local y el formulario dentro de la extensión. */
(function () {
  'use strict';
  const node = id => document.getElementById(id);
  if (!node('agenda-panel')) return;
  const extensionPage = location.protocol === 'chrome-extension:' && !!globalThis.chrome?.runtime?.id;
  let available = extensionPage, mode = 'manual', generation = 0, active = null, snapshot = null;
  const selected = new Set();
  function announce(text) { node('agenda-status').textContent = text; }
  function availability() {
    node('agenda-load').disabled = !available || !!active;
    node('agenda-help').hidden = available;
  }
  function changeMode(value) {
    mode = value;
    node('manual-patients').hidden = mode !== 'manual';
    node('agenda-panel').hidden = mode !== 'agenda';
    for (const button of document.querySelectorAll('[data-patient-mode]')) button.setAttribute('aria-pressed',String(button.dataset.patientMode===mode));
  }
  function counts() {
    const possible = (snapshot?.patients || []).filter(patient=>patient.selectable);
    node('agenda-all').checked = !!possible.length && selected.size === possible.length;
    node('agenda-all').indeterminate = selected.size > 0 && selected.size < possible.length;
    node('agenda-all').disabled = !possible.length;
    node('agenda-apply').disabled = !selected.size;
    node('agenda-apply').textContent = selected.size ? `Agregar ${selected.size} paciente(s)` : 'Agregar seleccionados';
  }
  function clearResults() {
    snapshot = null;selected.clear();node('agenda-rows').replaceChildren();node('agenda-results').hidden=true;counts();
  }
  function render(result) {
    if (!result || result.date !== node('agenda-date').value || !Array.isArray(result.patients)) throw Error('Respuesta de agenda incompatible.');
    const previous = new Set(selected);selected.clear();snapshot = result;
    const fragment = document.createDocumentFragment();
    for (const patient of result.patients) {
      const row = document.createElement('label');row.className='agenda-row';
      const checkbox = document.createElement('input');checkbox.type='checkbox';checkbox.value=patient.rut;checkbox.disabled=!patient.selectable;
      checkbox.setAttribute('aria-label',`${patient.name}, ${patient.rut}`);
      checkbox.checked = patient.selectable && previous.has(patient.rut);
      if (checkbox.checked) selected.add(patient.rut);
      const info = document.createElement('span'), name=document.createElement('strong'), details=document.createElement('small');
      name.textContent=patient.name;details.textContent=patient.rut+(patient.states.length ? ' · '+patient.states.join(', ') : '');info.append(name,details);
      const time=document.createElement('span');time.className='agenda-time';time.textContent=patient.times.join(' · ');
      checkbox.addEventListener('change',()=>{if (checkbox.checked) selected.add(patient.rut);else selected.delete(patient.rut);counts();});
      row.append(checkbox,info,time);fragment.append(row);
    }
    node('agenda-rows').replaceChildren(fragment);node('agenda-results').hidden=!result.patients.length;
    const date=ClinicalRequest.displayDate(result.date);
    node('agenda-identity').textContent='Mi agenda · Hanga Roa';
    const warning=result.status==='partial' ? ` · ${result.rejected+result.conflicts} registro(s) por revisar` : '';
    announce(result.patients.length ? `${date} · ${result.patients.length} paciente(s)${warning}` : result.status==='partial' ? `${date} · Agenda parcial; no hay pacientes seleccionables.` : `${date} · Sin pacientes citados.`);
    counts();
  }
  function finish(id, response) {
    if (!active || active.id !== id || active.generation !== generation) return;
    clearTimeout(active.timer);active=null;availability();
    if (!response?.ok) { announce((response?.error || 'No se pudo cargar la agenda.')+(snapshot ? ' Se conserva la lista anterior de esta fecha.' : ''));return; }
    try { render(response.result); } catch (_) { announce('La respuesta no coincide con la fecha solicitada. Se conserva la selección anterior.'); }
  }
  async function load() {
    if (!available || active) return;
    const date=node('agenda-date').value;
    try { ClinicalAgenda.day(date); } catch (error) { announce(error.message);return; }
    const id=[...crypto.getRandomValues(new Uint8Array(16))].map(n=>n.toString(16).padStart(2,'0')).join('');
    active={id,generation,timer:setTimeout(()=>finish(id,{ok:false,error:'La agenda no respondió. Comprueba la sesión de Eloísa.'}),25000)};
    availability();announce('Cargando agenda…');
    if (extensionPage) {
      try { finish(id,await chrome.runtime.sendMessage({type:'labs.agenda',id,date})); }
      catch (_) { finish(id,{ok:false,error:'Recarga la extensión y vuelve a cargar la agenda.'}); }
    } else window.postMessage({type:'labs.agenda-request',id,date},location.origin);
  }
  for (const button of document.querySelectorAll('[data-patient-mode]')) button.addEventListener('click',()=>changeMode(button.dataset.patientMode));
  node('agenda-load').addEventListener('click',load);
  node('agenda-date').value=ClinicalRequest.referenceDate(new Date());
  node('agenda-date').addEventListener('change',()=>{
    generation+=1;if(active) clearTimeout(active.timer);active=null;clearResults();availability();announce('');
  });
  node('agenda-all').addEventListener('change',()=>{
    for(const checkbox of node('agenda-rows').querySelectorAll('input[type="checkbox"]:not(:disabled)')) {
      checkbox.checked=node('agenda-all').checked;
      if(checkbox.checked) selected.add(checkbox.value);else selected.delete(checkbox.value);
    }
    counts();
  });
  node('agenda-apply').addEventListener('click',()=>{
    const existing=node('ruts').value.split(/[\s,;]+/).filter(Boolean).map(value=>value.replaceAll('.','').toUpperCase());
    const merged=[...new Set([...existing,...selected])];
    if(merged.length>200) { announce('La solicitud admite hasta 200 pacientes; reduce la selección.');return; }
    node('ruts').value=merged.join('\n');node('ruts').dispatchEvent(new Event('input',{bubbles:true}));changeMode('manual');node('ruts').focus();
  });
  window.addEventListener('message',event=>{
    if(event.source!==window || event.origin!==location.origin) return;
    if(event.data?.type==='labs.bridge-ready') { available=extensionPage || Number(event.data.version)>=3;availability(); }
    if(event.data?.type==='labs.agenda-result') finish(event.data.id,event.data);
  });
  window.addEventListener('pagehide',()=>{generation+=1;if(active)clearTimeout(active.timer);active=null;clearResults();});
  availability();counts();
  if(!extensionPage && location.protocol!=='file:') window.postMessage({type:'labs.bridge-ping'},location.origin);
})();
