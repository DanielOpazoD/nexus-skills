# Adaptar HHR y MEDIF

Puntos de partida verificados en `DanielOpazoD/HHR-entornodeprueba` el 16-10-2026. Localizar el
checkout disponible; no depender de una ruta privada del equipo. Releer estos contratos si
el repositorio evolucionó. La skill no cambia por sí sola la aplicación instalada.

## Motor compartido de HHR

El [PR #863](https://github.com/DanielOpazoD/HHR-entornodeprueba/pull/863) incorpora el motor
común de formularios. Verificar primero si el checkout lo contiene; si existe, ampliarlo:

- `src/features/clinical-library/domain/forms/clinicalVariables.json`: catálogo de ejecución,
  v1.1.0 y 41 variables en esta revisión. La copia de esta skill sirve de referencia; prevalece
  el catálogo actual del programa.
- `clinicalFormPatient.ts`: proyección autorizada de PatientData, documento personal validado,
  cama/cuna separadas, procedencia de los valores y clave de episodio e identidad.
- Los nueve JSON del directorio: mapas de controles y posiciones de cada PDF.
- `clinicalFormDraft.ts`, `clinicalFormPreferences.ts` y `clinicalFormDates.ts`: aliases de
  documento personal, fechas de emisión por documento, borrador manual y preferencias sin datos.
- `clinicalFormMedif.ts`: adapta la proyección común a los IDs originales MEDIF y a sus
  excepciones expresas. MedifTool consume esa proyección; no añadir otro lector del censo.
- `src/features/clinical-library/components/tools/forms/`: editor compacto, revisión de cambios
  de origen, actualización sólo de vacíos, comparación antes de imprimir y controles por variable.
- `src/features/clinical-library/services/clinicalFormPdf.ts`: impresión sobre el original,
  comprobación de hash/dimensiones y validación de tamaño/centrado.
- `docs/formularios-clinicos.md`: uso, plantillas, alcance de borradores y pruebas verificables.

No pasar los JSON de ejecución al validador de manifiestos portátiles: revisar
[contrato-formularios.md](contrato-formularios.md#motor-de-ejecución-hhr).

## Fuentes originales y compatibilidad

- `src/types/domain/patient.ts`: `PatientData`, identidad, nombres estructurados, ingreso,
  diagnóstico, especialidad y referencia al médico tratante. Las rutas `patient.*` del catálogo
  se aplican al paciente seleccionado, no siempre al ocupante principal de la cama.
- `src/features/clinical-library/domain/medifPatientPrefill.ts`: proyección de lectura, contexto
  y procedencia; maneja cama y cuna clínica por separado, propone datos como borrador y conserva
  unidades de edad. Su `MedifPatientSnapshot` NO contiene todos los campos del catálogo (por
  ejemplo RUT y apellidos estructurados): para otro formulario proyectar los campos necesarios
  desde el `PatientData` autorizado, sin asumir que ese snapshot los incluye.
- `src/features/clinical-library/domain/medifSchema.ts` y `medifSchema.json`: IDs PDF, geometría,
  grupos, alternativas y alias. No renombrar estos IDs al añadir el catálogo común.
- `medifDraft.ts`, `medifPreferences.ts` y `medifHabitualAnswers.ts`, en el mismo directorio:
  valores compartidos, preferencias de visibilidad versionadas y atajo explícito que sólo
  completa preguntas vacías. La exportación de preferencias usa una lista permitida.
- `src/features/clinical-library/services/medifPdf.ts`: generación imprimible. Reutilizar el
  enfoque de prueba de campos, límites y páginas; no asumir que sirve otra geometría sin mapearla.

## Integrar en un checkout anterior al motor común

Resolver una vez `censo → snapshot canónico` y consumirlo con los bindings de cada formulario.
Mantener el catálogo y el adaptador de lectura en un módulo común del programa; no crear un
prefill distinto con nombres incompatibles en cada herramienta. Mantener las geometrías,
respuestas habituales, excepciones y preferencias en cada formulario. El ingreso manual usa
el mismo contrato de valores sin fabricar un episodio ni exigir una cama.

No migrar las propiedades persistidas `rut`, `patientName`, `admissionDate` o `pathology` sólo
para coincidir con el vocabulario de la skill. Mapearlas a `paciente_rut`,
`paciente_nombre_completo`, `ingreso_fecha` y `diagnostico_texto` en la proyección. Comprobar
RUT/tipo de documento antes de ese primer vínculo. Conservar el código CIE-10 por separado.
Si el programa ya incorporó un módulo común, ampliarlo en lugar de abrir otro paralelo.

## Excepciones comprobadas de MEDIF

- Nombre y edad se repiten en páginas 1 y 2; cada par usa un valor y un control.
- `p2_nombre_medico`, `p1_medico_autorizado` y `p3_medico_declaracion` comparten el nombre del
  médico por petición del usuario. No extender esa equivalencia a médico acompañante, receptor
  o firmante de otro formulario sin comprobar el rol.
- `p3_fecha_declaracion` alimenta `p1_declaracion_fecha`; es una variable local distinta de ingreso,
  vuelo y emisión. No usar una fecha global para todos los casilleros con rótulo «Fecha».
- `p1_itinerario_1_desde` y `p1_itinerario_1_hacia` son constantes de esta plantilla/servicio:
  Isla de Pascua → Santiago. No son defaults universales del paciente ni del transporte.
- El usuario pidió proponer `admissionDate` en `p2_contagiosa_fecha_tipo` («Enfermedad y fecha de
  inicio»). El adaptador lo registra como `admissionDateAsRequested`: esto no demuestra la
  fecha de inicio de la enfermedad, ni debe aplicarse a otros formularios por analogía.
- `p2_genero` usa el sexo biológico registrado por petición expresa en este MEDIF. En un nuevo
  formulario comprobar si pide sexo biológico, género o ambos antes de vincularlo.
- Los «sí/no» habituales son selecciones específicas de MEDIF aplicadas por el check verde,
  no hechos heredables de una persona ni reglas que se activan al abrir otro formulario.

`ejemplo-medif.json` muestra estos vínculos, no los 137 casilleros ni las preferencias de todos
los usuarios. Verificar su inventario contra la plantilla actual antes de convertirlo en un
adaptador completo. No contiene historias clínicas, perfiles profesionales ni valores reales.
