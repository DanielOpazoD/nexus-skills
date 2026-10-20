# Mini disponible · servicio de usuario

`scripts/service_manager.py install` instala `cl.hhr.nexo.worker` en LaunchAgents del usuario, con el Python del runtime verificado, argumentos absolutos y sin shell ni sudo. El servicio arranca al iniciar sesión y se reinicia si termina; espera 15 s entre arranques. No mantiene el Mac despierto ni evita cierres de sesión de los portales. El llavero y Chrome pueden seguir requiriendo intervención.

Antes de instalar o sustituir código, comprobar que no haya descargas activas y cerrar el lanzador manual. `service_manager.py status` distingue configuración instalada, servicio cargado y salud del proceso. `service_manager.py stop` descarga únicamente ese servicio; no borra la cola ni expedientes. Para volver a activarlo, ejecutar `install`. El doble clic en `open-local.command` reutiliza el lanzador que ya ocupa su puerto.

El servicio conserva `~/Documents/Descargas clínicas` y el archivo Drive configurado. Sus registros locales están en `~/Library/Logs/Nexo`; no se publican. `/api/health` devuelve solo salud de cola/receptor y modo de ejecución, sin pacientes ni sesiones.

El receptor espera y vuelve a intentar si Drive falta al arrancar. Cada 15 s escribe `_Solicitudes Nexo/worker.json`, con vencimiento a los 90 s. Es una señal de vida del proceso, no una prueba de autenticación de los portales ni de sincronización actual entre equipos. Una señal vencida se presenta como «Sin señal reciente».

`acuses/acuse-ID.json` acredita importación o rechazo. `acuses/progreso-ID.json` comunica avance, ligado al mismo ID y SHA-256 del pedido: recibido, descargando, documentos parciales/disponibles, resumen preparado o cancelado. Incluye solo conteos y estados de copia/sincronización. No contiene nombres, RUT, textos, rutas, nonce ni credenciales. Fuentes listas, redacción archivada y sincronización confirmada son resultados distintos. El lector debe comprobar versión, ID, hash y fecha antes de presentar el estado.

El estado de un resumen corresponde a la evidencia comprobada por el programa; no certifica actualización clínica posterior. Leer/copiar desde la biblioteca vuelve a comprobar el archivo. El traslado entre dos Macs debe verificarse en ambos equipos; las pruebas locales ficticias no lo acreditan.

Referencia de implementación: [LaunchAgents de Apple](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).
