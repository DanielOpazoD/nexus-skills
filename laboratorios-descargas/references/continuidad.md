# Acceso y continuidad

## Sesiones y fuentes independientes

- Exalab comprueba el buscador autenticado antes del lote. Rayen consulta su sesión del frontend; Eloísa comprueba presencia/caducidad declarada del token y la primera lectura confirma el acceso. La forma de un token no demuestra autorización.
- `runLabs(..., {reauthenticate: async (source, tab) => nuevaPestana, ...})` admite un callback construido con la UI observada y cuenta autorizada. Máximo una renovación por fuente/ejecución. El callback resuelve login/autocompletado según la skill, devuelve pestaña autenticada o null si hay desafío persistente; no extrae contraseñas. Sin callback, informa la sesión pendiente. La renovación no ocurre por sí sola en el CLI.
- El puente retoma con el mismo `--resume` y `--retry-sources eloisa|exalab|rayen|lista`. Reconsulta solo las fuentes recuperadas y mantiene resultados de las demás. Mantener iguales alcance, pacientes y opciones. Hacer `await runLabs(...)`: no dejar llamadas de navegador en una promesa sin esperar al cerrar `cua_repl`.
- Se prueban credenciales existentes; no reintentar un login rechazado repetidamente. Lecturas transitorias GET y POST de consulta explícitos admiten un reintento; 401/403 requieren sesión/permisos, no más intentos de lectura. Respetar Retry-After: si exige más de 5 segundos, dejar pendiente. Fallo persistente pausa esa fuente en el lote. HIS mantiene su circuito propio con presupuesto reducido, sin apilar otro.

## Rendimiento y frescura

- Eloísa usa inicio/fin del período en `HistorialAtencion` y filtra también localmente. `--eloisa-full-history` es respaldo de diagnóstico; `latest` conserva búsqueda amplia. Piloto de seis meses del 19/10/2026: mismos 5 registros y huellas; consulta amplia 1,326 s, acotada 1,141 s. Medición única, no garantía de aceleración.
- El avance reutiliza originales íntegros, conserva versiones si cambia contenido y registra duración por fuente. Reanudación conserva fecha de referencia; una consulta de novedades debe usar la fecha actual. No confundir copia previa con actualización confirmada.
- Rayen usa consulta condicional del PDF si el servidor entrega ETag/Last-Modified. Solo acepta 304 con copia íntegra y verificada, tras una solicitud autenticada. Sin validador, descarga de nuevo. Caché `.cache-http` privada: documentos verificados y validadores, sin tokens ni URLs; no copiarla al expediente.
- MMRAD procesa imágenes después de los documentos de todos los pacientes. Guarda cada instancia con SHA-256/UID para retomar estudios interrumpidos. `--image-workers 1|2` (por defecto 1); 2 usa sesiones aisladas y ventanas pequeñas, mantiene orden y no publica PDF incompleto. Concurrencia validada con datos ficticios, rendimiento real pendiente.
- La caída de una fuente o de la unión PDF mantiene archivos independientes. El formulario local y CLI/puente admiten seis fuentes. Una pestaña antigua que envíe `all` conserva sus cinco fuentes históricas; Rayen requiere selección nueva explícita.

## TLS y red del ejecutor

El transporte usa verificación TLS y las CA ya instaladas (`/opt/homebrew/etc/openssl@3/cert.pem`, alternativas del sistema). El piloto resolvió un fallo de cadena usando ese almacén existente; nunca usar `verify=False` ni desactivar controles del navegador.

Si un subprocess de `cua_repl` carece de red, distinguir esa restricción de una caída del portal. Usar el mecanismo de aprobación de ejecución disponible. Para ese proceso, transportar sesión por una **FIFO privada**, sin archivo regular de secretos:

1. Crear un directorio temporal modo 0700 y dentro `os.mkfifo(ruta, 0o600)`; no reutilizar rutas de otras tareas.
2. Lanzar el CLI autorizado con `--session-stdin ... < RUTA_FIFO`; la shell queda esperando lectura. Conservar su identificador de ejecución.
3. En `cua_repl`, leer documentación CDP e importar el puente; llamar `await writeLabsSession(pestanas, {source: fuentes}, rutaFIFO, secretosAutorizados)`. Comprueba propietario/permisos/tipo FIFO y solo escribe a un lector activo; no devuelve secretos.
4. Recoger resultado y eliminar únicamente la FIFO/directorio temporales creados por esta ejecución cuando ya no haya lector. No persistir ni imprimir el payload. Esta vía no sustituye la aprobación de acceso de red.

## Comprobaciones

Desde `laboratorios-descargas`: `python3 -m unittest discover -s scripts/tests -v` y `node --test scripts/tests/bridge.test.mjs`; desde `rayen-epicrisis`, sus pruebas Python/Node. Todas esas pruebas usan datos ficticios. El piloto real confirmó reautenticación Eloísa, 5 atenciones y una epicrisis de 4 páginas. Un segundo PDF quedó pendiente porque su egreso difiere del listado; conservar esa discrepancia y no relajar validación. No guardar identificadores clínicos del piloto en skills o tests.
