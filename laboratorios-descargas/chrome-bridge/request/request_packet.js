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
    return `$flujo-clinico\n\nEjecuta esta solicitud en el Mac mini usando las skills clínicas instaladas. Fecha de referencia: ${displayDate(packet.asOf)} (Pacific/Easter).\n`+
      'Lee laboratorios-descargas/references/solicitud-portatil.md, valida el bloque JSON e impórtalo con submit_request.py en la cola local conservando id y asOf; un reenvío debe recuperar el mismo trabajo. Si esta tarea corre en otro equipo, indícalo y conserva la solicitud para el Mac mini. No des por enviado ni ejecutado el trabajo por haber copiado este texto.\n'+
      'Respeta solo los pacientes, fuentes, períodos propios, contenidos por fuente, productos MMRAD y formato elegidos. Fija --as-of con asOf; no recalcules la fecha al pegar. Conserva y archiva los documentos verificados por nombre de paciente aunque fallen otras fuentes. Excluye imágenes de ecocardiografías.\n'+
      'Si se seleccionó email, usa $correo-clinico con emailAccount y su período; comprueba la cuenta conectada antes de consultar. Guarda sólo evidencia vinculada al paciente. Al cerrar toda orden, incluye el resumen numerado [X]/[~]/[ ] de fuentes en la respuesta y guarda el mismo texto en TXT, aunque no se pida documento de entrega. Consulta references/cierre-fuentes.md de laboratorios-descargas.\n'+
      'deliveryModel=documents significa solo archivos, sin redactar un documento adicional. deliveryModel=custom usa deliveryInstructions como encargo de redacción libre, sin exigir plantilla institucional. Si sourceContent.rayen incluye record, completa el flujo del visor descrito en rayen-epicrisis/references/ficha-completa.md y verifica el PDF; abrirlo no equivale a descargarlo. Para los modelos institucionales, usa la plantilla del usuario si está disponible; si falta, deja esa redacción pendiente y entrega las fuentes. No firmes ni publiques en la ficha.\n\n'+
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
