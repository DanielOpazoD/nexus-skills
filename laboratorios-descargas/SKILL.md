---
name: laboratorios-descargas
description: Mostrar un formulario interactivo y descargar exámenes de Syslab/Exalab, atenciones de Rayen/Eloísa y HIS Hanga Roa, e informes o imágenes MMRAD RIS para varios RUT, con período común o propio por fuente y modelo de entrega elegido.
---

# Nexo · Descargas clínicas

Coordinar Syslab, Exalab, Eloísa, MMRAD, HIS, Eloísa Hospitalizados y Correo mediante [laboratorios_download.py](scripts/laboratorios_download.py), incluso con un paciente. Mantiene avance; procesa documentos antes de imágenes, con fuentes independientes ante fallos. Para el flujo completo usar [flujo-clinico](../flujo-clinico/SKILL.md).

## Preparar y ejecutar

Leer el [contrato común](references/verificacion.md), las skills de las fuentes seleccionadas y, antes de ejecutar, [operación](references/operacion.md): argumentos, autenticación, verificación de PDF, consolidación y reanudación. No cargar fuentes no solicitadas. Preferir los clientes programáticos descritos en la [matriz de acceso](references/modos-acceso.md): API cuando está implementada; HTTP directo en las otras fuentes. No sustituirlos por navegación manual de cada documento. La autenticación con Chrome sigue siendo necesaria para algunas fuentes.

- CLI: `--ruts`, `--source`, `--period`, `--output`. Períodos: `30d|3m|6m|1y|2y|5y|10y|latest`. `both` significa Syslab+Exalab; `all`, las seis fuentes; [Epicrisis Rayen](../rayen-epicrisis/SKILL.md) corresponde a `rayen`. `email` importa evidencia revisada con [correo-clinico](../correo-clinico/SKILL.md), cuenta institucional mediante `--email-account`. `all` conserva los seis portales históricos; para siete, usar lista explícita con `email`. El formulario local incluye las siete fuentes y envía la selección explícita.
- Períodos propios: `--source-periods` recibe un JSON `{fuente: período}` con excepciones al común. Sólo fuentes seleccionadas; aplica a informes e imágenes de esa fuente y se conserva al reanudar. No cambiar períodos sobre el mismo avance.
- Contenidos: conservar `sourceContent` y enviarlo como `--source-content` JSON. Leer las selecciones de [Ambulatorio](../eloisa-resultados/SKILL.md) y [Hospitalizados](../rayen-epicrisis/references/ficha-completa.md); no descartar opciones al pasar al puente/CLI. Ambulatorio incluye `attachments` por defecto en el formulario; MMRAD usa `ct_reports` para informes TAC. El [catálogo único](assets/clinical_catalog.json) alimenta validadores, puente y controles generados. Cambiar contenidos requiere otro avance.
- Entrega basal de toda corrida: [Resumen de antecedentes TXT](../resumen-antecedentes/SKILL.md) por paciente, también con `documents` y además del modelo elegido. La síntesis se redacta en Codex leyendo las fuentes; el motor de descarga no la redacta por sí solo. Conservar `deliveryInstructions` para `custom` y `deliveryModel` según el [catálogo](../reporte-clinico/references/modelos-entrega.json). Las plantillas institucionales pendientes no bloquean el TXT basal ni autorizan inventar ese formato. No marcar una redacción como generada al terminar la descarga.
- Eloísa sin selección explícita de contenidos: `medicos` por defecto; `todos` si se piden todas las atenciones. Declarar el filtro aplicado.
- MMRAD: el formulario ofrece informes TAC (`sourceContent.mmrad=["ct_reports"]`) y radiografías (`mmradImageTypes=["radiographs"]`), con `--mmrad-mode reports|images|both`. Radiografías sin informe son esperables; TAC sin PDF queda pendiente. Ecocardiogramas: informe en adjuntos de Eloísa, imágenes excluidas. Conservar el alcance explícito de solicitudes antiguas.
- `--list-only` no descarga. En toda descarga, el motor crea una copia de lectura PDF por fuente clínica con documentos verificados, ordenada de más reciente a más antiguo: LAB HHR, LAB HDS, Eloísa ambulatorio, MMRAD (solo informes TAC) y Eloísa Hospitalizados. La copia se genera incluso si el grupo es parcial, rotulada `PARCIAL`; el rango de meses corresponde a los documentos incluidos. Adjuntos ambulatorios e imágenes quedan aparte. `--merge` mantiene el consolidado técnico completo por fuente; `--patient-merge` añade un PDF global por paciente. Consolidar documentos no equivale a redactar un resumen.
- `--resume` conserva solicitud/fecha; no combinar con `--fresh`. Los no disponibles solo se reintentan por petición expresa mediante `--retry-unavailable`.

