---
name: resumen-antecedentes
description: Generar un TXT clínico breve y autocontenido por paciente en cada corrida del flujo HHR, con antecedentes, diagnósticos, fármacos, exámenes y últimas evaluaciones fechadas. Es la entrega basal incluso sin formato adicional o junto a otro informe.
---

# Resumen de antecedentes

Invocación: `$resumen-antecedentes`. Salida **predeterminada de toda corrida clínica por paciente**, aunque sólo se hayan pedido fuentes o se solicite además telereumatología, epicrisis u otro formato. La instrucción posterior explícita de no redactar/no guardar prevalece. No aplicar a mantenimiento del programa ni generar resúmenes nuevos de todos los pacientes históricos por cargar esta skill.

Usar sólo pacientes y evidencia del trabajo vigente; no ampliar fuentes, fechas o consultas. Leer [reporte-clinico](../reporte-clinico/SKILL.md) para verificar identidad y datos. El resumen es redacción clínica en Codex, separada del motor determinista de descargas: una descarga completa o un encargo copiado no acredita que este TXT esté redactado.

## Contenido y estilo

Evolución sucinta, en párrafos continuos breves; encabezados cortos sólo cuando faciliten lectura. Español notificativo, factual, sin preguntas, conectores de relleno, recomendaciones ni interpretaciones añadidas. Autocontenido: nombre y RUT verificados, fecha de elaboración y fecha de referencia si difieren. Edad sólo con nacimiento verificado y cálculo a la fecha de referencia. No necesita plantilla institucional ni DOCX.

Orden habitual, omitiendo bloques sin información comprobada:

1. **Antecedentes y diagnósticos relevantes:** enfermedades, hitos, cirugías/hospitalizaciones y alergias relevantes documentadas. Distinguir diagnóstico confirmado de sospecha consignada; no deducirlos de códigos, síntomas o medicamentos. Integrar la historia sin repetir datos.
2. **Fármacos:** esquema consignado más reciente, con fecha. Nombre, dosis, vía y frecuencia si constan. Describir como tratamiento vigente sólo cuando esté confirmado; para recetas históricas, «Prescripción del DD-MM-AAAA: …». No inferir continuidad, suspensión ni adherencia.
3. **Exámenes complementarios:** resultados relevantes y fechados de laboratorio, informes TAC/MMRAD, ecocardiograma, endoscopia, colonoscopia u otros documentos recuperados. Revisar los PDF adjuntos de Eloísa: pueden contener estos informes aunque el listado no los identifique. Transcribir conclusiones atribuidas al informe; imágenes sin informe no autorizan una interpretación. Laboratorio en prosa compacta por fecha: Hb, VCM, GB/linfocitos y plaquetas; creatinina/BUN, PCR/VHS, Na/K, perfil lipídico, CK y otros datos pertinentes. Orina enfocada en proteínas, leucocitos, GR, RAC/RPC cuando consten. No copiar toda la fórmula ni todos los paneles; conservar unidades necesarias según [exámenes breves](../reporte-clinico/references/examenes-breves.md).
4. **Últimas evaluaciones clínicas:** fecha, especialidad/profesional si consta, situación clínica y conducta documentada, de la más reciente hacia atrás. Incluir controles anteriores sólo si explican un cambio relevante. No atribuir un examen físico antiguo a la última atención.

«Sin plantear dudas» significa no añadir preguntas ni comentarios editoriales. No transformar una sospecha en certeza ni ocultar una discrepancia que cambie el sentido clínico. Mantener la precisión factual imprescindible en el texto; llevar incidencias y detalles de revisión al documento de control. No inventar resultados negativos o antecedentes ausentes. Con fuentes parciales, resumir lo verificado sin cancelar el resto; delimitar el alcance con una frase factual si afecta la lectura. Sin evidencia clínica utilizable, generar un TXT que diga «No se obtuvo documentación clínica verificable para elaborar antecedentes en esta corrida», identificado y fechado; no llenar secciones con datos supuestos.

## Sustento y archivo

Leer los documentos completos pertinentes, incluidos adjuntos; verificar paciente, fecha, cifras y vigencia. El TXT clínico no lleva referencias por frase ni logs. Guardar `DD-MM-AAAA Sustento Resumen antecedentes.txt` en `Control y trazabilidad/`: mapa breve de afirmaciones a archivo/página/fecha, discrepancias y pendientes. No usar un resumen anterior como única prueba si las fuentes están disponibles. Una corrección material debe reflejarse en el resumen, no quedar escondida en el mapa.

Nombre exacto de base: **`DD-MM-AAAA Resumen antecedentes.txt`**, fecha real de elaboración en Pacific/Easter. Para una orden de la cola, redactar primero en su carpeta local y aplicar el [registro verificable de entregas](../laboratorios-descargas/references/entregas-verificadas.md): encabezado con identidad y ambas fechas, referencias por archivo/hash/página y registro mediante `register_delivery.py`. El programa genera el sustento separado y archiva el TXT en `Pacientes/Nombre/Lectura y entregas/` con [eloisa-archivo-drive](../eloisa-archivo-drive/SKILL.md). Cada paciente tiene su propio archivo. Reenvío idéntico reutiliza el registro; una revisión conserva la anterior fuera de la vista principal. No sobrescribir una edición del usuario ni cambiar `asOf` al redactar después.

Antes de cerrar: cotejar clínicamente el texto con las fuentes y comprobar estado `archived`; `pending`, `verified`, `stale` o `modified` no acreditan entrega archivada. Si las fuentes cambiaron, revisar la redacción usando el nuevo encargo. Informar sincronización remota por separado. Entregarlo **además** de los productos solicitados. El cierre numerado de fuentes sigue en respuesta y TXT de `Control y trazabilidad/`; no forma parte de este resumen. No firmar digitalmente ni publicar en la ficha.
