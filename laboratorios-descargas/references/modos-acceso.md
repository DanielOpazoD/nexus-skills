# Acceso programático por fuente

Auditoría local del 19/10/2026. Preferir los clientes instalados; “modo API” expresa acceso programático, pero distinguir API JSON de HTTP que procesa HTML. No crear rutas supuestas ni presentar contratos internos como API pública estable.

| Fuente | Transporte implementado | Autenticación / navegador | Documento |
|---|---|---|---|
| Eloísa ambulatorio | API JSON: `UsuarioApsRut` → `HistorialAtencion` | Chrome personal obtiene/renueva sesión; token por stdin al cliente | PDF de trabajo generado |
| Epicrisis Rayen | API JSON de listado y endpoint de PDF | Chrome Registro Hospitalario; token/establecimiento por stdin | PDF original de alta médica |
| Syslab HHR | HTTP: formularios PHP → listado HTML → PDF | Credenciales propias y cookies del cliente; sin Chrome normalmente; red hospitalaria | PDF original por folio |
| Exalab SSMO | HTTP: `controlador/consulta.php` → `controlador/ventana.php` → PDF | ClaveÚnica en Chrome; cookies aplicables por stdin | PDF original por folio |
| MMRAD RIS | HTTP/formularios Liferay e informes; SockJS/DDP `GetStudyMetadata` y proxy WADO para imágenes | Credenciales propias y cookies del cliente; sin Chrome normalmente | PDF original del informe; DICOM y PDF generado por estudio |
| Correo institucional | Conector Gmail: búsqueda paginada, lectura de mensaje y adjuntos | Cuenta daniel.opazo@hospitalhangaroa.cl conectada a Codex; no usa sesión del puente Chrome | TXT de trabajo y adjuntos verificados; [operación](../../correo-clinico/references/operacion.md) |
| HIS HHR | HTTP/formularios, `consficha` y fichas HTML por ID/tipo | Credenciales propias y cookie del cliente; sin Chrome normalmente | PDF de trabajo generado |

## Operación

1. Usar el descargador unificado para Syslab, Exalab, Eloísa, MMRAD e HIS, manteniendo el avance. Epicrisis Rayen está integrada con `--source rayen` y en `--source all`. El formulario incluye siete fuentes; correo usa conector Gmail en Codex y posterior importación de evidencia.
2. Obtener la sesión por el mecanismo de cada skill. No guardar tokens/cookies en archivos, logs ni argumentos. Chrome conserva su función de inicio/renovación para Eloísa, Exalab y Rayen; no confundir automatización de descargas con eliminación del login.
3. Ante sesión vencida, aplicar recuperación de la fuente. En Eloísa, “actividad anormal/inusual” exige intentar el inicio autorizado una vez, obtener sesión nueva y reanudar; no mantener el token inválido. Bloqueos o desafíos persistentes requieren intervención. No repetir consultas mientras se sabe inválida la sesión.
4. Si cambian formato/rutas, inspeccionar el flujo autenticado visible y solicitudes observadas antes de ajustar el cliente. Usar la interfaz como alternativa si el servicio funciona; una caída del servidor no se resuelve cambiando de HTTP a API.
5. Conservar y entregar todo documento completo verificado aunque falle otra fuente o parte de la misma. Error/timeout/login no equivale a listado vacío. Archivar por paciente con la skill de Drive y declarar pendientes.

## Evidencia y límites

La auditoría de código se amplió con un piloto real de Eloísa y Rayen el 19/10/2026; ver [continuidad](continuidad.md). No acredita disponibilidad actual de las demás fuentes. Las pruebas offline no sustituyen una consulta autenticada real. En cada ejecución registrar resultado por fuente: consulta correcta con/sin registros, parcial, sesión requerida o no disponible; reservar “funciona de extremo a extremo” para listado y documento verificados en esa ejecución.

- [Eloísa](../../eloisa-resultados/scripts/eloisa_download.py): `Eloisa.request/search/download`; JSON autenticado y renderizado local.
- [Rayen](../../rayen-epicrisis/references/api.md): listado y una epicrisis real comprobados; otra quedó pendiente por fecha discrepante. Reintentos, integración y caché tienen pruebas ficticias.
- [Syslab](../../syslab-resultados/scripts/syslab_download.py): `Syslab.login/search/request` y parser de exámenes.
- [Exalab](../../exalab-resultados/scripts/exalab_download.py): `Exalab.search/download`, cookies y parser de listado/enlace PDF.
- [MMRAD](../../mmrad-resultados/scripts/mmrad_download.py): `MMRAD.login/search/download`, `viewer_metadata/download_dicom`; detalles en [DICOM](../../mmrad-resultados/references/dicom.md).
- [HIS](../../his-resultados/scripts/his_download.py) y [scrape.py](../../his-resultados/scripts/his_reports/scrape.py): HTTP y parsers. Consultar el [estado fechado](../../his-resultados/references/estado-servicio.md) antes de intentar acceso; no asumir que la incidencia sigue vigente sin comprobarlo.

No hace falta reescribir los seis clientes para consultar desde consola. Una migración adicional a API JSON de Syslab, Exalab o HIS requiere observar primero un endpoint real autorizado que aporte una mejora; la auditoría actual no confirmó tales endpoints.

Adjuntos Eloísa: mismo historial autenticado → token temporal del gestor documental → PDF original en Azure, sin trasladar Bearer. Identidad por encabezado y vínculo de atención; límites en [adjuntos](../../eloisa-resultados/references/adjuntos.md).
