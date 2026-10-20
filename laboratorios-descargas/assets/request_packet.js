/* Portable request contract. No network, credentials, storage or execution. */
(function (root) {
  'use strict';
  function referenceDate(now) {
    const parts = new Intl.DateTimeFormat('en-GB',{timeZone:'Pacific/Easter',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
    const part = type => parts.find(p => p.type === type).value;
    return `${part('year')}-${part('month')}-${part('day')}`;
  }
  function displayDate(iso) { return iso.split('-').reverse().join('-'); }
  function build(selection, now = new Date(), id = [...root.crypto.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2,'0')).join('')) {
    return {kind:'hhr-clinical-request',version:4,id,target:'mac-mini',timeZone:'Pacific/Easter',asOf:referenceDate(now),
      request:{schema:2,ruts:[...selection.ruts],source:selection.source,period:selection.period,
        emailAccount:selection.emailAccount || 'daniel.opazo@hospitalhangaroa.cl',sourcePeriods:{...selection.sourcePeriods},sourceContent:Object.fromEntries(Object.entries(selection.sourceContent || {}).map(([source,items]) => [source,[...items]])),deliveryInstructions:selection.deliveryInstructions || '',deliveryModel:selection.deliveryModel,eloisaScope:selection.eloisaScope,
        mmradMode:selection.mmradMode,mmradImageTypes:[...selection.mmradImageTypes],
        merge:selection.merge,patientMerge:selection.patientMerge}};
  }
  function prompt(packet) {
    return `$flujo-clinico\n\nSolicitud para importar en el Mac mini. Fecha fija: ${displayDate(packet.asOf)} (Pacific/Easter).\n`+
      'Valida el JSON e impórtalo una sola vez con laboratorios-descargas/scripts/submit_request.py. Conserva id y asOf; un reenvío recupera el mismo trabajo. Si estás en otro equipo, conserva el JSON para el Mini y no afirmes que se ejecutó. La cola descarga y archiva las fuentes seleccionadas; no repitas manualmente las consultas ni amplíes pacientes, períodos o contenidos.\n'+
      'Intervén solo para sesiones/credenciales pendientes, errores de verificación y tareas que el motor aún no ejecuta: correo con $correo-clinico si fue seleccionado y ficha hospitalaria completa si se pidió record. Respeta el período propio de cada una. Nunca tomes abrir el visor como descarga verificada. Conserva archivos parciales; excluye imágenes de ecocardiogramas.\n'+
      'Toda corrida añade por paciente el TXT clínico basal con $resumen-antecedentes: DD-MM-AAAA Resumen antecedentes.txt, en Lectura y entregas, aunque deliveryModel=documents o se solicite otro modelo. Obtén el encargo de /api/delivery, redacta desde evidencia verificada y registra con register_delivery.py según references/entregas-verificadas.md; exige estado archived e informa sincronización aparte. No lo des por generado al terminar la descarga. custom añade deliveryInstructions; los modelos institucionales usan la plantilla disponible o quedan pendientes sin bloquear el TXT basal. Cierre numerado [X]/[~]/[ ] en respuesta y TXT de Control y trazabilidad, según references/cierre-fuentes.md. No firmes ni publiques en la ficha.\n\n'+
      '```json\n'+JSON.stringify(packet,null,2)+'\n```';
  }
  function tracker() {
    let key = '', packet = null;
    return {
      prepare(selection, now = new Date()) {
        const next = JSON.stringify([referenceDate(now),selection]);
        if (next !== key) { packet = build(selection,now);key = next; }
        return packet;
      },
      reset() { key = '';packet = null; }
    };
  }
  root.ClinicalRequest = {build,prompt,referenceDate,displayDate,tracker};
  if (typeof module !== 'undefined') module.exports = root.ClinicalRequest;
})(globalThis);
