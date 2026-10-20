# API de epicrisis Rayen

Inspección del código cargado en Registro Hospitalario, versión 26.4.7, el 2026-10-19. No es documentación pública de estabilidad de API. Antes de usar con pacientes, verificar que el acceso y contrato siguen vigentes.

## Contratos observados

Base: `https://fichamedicoback.rayensalud.cl/api`.

- Listado: `GET /inpatientReport/getEpicrisisyReport` (conservar esa ortografía).
- Parámetros: `prefferedPeridentId=2` (RUN), `prefferedIdentifierCode`, `facilityId`, `dateFrom`, `dateTo`.
- Historial hospitalizaciones, si está solicitado: `GET /inpatientReport/getEncounterHistoryReport`, mismos parámetros. El cliente actual solo implementa epicrisis.
- PDF: `GET /report/Reporte_Epicrisis.pdf?enc_id=ID_EPISODIO`.
- Autorización: encabezado `Authorization` con el valor `session.token`, sin añadir prefijos por suposición. El `facilityId` procede de esa misma sesión.
- Sesión: `GET /api/auth/session` en el origen frontend `https://fichamedico.rayensalud.cl`. Respuesta observada `ok`, `session.token`, `session.facilityId`. La comprobación real devolvió HTTP 200 y sesión vigente; no se imprimió el token.

El código del listado exige episodios con `encounterId`, `patientId`, `facilityId`, `patientIdentifier`, `patientIdentifierTypeId`, `patientName`, `startPeriod`, `endPeriod`, `generatedReport`, `deleted`, entre otros campos. El identificador RUN admite validación de dígito. En la UI, fechas del formulario solo se envían para N.N.; para RUN el cliente replica búsqueda del paciente y **filtra localmente por fecha de egreso** antes de descargar. Informar este criterio; si la solicitud exige fecha de ingreso o emisión, adaptar explícitamente el criterio antes de ejecutar. Fechas no verificables quedan pendientes.

## Cliente de consola y puente

[rayen_epicrisis.py](../scripts/rayen_epicrisis.py): Python 3.9+ y `pypdf`; localizar el runtime con `load_workspace_dependencies`. Recibe JSON de sesión por stdin, nunca contraseña ni token como argumento. Sintaxis: `python3 rayen_epicrisis.py --rut RUN --from AAAA-MM-DD --to AAAA-MM-DD --output RUTA_ABSOLUTA [--download]`. Sin `--download`, solo lista y guarda estado.

Preferir [rayen_bridge.mjs](../scripts/rayen_bridge.mjs) desde `cua_repl`: leer documentación CDP, importar el módulo y llamar `runRayenEpicrisis(tab, {rut, from, to, output, python, download})` con la pestaña autenticada del portal. El puente obtiene únicamente token/establecimiento por la ruta observada y los pasa al proceso por stdin; no mostrar el objeto de sesión. Reautenticar en Chrome si falta o vence, respetando la cuenta autorizada en la skill.

Salidas locales de trabajo: `OUTPUT/RUN/estado-rayen-FECHA.json` y PDF por episodio; posteriormente copiar al expediente por nombre con la skill de Drive. El estado contiene información clínica, no credenciales: mantenerlo fuera del repositorio. Los documentos idénticos se reutilizan; los cambios reciben versión nueva. En el cliente directo cada ejecución vuelve a consultar la lista. En el unificado, `rayen` comparte `avance.json`, archivos independientes y consolidación; los PDF previos se revalidan con el servidor mediante ETag/Last-Modified cuando existen. Sin validadores, se descarga y verifica nuevamente. La caché técnica `.cache-http` no se copia al expediente.

Validación conservadora: establecimiento/RUN en listado; firma, páginas, RUN y fecha de egreso en PDF. Un formato que no permita verificarlos queda pendiente de revisión visible, no se publica como validado. El piloto mostró que `generatedReport=false` permite obtener PDF: consultar el endpoint del episodio; HTTP 204 queda no disponible. No usar ese indicador como filtro de ausencia. Un fallo no elimina los anteriores. Sesión vencida detiene esa fuente sin nuevos intentos; código 2 requiere autenticación, 1 indica error/parcial, 0 ejecución completa dentro del alcance.

## Evidencia y límite

Rutas y parámetros confirmados en los módulos públicos cargados `4571-e58c087c31bd58b5.js` y `8732-e31722ec637278fa.js`; sesión comprobada sin consultar pacientes. Pruebas locales con datos ficticios: filtrado, identidad, PDF, resultados parciales, sesión vencida, versiones, errores y transporte privado de sesión.

**Piloto real 19/10/2026:** dos episodios listados para seis meses; una epicrisis descargada/verificada (4 páginas); otra pendiente por fecha de egreso discrepante entre listado y documento. Se cotejó el buscador visible. No registrar datos identificatorios de pacientes en esta skill. `--source rayen` y `--source all` ya están integrados; comprobar los resultados por fuente aunque el proceso termine parcial.

Pruebas offline: `python3 -m unittest discover -s scripts/tests -v` y `node --test scripts/tests/bridge.test.mjs`, desde la carpeta de la skill. Las pruebas Python requieren `reportlab` además de `pypdf` para producir PDF ficticios; no acceden a portales.

## Identidad y regresiones

`validate_pdf` exige RUN dentro de «Datos/Identificación del paciente» o un rótulo explícito de paciente; nunca una coincidencia libre. Admite valores antes de rótulos dentro del bloque, rechaza encabezados contradictorios entre páginas y compara el episodio si está identificado. Egreso discrepante queda pendiente. Probar con `python3 -m unittest discover -s scripts/tests -v`, incluidos paciente distinto con RUT solicitado bajo médico, texto sin encabezado y episodio erróneo. Las pruebas son ficticias.
