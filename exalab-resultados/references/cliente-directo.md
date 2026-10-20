# Cliente directo y navegación Exalab

## Programa de descarga

Para reanudar descargas, varios RUT, ambos laboratorios o un PDF por paciente/laboratorio, usa la skill `laboratorios-descargas` y su programa unificado con `--merge` si corresponde. Para descargas nuevas, prefiere también el unificado con un solo paciente: así guarda avance. Este cliente sigue disponible para consultas simples y diagnóstico.

[scripts/exalab_download.py](../scripts/exalab_download.py) es el cliente de consulta, filtrado y descarga que utiliza el unificado. Necesita Python 3.9 o posterior, sin paquetes adicionales. A diferencia de Syslab Hanga Roa, usa una sesión autenticada con ClaveÚnica, no usuario y contraseña de Syslab.

En Chrome abre el portal y verifica que la sesión muestre «Consulta Exámenes». Si venció, usa el perfil personal y su autocompletado para entrar, conforme a la autorización del usuario indicada abajo. No extraigas la contraseña guardada.

El puente [scripts/exalab_chrome_bridge.mjs](../scripts/exalab_chrome_bridge.mjs) se ejecuta desde `cua_repl` con la pestaña autenticada. Lee la documentación de la capacidad `cdp` si todavía no la has leído. Importa el módulo y llama a `runExalab(tab, options)`, con la pestaña del portal, `rut`, `period`, `output` y opcionalmente `asOf`, `listOnly` y `python`. Los períodos son `30d`, `3m`, `6m`, `1y`, `2y`, `5y`, `10y` y `latest`. Usa la carpeta de entregables de la tarea para `output`.

El puente obtiene exclusivamente `PHPSESSID` y `cf_clearance` aplicables al portal y el User-Agent. Los pasa al Python por stdin y los mantiene en memoria. No imprimas ni guardes las cookies ni el JSON de sesión. No uses archivos de cookies, variables de shell que queden en el historial, ni argumentos con secretos. No copia el perfil ni modifica ajustes de Chrome.

El programa requiere `--rut` y `--period` cuando recibe la sesión por stdin. Conserva HTTPS y la validación de certificados; en macOS utiliza también `/etc/ssl/cert.pem` para las raíces de confianza. El código 2 indica que hay que renovar la sesión en Chrome, el 1 un error o descarga parcial, y el 0 una consulta completa. Solo reintenta tras resolver la causa y comunica los folios pendientes.

Adjunta los PDF generados al chat y verifica que la salida corresponda al RUT solicitado. Cada PDF corresponde a un folio. El programa conserva versiones anteriores si el contenido cambió. La fecha de referencia usa Pacific/Easter y los intervalos de meses o años usan meses de calendario.

Si el programa rechaza la estructura del sitio, inspecciona el flujo visible antes de cambiar el código. La ruta de cada laboratorio en la lista es un parámetro que se devuelve a Exalab; el programa no conecta directamente a esos servidores internos.

Después de «Consultar», espera a que termine «Espere por favor». La tabla «Folios Asociados» muestra fecha, folio y paciente. Se abre el informe pulsando el número del examen en la fila; el PDF aparece incrustado en la misma página y tiene su propio botón «Descargar».

El portal puede redirigir a la pantalla Exalab y solicitar autenticación con ClaveÚnica. El usuario prefiere Chrome del Mac mini con el perfil personal asociado a d.opazo.damiani@gmail.com, mostrado como «daniel». Ha autorizado usar el autocompletado de ese perfil y pulsar «INGRESA» para acceder a Exalab. No reutilices credenciales de Syslab para ClaveÚnica. Si el autocompletado no permite entrar, deja la pantalla abierta y pide al usuario que inicie sesión. Esta skill no almacena RUT de pacientes ni contraseñas.

El puente no limita la duración total por defecto. `timeoutMs: 0` mantiene ese comportamiento; un valor positivo fija un plazo opcional. Los tiempos de espera de red del cliente siguen activos. Para guardado de avance y reanudación, usa el programa unificado de `laboratorios-descargas`, también con un solo RUT y `--source exalab`.
