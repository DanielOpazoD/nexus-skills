---
name: telereumatologia
description: Redactar resúmenes para telereumatología de pacientes nuevos o en seguimiento, con síntesis clínica compacta y observaciones documentales en TXT separado. Usar al pedir telereumato, telemedicina reumatológica o este formato de entrega.
---

# Resumen para telereumatología

Invocación: `$telereumatologia`. Aplicar el formato editado por el usuario el 20-10-2026 y la [estructura vacía](references/estructura.md). Esta skill redacta un documento para presentar a telereumatología; no inicia búsquedas ni envía interconsultas. Usar sólo pacientes y documentos de la solicitud vigente. Añadir el [TXT basal de antecedentes](../resumen-antecedentes/SKILL.md) de cada corrida, independiente del DOCX solicitado. Leer [reporte-clinico](../reporte-clinico/SKILL.md) para evidencia, archivo y cierre, con la **excepción de citas visuales** de abajo.

## Documento clínico

Identificación verificada: nombre, RUT, edad/sexo, nacimiento, previsión, ocupación, centro derivador y fecha del documento, solo si constan. Calcular edad con la fecha de referencia; anotar discrepancias en el TXT de observaciones. No copiar valores del ejemplo.

Orden de lectura:
1. **Motivo de derivación:** diagnóstico o problema documentado en una frase breve; agregar objetivo solo si consta. Para paciente nuevo, priorizar motivo y trayectoria; en seguimiento, cambios desde el último control. No inventar la pregunta al especialista.
2. **Antecedentes y evolución:** diagnóstico, inicio, órganos afectados, biopsias disponibles, brotes, hospitalizaciones, tratamiento previo y último esquema consignado, en 1–3 párrafos cronológicos fluidos, sin repetir el motivo ni fragmentar la historia en viñetas. Distinguir tratamiento **vigente confirmado** de última prescripción o nota. Dosis, vía y frecuencia solo cuando consten.
3. **Enfermedad actual y examen físico:** pueden compartir un bloque compacto, pero distinguir síntomas de hallazgos; fechar cada uno por separado. No atribuir un examen sin fecha al control más reciente; si la versión del autor omite una fecha conocida, dejar la precisión en el TXT de observaciones. Evitar «asintomático» repetido.
4. **Laboratorio reumatológico:** tabla de evolución por fecha cuando hay series comparables. Conservar método, unidades y cualitativos necesarios; no equiparar métodos o escalas distintos. «—» significa dato no disponible. Paneles aislados en una línea breve.
5. **Exámenes generales:** redactar en **párrafos continuos breves por fecha**, sin tabla de paneles. Selección habitual: Hb, VCM, glóbulos blancos (GB, con linfocitos absolutos cuando consten) y plaquetas; creatinina/BUN; PCR/VHS; Na/K; colesterol total, LDL, HDL y TG; CK total. Añadir glicemia, AST/ALT, TSH/T4 libre u otros resultados habituales cuando aporten información al caso. En orina, priorizar proteínas, leucocitos y glóbulos rojos; RAC/RPC solo si están informados, indicando unidades cuando importen. No transcribir la fórmula completa del hemograma, CHCM/RDW/MPV ni cada subfracción de perfiles si no son decisivos; los PDF originales conservan el panel completo. Distinguir tira urinaria de sedimento y no fusionar exámenes de orina de fechas distintas. Expresar GB y linfocitos en una escala consistente (p. ej., /µL con miles separados por punto); no alternar 3,8 y 3.800 sin unidad. No inventar ausencias. Si falta fecha, unidad o cifra, conservar esa precisión. Aplicar [unidades selectivas](../reporte-clinico/references/examenes-breves.md): omitir unidades habituales inequívocas; mantener PCR, troponina, dímero D, proteinuria/RAC o las que eviten ambigüedad.

6. **Plan:** reproducir solo el plan de la fuente o aportado por el médico autor, con atribución/fecha si corresponde. No añadir tratamientos ni recomendaciones. La revisión del autor es una fuente distinta del registro previo; si modifica el plan, conservarlo y señalar en el TXT qué requiere confirmación.

Omitir secciones opcionales sin contenido en vez de llenar la página de «No consignado»; si una ausencia afecta la decisión clínica, corregir el cuerpo o anotarla en el TXT según su importancia. Terminar **siempre** el DOCX con la línea exacta «Dr Daniel Opazo, Medicina Interna». Es identificación profesional, no firma digital; no validar ni publicar.

## Estilo y evidencia

Español clínico notificativo, breve y factual. Frases cortas; pocas conjunciones; evitar conectores de relleno, repeticiones, juicios de normalidad y explicaciones causales no documentadas. «No consta» no equivale a «niega». Diagnóstico, sospecha, relato y conclusión de otra fuente conservan su atribución. Fechas **DD-MM-AAAA**; respetar precisión parcial. Exámenes: fecha, prueba y resultado, sin interpretación añadida.

**No insertar `[S1]`, notas al pie ni referencias junto a cada frase** del resumen presentado. Mantener en la preparación un mapa de afirmaciones a archivo/página/fecha; verificar identidad y cifras antes de redactar. La versión editada por el autor puede aportar hechos o plan nuevos, pero no se debe atribuirlos retrospectivamente a fuentes primarias. Evitar que la ausencia de citas visuales se convierta en ausencia de trazabilidad.

## Observaciones documentales fuera del resumen

El DOCX **no lleva anexo, advertencias editoriales ni índice de fuentes**. Guardar un TXT aparte, `Observaciones documentales - Nombre del paciente - DD-MM-AAAA.txt`, con discrepancias, datos añadidos por el autor sin fecha en los registros revisados, unidades o fechas no visibles, pendientes y fuentes efectivamente usadas. Ser concreto: qué dato difiere, en qué fuente y fecha, qué queda por verificar. No presentar la ausencia de observaciones dentro del resumen clínico. Si una omisión cambiara materialmente el sentido clínico, corregir el resumen antes de entregarlo; el TXT no sustituye esa corrección. Mantener aparte el cierre operativo de siete fuentes requerido por el flujo clínico.

## Diseño y entrega

Priorizar una página clínica cuando la evidencia lo permita, sin reducir letra hasta dificultar la lectura. Mantener el aspecto azul sobrio del ejemplo editado: título claro, identificación en tabla, barras de sección delgadas, tablas solo para datos comparables, sin párrafos vacíos entre bloques. No añadir una página de revisión al DOCX. No duplicar fechas o valores de tablas en prosa. Adaptar filas a la evidencia: el ejemplo no es un panel obligatorio.

Si se pide DOCX, usar la skill de documentos, renderizar y revisar **todas** las páginas. Nombre: `Resumen telereumatología - Nombre del paciente - DD-MM-AAAA.docx`; conservar versiones, no sobrescribir la edición del usuario. Archivar el informe clínico en `Pacientes/Nombre/Lectura y entregas/`; TXT de observaciones y cierre de fuentes en `Control y trazabilidad/`, con [eloisa-archivo-drive](../eloisa-archivo-drive/SKILL.md). Para una orden clínica, mostrar además el [cierre de fuentes](../laboratorios-descargas/references/cierre-fuentes.md) en la respuesta, separado del informe. Si se pide solo chat, entregar el resumen en chat. No publicar en fichas ni enviar a terceros.
