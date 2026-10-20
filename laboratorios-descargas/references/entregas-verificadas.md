# Registro y vigencia de entregas

Descarga, redacción, copia local y sincronización son estados independientes. `status=complete` corresponde a fuentes; `fulfillment=complete` exige además todas las entregas de la orden archivadas. La sincronización remota se declara por separado. Codex redacta y coteja clínicamente; el programa valida identidad de encabezado, fechas, archivos, referencias y copias. No certifica por sí solo la exactitud médica de la prosa.

## Contratos canónicos

- `assets/clinical_catalog.json`: fuentes, períodos, contenidos y productos MMRAD. Python y formulario usan el mismo catálogo. `clinical_catalog.js`, controles y formulario portátil se generan con `build_portable_form.py`; no editar sus copias.
- `reporte-clinico/references/modelos-entrega.json`: modelos, disponibilidad de plantilla y entrega basal obligatoria. El generador incorpora este catálogo al formulario. Las skills explican las decisiones clínicas; remiten aquí para el protocolo operativo.
- `clinical_request.py`: valida la entrada y su identidad; `clinical_recovery.py` conserva y reconcilia avances. Ninguna entrega cambia pacientes, período ni `asOf`.

## Redactar y registrar

1. Obtener `/api/delivery?id=ID` en el lanzador activo: incluye los archivos vigentes, el nombre verificado, la revisión SHA-256 del conjunto de evidencia y un objeto de registro por paciente. Leer las fuentes completas pertinentes; una página abierta o un encargo copiado no es una entrega.
2. Escribir el TXT basal UTF-8 en la ruta de trabajo propuesta. Encabezado en líneas separadas: `Paciente: …`, `RUT: …`, `Fecha de elaboración: DD-MM-AAAA`, `Fecha de referencia: DD-MM-AAAA`. Fecha de elaboración real Pacific/Easter; conservar la referencia de la orden. Sin documentos utilizables, declarar «No se obtuvo documentación clínica verificable para elaborar antecedentes en esta corrida». Si falta nombre verificado, no inventarlo ni crear un expediente por RUT: el TXT queda local y el archivo nominal pendiente.
3. Completar el JSON del contexto; retirar el campo auxiliar `patientName`. `citations` contiene `{path, sha256, pages: [1], claim: "afirmación sustentada"}` por afirmación/grupo clínico. PDF exige páginas existentes; otros archivos usan `pages: []`. `notes` contiene discrepancias y pendientes. No mover este mapa al resumen clínico.
4. Ejecutar con el Python del entorno clínico: `scripts/register_delivery.py RUTA_REGISTRO.json` desde `laboratorios-descargas`. Usa el lanzador local, no otra cola paralela. El programa comprueba ámbito, identidad, fechas, revisión, hashes y páginas; guarda copias inmutables y genera el sustento en TXT. Reenviar contenido idéntico recupera el registro. Un cambio en la evidencia rechaza un registro antiguo: obtener otro encargo y revisar la redacción.
5. Comprobar `/api/status?id=ID`: `artifacts` por paciente/producto distingue `pending` (redacción), `verified` (registro local, falta copia), `archived` (TXT y sustento copiados y cotejados), `stale` (fuentes cambiaron), `modified` (registro dañado o entrega alterada/ausente). `archive.sync=confirmed` exige comprobación remota; `archived` por sí solo acredita copia local.

El registro está en `.entregas/registro.json` dentro de los datos del trabajo; cada revisión conserva sus bytes en una carpeta propia. Se publica atómicamente después de ambos archivos. Un reinicio entre registro y archivo recupera la entrega sin redactarla de nuevo. Un registro dañado se conserva para revisión y no se declara completado. No editar los archivos registrados; corregir el borrador y registrar una revisión nueva.

Para un formato adicional ya redactado, usar su ID de modelo en `kind`, un archivo TXT/DOCX/PDF dentro del trabajo, con nombre que incluya su fecha DD-MM-AAAA e identidad en el encabezado. Comparte revisión, referencias y registro; no sustituye el basal. Una plantilla institucional pendiente deja ese producto pendiente y permite completar el resto.

## Vista vigente

`Control y trazabilidad/Entregas vigentes.json` selecciona explícitamente una copia por producto. Regla: mayor fecha de referencia `asOf`; en empate, solicitud creada más recientemente; dentro del mismo trabajo, última revisión registrada y verificada. Volver a archivar una solicitud antigua conserva una copia histórica y no desplaza la actual. Los PDF integrados de cada fuente usan la misma regla. Un período más corto o cobertura parcial no se oculta: conserva su alcance y rótulo correspondiente.

Las revisiones sustituidas gestionadas por este registro pasan a `Control y trazabilidad/Archivo anterior/Entregas/PRODUCTO/`. La operación conserva originales locales y se recupera tras interrupción. No retirar archivos anteriores desconocidos ni deducir su vigencia por el nombre. Si la copia actual fue editada o falta, bloquear su sustitución, conservar esa edición y declarar revisión pendiente. No migrar resúmenes históricos al nuevo registro sin leerlos y verificarlos.

Una entrega `stale` permanece conservada mientras se prepara su actualización; el panel la identifica para revisión y no considera cerrada la orden. La carpeta de lectura no contiene logs ni estados. En Drive, comprobar por separado la propagación de traslados y el contenido remoto antes de declarar la vista sincronizada.
