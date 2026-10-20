---
name: reporte-clinico
description: Redactar resúmenes de antecedentes y reportes clínicos HHR trazables a documentos verificados, con cronología, datos de laboratorio, imágenes, discrepancias y pendientes. Usar al sintetizar o comparar documentación de uno o varios pacientes.
---

# Reporte clínico

Español clínico breve y factual; ajustar detalle al pedido. Leer el [contrato común](../laboratorios-descargas/references/verificacion.md) y la [estructura adaptable](references/estructura.md). No iniciar consultas para completar un resumen de archivos aportados.

## Evidencia

Leer los documentos, no inferir hechos por su nombre. Distinguir fuente primaria, copia de trabajo, consolidado, resumen previo y relato del usuario. Cada dato relevante conserva fecha clínica y referencia a archivo/página/sección. Un resumen previo orienta, pero no reemplaza las fuentes disponibles. Verificar OCR dudoso contra la página.

Una fuente parcial no bloquea el reporte: incluir los documentos verificados disponibles y señalar los faltantes. Limitar la cobertura declarada a lo realmente revisado.

## Redacción

Fechas en nombres, encabezados, cronología y citas: **DD-MM-AAAA**, por ejemplo `19-10-2026`; conservar precisión parcial sin inventar componentes.

- Distinguir diagnóstico consignado, sospecha y relato. No deducir diagnósticos de síntomas, códigos o medicamentos; separar antecedentes personales y familiares.
- “No consta” no significa “niega”. Conservar contradicciones con sus fuentes; la nota más reciente no las resuelve automáticamente.
- Medicación: nombre, dosis, unidad, vía, frecuencia y fecha cuando consten. Diferenciar prescripción histórica de tratamiento vigente; no inferir suspensión por omisión posterior.
- **Exámenes breves, notificativos y sin interpretación añadida.** Fecha, prueba y resultado; sin juicios de normalidad, flechas, diagnósticos ni recomendaciones. Transcribir los cualitativos originales. Aplicar [unidades selectivas y ejemplos](references/examenes-breves.md): omitir unidades habituales inequívocas; conservarlas en PCR, troponinas, dímero D o valores ambiguos. Mantener cifras, signos y escala originales; respaldo con unidades/rangos íntegros.
- Imagenología: fecha, modalidad, región y conclusión atribuida al informe. Imágenes sin informe no acreditan una conclusión radiológica documentada.
- Interpretar, recomendar o calcular solo si se pide. Separar esos resultados de los hechos; verificar fuentes médicas externas actuales sin datos identificatorios. Para cálculos: fórmula, entradas fechadas/unidades y supuestos; entradas faltantes quedan pendientes.

## Modelo solicitado

Respetar el [catálogo de entrega](references/modelos-entrega.json) y el modelo guardado en la solicitud: epicrisis, telemedicina (reumatología o gastroenterología), evolución Eloísa ambulatoria o de hospitalizados. `deliveryModel=custom` usa el encargo `deliveryInstructions` (obligatorio) como formato libre y no requiere plantilla institucional. `documents` no pide redacción. Para los cinco modelos institucionales, el usuario entregará sus plantillas, con espacio reservado en [plantillas de entrega](../plantillas/README.md) y su catálogo de recepción; hasta entonces conservar la selección y declarar pendiente la redacción con ese modelo. No inventar formatos institucionales. Al recibirlas, aplicar [formularios-clinicos](../formularios-clinicos/SKILL.md). La selección no amplía fuentes ni períodos; si son distintos por fuente, declarar esa cobertura. Cada paciente y episodio tienen identidad propia. Una epicrisis generada es un borrador, separado del informe original Rayen; no firmar ni publicar en la ficha.

## Salida

Citas compactas junto a los datos: `[S1, p. 2]`; índice final con archivo, fuente, fecha y folio/ID disponibles. Preferir rutas relativas al expediente; no usar enlaces de sesión. Citar solo lo inspeccionado.

Resumen individual guardado: DOCX y TXT equivalentes por defecto (`Resumen de antecedentes`), salvo otro formato solicitado. Usar la skill del formato y revisar su renderizado cuando corresponda. Archivar con [eloisa-archivo-drive](../eloisa-archivo-drive/SKILL.md), conservando versiones; una respuesta solo en chat no exige DOCX; el cierre operativo TXT sigue siendo obligatorio salvo instrucción explícita de no guardar. En agendas, separar identidades y guardar el conjunto en Documentos generales; generar individuales si se pidieron.

Verificar antes de entregar: identidad, citas, fechas, unidades, vigencia de medicación, discrepancias y cobertura.

Toda orden clínica termina con el [cierre de fuentes en respuesta y TXT](../laboratorios-descargas/references/cierre-fuentes.md), separado del reporte solicitado. Para correo, citar cuenta/ID y fecha del mensaje, atribuir información al remitente y distinguir fecha clínica; no transformar correspondencia en diagnóstico confirmado.