Para registrar productos redactados, comprobar su vigencia y cerrar una orden, leer [entregas verificadas](references/entregas-verificadas.md). El motor distingue fuentes completas de entregas pendientes: TXT basal y formatos adicionales requieren registro y copia comprobada. Si cambia la evidencia, la redacción queda para revisión; conserva la anterior. Períodos, contenidos y entregas tienen catálogos canónicos compartidos con el formulario.

Para abrir el lanzador o mostrar el formulario, leer [interfaz local](references/interfaz-local.md). El lanzador conserva trabajo y cola en `~/Documents/Descargas clínicas/` y copia automáticamente al expediente por nombre en Drive, verificando identidad e integridad. Presenta por separado copia local y sincronización remota; sin conexión autorizada a Drive, esta última queda pendiente.

La extensión añade un círculo en Eloísa Ambulatorio y dos espacios en su panel lateral: **Solicitar** y **Resúmenes**. Para leer/copiar antecedentes existentes desde el Mini o el Drive del Air, aplicar [panel de Eloísa y biblioteca](references/panel-eloisa.md). Lectura sin nueva búsqueda ni redacción; identidad y hash comprobados antes de copiar, sin pegar o guardar en la ficha.

Para elegir pacientes por fecha, usar «Desde agenda» en el panel o formulario de la extensión Chrome v3: funciona en Air y Mini con su propia sesión. Leer [agenda Eloísa](../eloisa-resultados/references/agenda.md); seleccionar pacientes no ejecuta la orden.

Para solicitudes del MacBook Air, leer [solicitud portátil](references/solicitud-portatil.md): «Enviar a Drive» deposita JSON con marcador de integridad y el receptor del Mini lo importa a la cola mientras el lanzador esté abierto. El acuse confirma importación, no finalización. Si se copia un texto o TXT, usar `submit_request.py` manualmente. Ambos caminos conservan ID, fecha de referencia, períodos y modelo; reenviar ID/contenido recupera el mismo trabajo.

## Acceso y continuidad

Leer [continuidad](references/continuidad.md) para precomprobación de sesiones, reautenticación única, reanudación por fuente, TLS/red restringida, fechas acotadas y concurrencia de imágenes. Las mejoras de acceso no amplían pacientes, fuentes ni períodos.

## Entrega parcial

Leer el resumen JSON por paciente/fuente aunque el proceso termine con error o falte el PDF único. Entregar y archivar todos los documentos verificados, incluidos los de `incompletos` y `.avance`. Un grupo parcial puede contener PDF individuales completos. Un archivo truncado o con identidad no verificada no sirve como evidencia.

El consolidado completo se omite si falta una fuente/registro requerido; **los archivos independientes y su información se entregan igualmente**. En una reanudación fallida, conservar la lista de archivos con hash vigente y mostrar «Documento obtenido previamente; actualización pendiente». No certificar un archivo modificado después de verificarse. Mantener el avance local para reanudar. El [contrato común](references/verificacion.md) define cierre, reporte y archivo.

Identidad de la aplicación: **Nexo**, con icono azul/violeta. [Activos y actualización](references/identidad-visual.md).

## Mantenimiento

Cambiar opciones requiere mantener el [contrato de entrada y recuperación](references/verificacion.md): validación compartida, identidad completa del avance y una fila por paciente/producto. Probar entradas inválidas sin efectos, reanudación incompatible y corrupción parcial con datos ficticios; no consultar pacientes para una revisión de código.

Para instalar, actualizar o verificar el paquete, leer [instalación reproducible](references/instalacion.md). `./check.command` comprueba dependencias fijadas, las skills clínicas, HTML generado y pruebas de motor/puentes con datos ficticios. No demuestra disponibilidad de portales ni se repite por cada descarga habitual. Las [fronteras del programa](references/verificacion.md#fronteras-del-programa) separan contrato, estado, persistencia, recuperación y ejecución.

## Cierre obligatorio

Aplicar [cierre-fuentes](references/cierre-fuentes.md): resumen numerado `[X]/[~]/[ ]` en cada respuesta que cierre una orden clínica y en TXT, también sin plantilla, con descarga parcial, cancelación o cero resultados. El motor/lanzador lo generan y guardan; Codex debe leerlo, incluirlo y enlazarlo. Correo usa Gmail en Codex, no el puente Chrome; el botón local copia su encargo y la reanudación importa la evidencia. Mensajes y adjuntos se entregan aparte del PDF único de portales.

**Capacidades pendientes:** Biopsias aún no tiene módulo ni fuente configurable; no incluirla en «todas» ni declarar una búsqueda negativa. Para alcance real y pasos que requieren Codex/visor, consultar [estado de capacidades](../flujo-clinico/references/estado-capacidades.md).
