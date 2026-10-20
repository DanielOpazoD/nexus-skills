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

Para resúmenes de telereumatología, aplicar [telereumatologia](../telereumatologia/SKILL.md): estructura del usuario recibida el 19-10-2026, disponible para redacción en Codex. Esta excepción sustituye la espera genérica de plantilla indicada abajo para ese resumen; la automatización del modelo en el programa sigue pendiente.

Toda corrida añade [resumen-antecedentes](../resumen-antecedentes/SKILL.md): TXT basal clínico, breve y sustentado, por paciente. `deliveryModel=documents` no añade un modelo institucional, pero sí este resumen predeterminado. `custom` usa `deliveryInstructions` como encargo adicional libre. Los otros modelos se suman al TXT; no lo sustituyen. Conservar el [catálogo](references/modelos-entrega.json) y la selección, sin ampliar fuentes ni períodos. Las plantillas institucionales pendientes siguen en [plantillas](../plantillas/README.md); no inventarlas ni bloquear el TXT basal por su ausencia. Cada paciente y episodio tienen identidad propia. Una epicrisis redactada es un borrador separado de Rayen; no firmar ni publicar en la ficha.

## Salida

Citas compactas junto a los datos: `[S1, p. 2]`; índice final con archivo, fuente, fecha y folio/ID disponibles. **Excepción:** telereumatología omite citas visibles y lleva observaciones/evidencia en TXT aparte, según su skill; la trazabilidad por afirmación se conserva en la preparación. Preferir rutas relativas al expediente; no usar enlaces de sesión. Citar solo lo inspeccionado.

Salida basal: `DD-MM-AAAA Resumen antecedentes.txt` conforme a [su skill](../resumen-antecedentes/SKILL.md); DOCX sólo si se solicita otro formato que lo requiera. Revisar el renderizado de los documentos de formato. En órdenes de la cola, aplicar el [registro de entregas y evidencia](../laboratorios-descargas/references/entregas-verificadas.md) para el TXT y los modelos adicionales: cotejo clínico por Codex, validación mecánica y copia archivada por el programa. Archivar material clínico en `Pacientes/Nombre/Lectura y entregas/` con [eloisa-archivo-drive](../eloisa-archivo-drive/SKILL.md), conservando versiones fuera de esa vista. Una instrucción explícita de sólo chat/no guardar prevalece. En agendas, el TXT basal sigue siendo individual; guardar los documentos colectivos en Documentos generales.

Verificar antes de entregar: identidad, citas, fechas, unidades, vigencia de medicación, discrepancias y cobertura.

Toda orden clínica termina con el [cierre de fuentes en respuesta y TXT](../laboratorios-descargas/references/cierre-fuentes.md), separado del reporte solicitado. Guardar cierre, estado, observaciones y mapa de evidencia en `Control y trazabilidad/`, fuera de `Lectura y entregas/`. Para correo, citar cuenta/ID y fecha del mensaje, atribuir información al remitente y distinguir fecha clínica; no transformar correspondencia en diagnóstico confirmado.
