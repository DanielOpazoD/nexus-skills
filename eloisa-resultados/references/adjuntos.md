# Adjuntos ambulatorios — 19-10-2026

Flujo comprobado con un ecocardiograma PDF real autorizado de dos páginas, más pruebas ficticias. No acredita todos los formatos del portal.

1. API autenticada `Inscripcion/UsuarioApsRut/{rut}/{nodo}` → `FichaClinica/HistorialAtencion`. Validar RUT del maestro y cada atención; usar `FechaCita`/`Fecha` dentro del período. `ArchivosAdjunto` entrega `NombreArchivo` y `PathAzure`; puede no incluir ID propio. Si incluye `IdUsuario`, `IdNodo` o `IdAtencion`, deben coincidir.
2. Obtener acceso temporal por GET `Autentificacion/TokenGestorDocumento/{IdUsuario}/{IdNodo}`. Ruta observada en el cliente público de Eloísa: `https://clinicohangaroa.eloisa.cl/static/js/main.0afb86a1.chunk.js`. La UI usa el permiso `VerDocumentosClinicos`; respetar negativas del servidor. Sesión vencida: recuperación única de la skill.
3. `connection` y `sas` permiten el GET del objeto de Azure. Aceptar sólo HTTPS, el host Azure de esa conexión y el contenedor del paciente; rechazar otros orígenes/contenedores, rutas ambiguas y redirecciones. Nunca enviar el Bearer de Eloísa a Azure ni guardar SAS/URL firmadas en logs, avance o Drive. El puente transmite sesión por stdin/FIFO privada, nunca por argumentos.
4. Máximo 32 MiB por PDF; comprobar estructura, cierre y páginas. Verificar nombre/RUT en bloque rotulado del paciente; un RUT de profesional/familiar no acredita identidad. Comparar ID de atención cuando esté impreso. Un formato no reconocido o escaneado requiere revisión manual; no publicarlo como verificado. Formatos distintos de PDF quedan explícitamente pendientes por ahora.
5. Conservar bytes originales, SHA-256, nombre de archivo, atención, fecha de atención y huella de la ruta sin guardarla. La identidad de caché incluye atención + huella de ruta: dos adjuntos de la misma atención no colisionan. Reanudar sólo bytes íntegros y contexto compatible; conservar versiones y entregas previas ante fallos.

Al seleccionar `latest`, se mantiene la semántica existente: la atención elegible más reciente de Eloísa, con todos sus productos seleccionados, incluidos varios adjuntos de esa misma atención. Para buscar un adjunto anterior junto con evoluciones recientes, elegir un período. Los adjuntos no amplían el intervalo ni habilitan otra fuente automáticamente.

Los nombres/fechas añadidos usan DD-MM-AAAA. La fecha impresa y el contenido del original se conservan literalmente. No copiar documentos reales ni identificadores de pacientes a pruebas/Git.
