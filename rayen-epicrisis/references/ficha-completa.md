# Ficha clínica completa · Eloísa Hospitalizados

Implementación de referencia revisada el 19-10-2026: [HHR-entornodeprueba, hospitalization-reports-runtime.js](https://github.com/DanielOpazoD/HHR-entornodeprueba/blob/7ca9f7d381b1a1c5b67db9ba199b33298869fe4b/extension/hospitalization-reports-runtime.js) y [búsqueda](https://github.com/DanielOpazoD/HHR-entornodeprueba/blob/7ca9f7d381b1a1c5b67db9ba199b33298869fe4b/extension/hospitalization-report-search-runtime.js). Este flujo **abre el visor oficial**; no contiene una descarga directa del PDF de ficha completa. No confundirlo con la API PDF de epicrisis.

## Selección y búsqueda

- Fuente estable `rayen`; nombre visible **Eloísa Hospitalizados**. `sourceContent.rayen`: `epicrisis` (predeterminado), `record` (ficha completa) o ambos. El CLI recibe `--source-content` con ese mapa. Omitir el campo conserva la descarga histórica de epicrisis.
- Ficha completa: GET `/api/inpatientReport/getEncounterHistoryReport`, `prefferedPeridentId=2`, `prefferedIdentifierCode=RUN`, `facilityId` autenticado y fechas vacías, como en el flujo observado. Verificar RUN propio, tipo 2, nombre, paciente, establecimiento e ID de episodio antes de construir enlaces. **No usar el fallback de RUN materno/tipo 4 del repositorio**: no identifica necesariamente al paciente solicitado.
- Epicrisis: selección por egreso. Ficha completa: hospitalizaciones que coinciden con el período (ingreso ≤ término solicitado y egreso ≥ inicio, o episodio aún activo). Se solicita el episodio completo hasta la fecha de referencia; declarar si su ingreso antecede a la ventana. «Último» elige un episodio por cada producto. Fechas ausentes/incoherentes quedan pendientes, nunca como ausencia de antecedentes.
- Un fallo de búsqueda/descarga de un producto conserva el otro y las demás fuentes. Los enlaces pendientes se guardan en `unavailable_records`; no son documentos ni suman páginas.

## Completar con Codex y el navegador

1. Leer el resultado del trabajo y abrir únicamente `viewer_url` del paciente autorizado en el perfil habitual de Chrome, renovando una vez la sesión si corresponde. Origen `https://fichamedico.rayensalud.cl`, ruta `/dashboard/reports`, `isReportServer=true`, `report=GetHospitalizedEncounterHistory`, `params={enc_id,start_date,end_date}`. Son parámetros del episodio, nunca tokens. Las fechas ISO son internas del portal; presentación y archivos en **DD-MM-AAAA**.
2. Comprobar nombre/RUN en el bloque del paciente y episodio/fechas frente al listado. Usar el control visible de descarga del visor. Si sólo ofrece imprimir, exportar copia de trabajo PDF e identificarla como tal. No inventar una ruta PDF ni sustituir la ficha completa por un resumen diario o una proyección JSON parcial.
3. Validar PDF íntegro, páginas legibles, identidad del paciente vinculada al encabezado y episodio/fechas cuando figuren. No aplicar sin adaptación el validador de epicrisis, que exige egreso. Ante ambigüedad, dejar pendiente; no inferir identidad de un RUN de profesional/familiar. Conservar hash SHA-256 y referencia del episodio.
4. Guardar y archivar lo verificado por nombre de paciente con `eloisa-archivo-drive`, en `Fuentes primarias/Ficha clínica hospitalaria/`; conservar originales/versiones. Entregar la ficha con su cobertura y estado de las otras fuentes.

## Límite actual

La cola local lista episodios y ofrece «Abrir ficha completa», pero **no automatiza el guardado del visor ni importa su PDF al estado de la cola**. Codex puede completar el paso visible y archivar el documento; informar por separado ese resultado y el estado aún pendiente del lanzador. Abrir el informe, obtener su URL o copiar una solicitud nunca acredita descarga. La nueva integración se probó con datos ficticios y contratos del repositorio; falta comprobar el recorrido del visor con un paciente expresamente autorizado para una prueba actual.
