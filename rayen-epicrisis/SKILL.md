---
name: rayen-epicrisis
description: Buscar hospitalizaciones e informes de alta médica (epicrisis) en Eloísa Registro Hospitalario de Rayen mediante cliente API con sesión de Chrome y archivar los documentos verificados por paciente. Usar en revisiones integrales, epicrisis hospitalarias o ficha completa (visor oficial).
---

# Eloísa Hospitalizados

Portal: `https://fichamedico.rayensalud.cl/`, **Eloísa – Registro Hospitalario**. Es una fuente distinta de Eloísa Ambulatorio y del HIS Hanga Roa. Aplicar el [contrato común](../laboratorios-descargas/references/verificacion.md); usar solo pacientes/período autorizados.

## Acceso

Chrome personal `d.opazo.damiani@gmail.com` (“daniel”); la cuenta profesional autorizada por el usuario. Su identificador de acceso nunca se reutiliza como paciente. Seleccionar su credencial guardada, autocompletar y pulsar **Ingresar**, sin extraer ni guardar la contraseña. No seleccionar otras cuentas guardadas.

Si vence la sesión, conservar archivos/estado, volver al login, iniciar con la misma cuenta y comprobar acceso antes de retomar. Ante “actividad anormal/inusual”, intentar una reautenticación; si persiste o exige CAPTCHA/segundo factor, detener reintentos y solicitar la intervención concreta. Un fallo de sesión no significa ausencia de hospitalizaciones.

## Vía preferida: cliente API

Leer [API y consola](references/api.md). Preferir [laboratorios-descargas](../laboratorios-descargas/SKILL.md) con `--source rayen` y pestaña `rayen` en el puente común: integra avance, reanudación y PDF por paciente. El [cliente directo](scripts/rayen_epicrisis.py) y su [puente](scripts/rayen_bridge.mjs) siguen disponibles para diagnóstico. Chrome mantiene inicio/renovación; consultas y PDF usan API.

## Contenido seleccionable

Epicrisis médica por defecto. Si `sourceContent.rayen` incluye `record`, leer [ficha clínica completa](references/ficha-completa.md): búsqueda de episodios por API y descarga desde el visor oficial de HHR-entornodeprueba. Seleccionar ambos conserva cada producto independientemente. El lanzador deja la ficha completa pendiente hasta descargar/verificar con el visor; no anunciarla como PDF automático.

## Respaldo por navegador

Ruta comprobada el 2026-10-19: menú **Informes** → **Informe Alta Médica** → **Tipo de documento: RUN** → **Identificador** → **Buscar**. Existe también **Historial hospitalizaciones paciente**. La URL observada es `/dashboard/reports`; las pestañas comparten esa ruta, así que verificar la pestaña seleccionada.

Introducir el RUN del paciente autorizado conforme a la validación visible; no suponer que el formato del buscador de la lista de trabajo es idéntico. En esta revisión no había máscara ni ejemplo en el campo Identificador. Comprobar nombre/RUN de los resultados antes de abrir documentos. No usar pacientes de la lista inicial de trabajo para probar el flujo.

Revisar hospitalizaciones y altas del período pedido, incluidas páginas adicionales. Distinguir fechas de ingreso, egreso y emisión; registrar cuál se utilizó para filtrar. Si el buscador no filtra fechas, aplicar el período sobre los resultados verificables del paciente. “Último” se determina por fecha clínica, no por orden de filas. Una hospitalización encontrada no garantiza que su epicrisis esté disponible o finalizada.

## Documento y entrega

Abrir el informe existente. Vincular el RUN al bloque rotulado del paciente; una mención en texto libre, firma, profesional o familiar no acredita identidad. Comprobar además ID de episodio cuando esté rotulado y fecha de egreso frente al listado. Encabezado ambiguo o discrepancia impiden publicar/unir el PDF; dejarlo pendiente de revisión visible. Descargar mediante el control visible del portal si está disponible. Si solo permite impresión, exportar una copia de trabajo PDF identificada como tal, sin modificar ni firmar la ficha. No crear una epicrisis clínica nueva para sustituir una ausente; no confundir alta de enfermería con alta médica.

Validar páginas, integridad y correspondencia con el episodio. Archivar en `Pacientes/Nombre completo/Fuentes primarias/Epicrisis Rayen/`, con fecha e ID de episodio cuando estén disponibles, según [eloisa-archivo-drive](../eloisa-archivo-drive/SKILL.md). Reportar con [reporte-clinico](../reporte-clinico/SKILL.md). Conservar versiones y entregar lo verificado aunque falten otros documentos/fuentes.

## Límite verificado

El 19-10-2026 se comprobó búsqueda real por RUN y descarga de una epicrisis de cuatro páginas con la validación disponible entonces. La corrección del 19-10-2026 añade validación del encabezado y episodio, probada con documentos ficticios; no implica una nueva descarga real. Otro episodio quedó pendiente por discrepancia entre egreso del listado y PDF; no relajar la validación para aceptarlo. `generatedReport=false` no demuestra ausencia: el portal ofrece lectura del PDF y este puede existir. HTTP 204 sin documento queda no disponible; no reintentar automáticamente. CLI/puente unificados incluyen `rayen` y `all`; el formulario local incluye las seis fuentes.

Al cerrar la orden, incluir el [resumen numerado de fuentes](../laboratorios-descargas/references/cierre-fuentes.md) en respuesta y TXT, también si esta es la única fuente o queda parcial. No consultar fuentes adicionales para completar ese bloque.
