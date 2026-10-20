const $ = id => document.getElementById(id);
const form = $('request-form');
if(new URLSearchParams(location.search).get('embedded')==='1')document.body.classList.add('nexo-embedded');
const labels = {...ClinicalCatalog.sources,mmrad_images:'Imágenes MMRAD'};
let submitting = false, bridgeVersion = 0;
function selectedSources() { return Array.from(form.querySelectorAll('input[name="source"]:checked'),input => input.value); }
const periods = ClinicalCatalog.periods.filter(period => period.value !== 'latest');
function patientSelection() {
  const all = [...new Set(form.elements.ruts.value.split(/[\s,;]+/).filter(Boolean).map(x => x.replace(/\./g,'').toUpperCase()))];
  const valid = all.filter(rut => {
    const {minDigits,maxDigits} = ClinicalCatalog.identity;
    if (!new RegExp(`^\\d{${minDigits},${maxDigits}}-[0-9K]$`).test(rut)) return false;
    const [body,digit] = rut.split('-');
    let sum = 0;
    [...body].reverse().forEach((n,i) => { sum += Number(n) * (2 + i % 6); });
    const remainder = 11 - sum % 11;
    return digit === (remainder === 11 ? '0' : remainder === 10 ? 'K' : String(remainder));
  });
  return {all,valid,invalid:all.length-valid.length};
}
function mmradSelection() {
  const reports = form.elements.mmradReports.checked;
  const types = [];
  if (form.elements.mmradRadiographs.checked) types.push('radiographs');

  return {types, mode:reports ? (types.length ? 'both' : 'reports') : 'images', empty:!reports && !types.length};
}
function currentPeriod() {
  return $('latest-only').checked ? {value:'latest',label:'Último registro'} : periods[Number($('period-range').value)];
}
function updatePeriod() {
  const period = currentPeriod(), latest = period.value === 'latest';
  form.elements.period.value = period.value;
  $('period-label').textContent = period.label;
  $('period-range').disabled = latest;
  $('period-range').setAttribute('aria-valuetext',periods[Number($('period-range').value)].label);
  $('period-range').style.setProperty('--range-fill', `${Number($('period-range').value)*100/(periods.length-1)}%`);
  for (const button of document.querySelectorAll('[data-period]')) {
    button.setAttribute('aria-pressed',String(!latest && button.dataset.period === $('period-range').value));
  }
  if (latest) $('date-window').textContent = 'El último registro elegible de cada fuente';
  else {
    const parts = new Intl.DateTimeFormat('en-GB',{timeZone:'Pacific/Easter',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const part = type => Number(parts.find(p => p.type === type).value);
    const end = new Date(Date.UTC(part('year'),part('month')-1,part('day'))), start = new Date(end);
    if (period.days) start.setUTCDate(start.getUTCDate()-period.days);
    else {
      start.setUTCDate(1);start.setUTCMonth(start.getUTCMonth()-period.months);
      const lastDay = new Date(Date.UTC(start.getUTCFullYear(),start.getUTCMonth()+1,0)).getUTCDate();
      start.setUTCDate(Math.min(end.getUTCDate(),lastDay));
    }
    const formatted = d => [d.getUTCDate(),d.getUTCMonth()+1,d.getUTCFullYear()].map((n,i) => i<2 ? String(n).padStart(2,'0') : n).join('-');
    $('date-window').textContent = `${formatted(start)} → ${formatted(end)}`;
  }
}
const customPeriods = {}, expandedPeriods = new Set();
function sourcePeriods() {
  return Object.fromEntries(selectedSources().filter(source => Object.hasOwn(customPeriods,source))
    .map(source => [source,customPeriods[source]]).filter(([,period]) => period !== currentPeriod().value));
}
function updateSourcePeriods(selected) {
  const allPeriods = ClinicalCatalog.periods;
  const shortLabels = allPeriods.map(period => period.short);
  for (const source of ['syslab','exalab','eloisa','his','rayen','mmrad','email']) {
    const custom = Object.hasOwn(customPeriods,source), enabled = selected.includes(source);
    const slider = form.querySelector(`[data-source-period="${source}"]`);
    const button = form.querySelector(`[data-period-toggle="${source}"]`);
    const index = allPeriods.findIndex(p => p.value === (custom ? customPeriods[source] : currentPeriod().value));
    slider.value = index;slider.disabled = !enabled;
    slider.setAttribute('aria-valuetext',allPeriods[index].label);
    slider.style.setProperty('--range-fill',`${index*100/(allPeriods.length-1)}%`);
    button.disabled = !enabled;
    button.classList.toggle('is-custom',custom);
    button.setAttribute('aria-label',`Período ${labels[source]}: ${allPeriods[index].label}${custom ? ', personalizado' : ''}`);
    const expanded = enabled && expandedPeriods.has(source);
    button.setAttribute('aria-expanded',String(expanded));
    $('source-period-'+source).hidden = !expanded;
    form.querySelector(`[data-period-label="${source}"]`).textContent = shortLabels[index]+(custom ? ' · propio' : '');
    form.querySelector(`[data-reset-period="${source}"]`).hidden = !custom;
  }
}
for (const button of form.querySelectorAll('[data-period-toggle]')) button.addEventListener('click',() => {
  const source = button.dataset.periodToggle;
  if (expandedPeriods.has(source)) expandedPeriods.delete(source);else expandedPeriods.add(source);
  updateFields();
});
for (const slider of form.querySelectorAll('[data-source-period]')) slider.addEventListener('input',() => {
  customPeriods[slider.dataset.sourcePeriod] = [...periods.map(p => p.value),'latest'][Number(slider.value)];
  updateFields();
});
for (const button of form.querySelectorAll('[data-reset-period]')) button.addEventListener('click',() => {
  const source = button.dataset.resetPeriod;
  delete customPeriods[source];expandedPeriods.delete(source);updateFields();
  form.querySelector(`[data-period-toggle="${source}"]`).focus();
});
$('apply-period-all').addEventListener('click',() => {
  for (const source of Object.keys(customPeriods)) delete customPeriods[source];
  expandedPeriods.clear();updateFields();
});
function sourceContent() {
  const result=Object.fromEntries(['eloisa','rayen'].filter(source => selectedSources().includes(source)).map(source =>
    [source,Array.from(form.querySelectorAll(`input[name="${source}Content"]:checked`),input => input.value)]));
  if (selectedSources().includes('mmrad') && form.elements.mmradReports.checked) result.mmrad=ClinicalCatalog.content.mmrad.filter(x=>x.default).map(x=>x.id);
  return result;
}
function updateFields() {
  form.elements.ruts.style.height = 'auto';
  form.elements.ruts.style.height = Math.min(160,form.elements.ruts.scrollHeight+2)+'px';
  const selected = selectedSources(), patients = patientSelection(), imaging = mmradSelection();
  $('email-account').hidden = !selected.includes('email');
  const mmrad = selected.includes('mmrad');
  const contents = sourceContent();
  for (const source of ['eloisa','rayen']) {
    $(source+'-options').hidden = !selected.includes(source);
    $(source+'-content-summary').textContent = (contents[source] || []).length+((contents[source] || []).length === 1 ? ' seleccionado' : ' seleccionados');
    $(source+'-content-error').hidden = !contents[source] || contents[source].length > 0;
    for (const box of form.querySelectorAll(`input[name="${source}Content"]`)) box.disabled = !selected.includes(source);
  }
  const custom = form.elements.deliveryModel.value === 'custom';
  $('custom-delivery').hidden = !custom;
  form.elements.deliveryInstructions.disabled = !custom;
  const emptyCustom = custom && !form.elements.deliveryInstructions.value.trim();
  form.elements.deliveryInstructions.setAttribute('aria-invalid',String(emptyCustom));
  $('mmrad-options').disabled = !mmrad;$('mmrad-options').hidden = !mmrad;
  updateSourcePeriods(selected);
  $('summary-delivery').textContent = form.elements.deliveryModel.selectedOptions[0].textContent;
  $('delivery-summary').textContent = form.elements.deliveryModel.value === 'documents' ? 'Opcional' : form.elements.deliveryModel.selectedOptions[0].textContent;
  $('template-state').hidden = ClinicalCatalog.delivery.models.find(model => model.id === form.elements.deliveryModel.value)?.template_status !== 'pending';
  $('summary-periods').textContent = Object.entries(sourcePeriods()).map(([source,period]) => labels[source]+': '+([...periods,{value:'latest',label:'Último registro'}].find(p => p.value === period).label)).join(' · ');
  $('mmrad-error').hidden = !mmrad || !imaging.empty;
  for (const box of form.querySelectorAll('[data-group]')) {
    const names = box.dataset.group.split(','), count = names.filter(x => selected.includes(x)).length;
    box.checked = count === names.length;box.indeterminate = count>0 && count<names.length;
  }
  const invalid = patients.invalid || patients.all.length>ClinicalCatalog.identity.maxPatients;
  form.elements.ruts.setAttribute('aria-invalid',String(Boolean(invalid)));
  $('rut-status').textContent = patients.all.length>ClinicalCatalog.identity.maxPatients ? `Máximo ${ClinicalCatalog.identity.maxPatients} pacientes` : patients.invalid ? `${patients.invalid} RUT no válido(s)` : patients.valid.length ? `${patients.valid.length} paciente(s)` : 'Sin pacientes';
  $('rut-status').classList.toggle('field-error',Boolean(invalid));
  $('source-count').textContent = `${selected.length} de 7 fuentes seleccionadas`;
  $('summary-patients').textContent = patients.valid.length ? String(patients.valid.length) : '—';
  $('summary-period').textContent = currentPeriod().label;
  $('summary-sources').replaceChildren();
  for (const source of selected) {
    const chip = document.createElement('span');chip.className = 'summary-chip';chip.textContent = labels[source];$('summary-sources').append(chip);
  }
  if (!selected.length) $('summary-sources').textContent = 'Selecciona al menos una fuente.';
  $('summary-images').hidden = !mmrad;
  $('summary-images').textContent = 'MMRAD: '+[...(form.elements.mmradReports.checked ? ['informes TAC'] : []),...imaging.types.map(x => x === 'radiographs' ? 'radiografías' : 'ecografías')].join(' + ')+'.';
  $('run').disabled = submitting || emptyCustom || Object.values(contents).some(items => !items.length) || !selected.length || !patients.valid.length || Boolean(invalid) || (mmrad && imaging.empty);
  $('bridge-status').textContent = selected.some(name => ['exalab','eloisa','rayen'].includes(name)) ?
    bridgeVersion >= 2 ? 'Sesiones de Chrome: puente conectado.' : 'Las fuentes con sesión de Chrome se iniciarán cuando esté conectado el puente.' : '';
}
for (const box of form.querySelectorAll('[data-group]')) box.addEventListener('change',() => {
  for (const name of box.dataset.group.split(',')) form.querySelector(`input[name="source"][value="${name}"]`).checked = box.checked;
  updateFields();
});
for (const [id,checked] of [['select-all',true],['select-none',false]]) $(id).addEventListener('click',() => {
  for (const box of form.querySelectorAll('input[name="source"]')) box.checked = checked;
  updateFields();
});
for (const button of document.querySelectorAll('[data-period]')) button.addEventListener('click',() => {
  $('latest-only').checked = false;$('period-range').value = button.dataset.period;updatePeriod();updateFields();
});
$('period-range').addEventListener('input',() => { updatePeriod();updateFields(); });
$('latest-only').addEventListener('change',() => { updatePeriod();updateFields(); });
form.addEventListener('input',event => { $('form-error').hidden = true;if (!event.target.matches('[data-group]')) updateFields(); });
form.addEventListener('change',updateFields);

function requestSelection() {
  const selected = selectedSources(), patients = patientSelection(), imaging = mmradSelection();
  if (!patients.valid.length || patients.invalid || patients.all.length > ClinicalCatalog.identity.maxPatients) throw new Error('Revisa los RUT de los pacientes.');
  if (!selected.length) throw new Error('Selecciona al menos una fuente.');
  if (selected.includes('mmrad') && imaging.empty) throw new Error('Selecciona qué descargar de MMRAD.');
  const contents = sourceContent();
  if (Object.values(contents).some(items => !items.length)) throw new Error('Selecciona qué contenido obtener de cada Eloísa.');
  const instructions = form.elements.deliveryModel.value === 'custom' ? form.elements.deliveryInstructions.value.trim() : '';
  if (form.elements.deliveryModel.value === 'custom' && !instructions) throw new Error('Describe la entrega libre.');
  const data = new FormData(form);
  return {schema:2,ruts:patients.valid,source:selected.join(','),period:currentPeriod().value,
    emailAccount:'daniel.opazo@hospitalhangaroa.cl',sourcePeriods:sourcePeriods(),sourceContent:contents,deliveryInstructions:instructions,deliveryModel:data.get('deliveryModel'),eloisaScope:data.get('eloisaScope'),
    mmradMode:imaging.mode,mmradImageTypes:imaging.types,merge:data.has('merge'),patientMerge:data.has('patientMerge')};
}
