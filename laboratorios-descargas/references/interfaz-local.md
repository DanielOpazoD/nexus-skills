# Lanzador y formulario

## Uso independiente en este Mac

Instalar una vez con el [entorno reproducible](instalacion.md). `open-local.command` selecciona la versión verificada correspondiente al lock; `check.command` comprueba el paquete sin iniciar descargas.

[open-local.command](../open-local.command) abre `http://127.0.0.1:8765/` en Chrome personal. La interfaz agrupa las siete fuentes en laboratorio, atenciones/hospitalizaciones e imagenología. Permite marcar o desmarcar una fuente o su grupo; valida los RUT y muestra un resumen antes de iniciar. La barra horizontal ofrece 30 días, 3 y 6 meses, 1, 2, 5 y 10 años, con mouse/teclado y fechas `DD-MM-AAAA`; «último registro» es una opción separada. MMRAD tiene dos casillas: Informes TAC y Radiografías. Eloísa mantiene Documentos adjuntos seleccionado dentro de Contenido; allí se obtienen los informes de ecocardiograma. Sus imágenes MMRAD se excluyen. No se permiten solicitudes MMRAD sin seleccionar ningún producto. Incluye siete fuentes; los portales comienzan al disponer de credenciales o sesión y correo se resuelve en Codex. Las ausentes quedan pendientes. Se pueden añadir solicitudes durante una descarga y elegir trabajos anteriores, reanudar pendientes o cancelar una ejecución conservando lo verificado.

Syslab/MMRAD/HIS usan credenciales propias, opcionalmente guardadas en el llavero. Exalab/Eloísa/Epicrisis Rayen reciben sesiones mediante [chrome-bridge](../chrome-bridge), versión 3. La extensión envía cada sesión directamente al servicio local; una pestaña vencida no descarta las otras. Nunca transporta secretos mediante el DOM. Tras actualizar sus archivos hay que recargar la extensión y la página; comprobar versión visible. Si Chrome solicita nuevos permisos para Registro Hospitalario, completar su autorización antes de usar Rayen. No afirmar instalación/activación sin observarla.

En el lanzador independiente, una sesión vencida requiere iniciar sesión en la pestaña y pulsar **Reintentar sesiones**; el programa no resuelve CAPTCHA ni realiza automáticamente el login. Con Codex, seguir la reautenticación única autorizada de [continuidad](continuidad.md).

## Cola y recuperación

[clinical_jobs.py](../scripts/clinical_jobs.py) guarda `.trabajos/cola.json` atómicamente dentro de `~/Documents/Descargas clínicas/`, con permisos locales restringidos. Un único ejecutor consume los trabajos que tengan fuentes disponibles; una solicitud esperando acceso no impide comenzar otra. El avance de cada trabajo está en `.trabajos/ID/datos/`. La cola versión 2 valida cada trabajo por separado: uno dañado queda apartado y los válidos siguen disponibles. La migración desde versión 1 y el aislamiento guardan los bytes originales en `.trabajos/recuperacion/`, con permisos restringidos y fecha DD-MM-AAAA. Una versión futura o un JSON global ilegible no se sobrescribe. El historial conserva archivos, solicitud y estados; las sesiones, cookies, contraseñas y nonces no se serializan.

Al volver a abrir, reconstruir documentos desde resumen/checkpoint y hashes, rotar el nonce y continuar únicamente las fuentes pendientes con acceso disponible. Los trabajos cancelados permanecen cancelados hasta reanudación explícita. `clinical_worker.py` interrumpe el cliente si desaparece el lanzador, evitando procesos huérfanos. Cancelación: SIGINT, espera acotada y terminación forzada si no responde; los documentos íntegros sobreviven. Un avance incompatible, ilegible o ambiguo queda en atención: no se sobrescribe ni se reanuda automáticamente; conservar esa carpeta y crear otra solicitud. Un registro dañado deja pendiente su paciente/fuente, sin ocultar documentos verificados de las demás. La cola no es un servicio permanente de macOS: si el lanzador está cerrado, no inicia trabajos.

## Expediente y sincronización

[clinical_archive.py](../scripts/clinical_archive.py) copia automáticamente PDF completos, originales de `.avance`, DICOM y estado al expediente definido en [eloisa-archivo-drive](../../eloisa-archivo-drive/SKILL.md). Usa nombre para navegación y RUT para identidad; una carpeta homónima sin identidad comprobable queda pendiente, sin mezclar. Comprueba SHA-256 de origen/destino, conserva versiones y no fabrica una carpeta alternativa si Drive no está disponible.

**Copia verificada** y **sincronización confirmada** son estados separados. El verificador remoto usa Google Drive API de solo lectura para comprobar ancestros desde el ID configurado, nombre, tamaño y checksum; la presencia local no basta. La instalación requiere una conexión OAuth autorizada para esta comprobación. [drive_oauth.py](../scripts/drive_oauth.py) permite vincular una aplicación de escritorio de Google mediante consentimiento, PKCE y acceso `drive.metadata.readonly`; guarda el refresh token en el llavero y renueva automáticamente el acceso. Requiere un cliente OAuth de escritorio propio con Drive API habilitada: `python3 scripts/drive_oauth.py --client-json RUTA_AL_JSON_DEL_CLIENTE`. Ese archivo de configuración se elige localmente; no copiarlo a prompts. La cuenta del llavero es `local-launcher`, servicio `CLINICAL_DRIVE_OAUTH`; se admite un access token temporal existente en `CLINICAL_DRIVE_ACCESS_TOKEN`. No se configuró ni autorizó una conexión nueva como parte de las pruebas ficticias. Sin configuración/consentimiento o si se revoca el acceso, la copia sigue y la nube queda pendiente. **Comprobar archivo en Drive** vuelve a evaluar. No presentar las pruebas de nube ficticia como sincronización real.

Referencias: [OAuth de escritorio](https://developers.google.com/identity/protocols/oauth2/native-app) y campos remotos: [Google Drive Files](https://developers.google.com/workspace/drive/api/reference/rest/v3/files).

## Formulario dentro de Codex

[assets/solicitud-examenes.html](../assets/solicitud-examenes.html) ofrece las siete fuentes y envía una selección explícita al chat. Para mostrarlo, leer `visualize`, copiar a la carpeta de visualizaciones de la tarea y emitir según su contrato. No incorporar RUT previos. El estado conserva opciones, nunca RUT ni credenciales. Si el envío no está disponible, mostrar texto para pegar. Cambiar opciones no descarga nada.

Otra tarea del Mac puede invocar `$laboratorios-descargas`; otro equipo requiere el paquete, acceso a los portales, perfil y configuración de destino propios.

Las opciones `mmradMode` y `mmradImageTypes` viajan del formulario a la cola persistente y al CLI; no dependen sólo de la vista. El formulario de chat transmite los mismos filtros. Esta mejora de interfaz mantiene ejecución local: el envío Air → Drive → mini sigue siendo una integración pendiente y no debe presentarse como activada.

## Períodos propios y documento de entrega

Interfaz compacta: paciente, período común, modelo de entrega y panel lateral de fuentes. Todas las fuentes heredan el período general automáticamente. Pulsar el período junto a una fuente despliega su barra; moverla crea un período propio. «Restablecer» devuelve esa fuente al general y «Aplicar a todas» elimina las excepciones. No hay casilleros de período común por fuente. Fuentes desmarcadas no envían períodos ni se consultan. La solicitud guarda `sourcePeriods`; el CLI recibe `--source-periods` como JSON. Un cambio de período requiere una solicitud nueva y no reutiliza un avance incompatible.

«Formato de entrega» es una sección plegada y opcional; por defecto sólo se descargan archivos. `deliveryModel` selecciona originales, epicrisis, telemedicina reumatológica/gastroenterológica, evolución ambulatoria/hospitalaria o libre. «Libre» abre un campo obligatorio de hasta 2000 caracteres (`deliveryInstructions`) y queda pendiente de redacción en Codex, sin exigir plantilla institucional. El catálogo está en [reporte-clinico](../../reporte-clinico/references/modelos-entrega.json); la cola conserva una copia versionada del modelo. Por indicación del usuario se esperan sus plantillas. El formulario distingue **Fuentes completadas** de **Plantilla pendiente**. Seleccionar un modelo no añade fuentes ni redacta automáticamente, no firma ni escribe en una ficha. «Copiar solicitud para Codex» conserva el modelo, cobertura, períodos y referencias de archivos con identidad del trabajo y hash vigente; no incluye secretos. Permite continuar con documentos parciales; no requiere que las otras fuentes terminen. No confundir una epicrisis generada con el original Rayen.

Al recibir las plantillas, inspeccionarlas con `formularios-clinicos`, mapear variables y validar una salida ficticia antes de habilitar su generación; no cambiar sólo el estado del catálogo. El programa todavía no tiene un motor de redacción autónoma ni una bandeja entre Macs.

## Solicitud desde el Air

El [formulario portátil](../assets/solicitud-portatil.html) abre con doble clic, comparte controles con el lanzador y copia/exporta una solicitud para Codex del Mini. Leer el [contrato y traslado manual](solicitud-portatil.md) al recibirla o distribuirla. No necesita las skills en el Air. El Mini sigue ejecutando y archivando; la bandeja automática de Drive todavía está pendiente. Configuración e historial del lanzador permanecen plegados; el campo RUT crece al añadir pacientes.

## Contenidos por fuente

Eloísa Ambulatorio y Eloísa Hospitalizados muestran «Contenido» colapsado al iniciar. Ambulatorio preselecciona evoluciones médicas, recetas e interconsultas; otros profesionales es opcional. Hospitalizados preselecciona epicrisis médica; ficha completa es adicional y requiere el [visor oficial](../../rayen-epicrisis/references/ficha-completa.md). Una fuente activa debe tener al menos un contenido. Desmarcarla excluye sus opciones del encargo. `sourceContent` se conserva en texto portátil, cola, puente, CLI y checkpoint. El formato libre no amplía esa selección ni ejecuta acciones fuera del encargo clínico.

## Correo y cierre

Séptima fuente `Correo`, cuenta institucional fija en la interfaz y período propio. `Consultar correo en Codex` copia un encargo con contexto/carpeta; Gmail se consulta en Codex y `Reanudar pendientes` importa el resultado revisado. Las otras fuentes continúan sin esperar correo. Al terminar o cancelar, `Resumen de fuentes` muestra el bloque numerado y permite copiar el texto y guardar el TXT; también se conserva/copia cuando no hubo documentos. Las solicitudes históricas conservan sus fuentes originales. Véase [correo](../../correo-clinico/SKILL.md) y [cierre](cierre-fuentes.md).

El resultado muestra fuentes completadas/seleccionadas y archivos con integridad vigente. El resumen conserva su selección de texto entre sondeos. Un archivo perdido o cambiado vuelve a dejar pendiente solo su fuente, incluso después de reiniciar; conserva los originales recuperables y el resto del trabajo. «Biopsias · Pendiente» es un recordatorio sin casillero y no altera «Todas», el contador ni las solicitudes.

## Elegir pacientes desde la agenda

«Desde agenda» consulta un día de la agenda del prestador autenticado de Eloísa en este equipo. Funciona también desde el formulario propio de la extensión en el Air, sin servidor Python. Seleccionar y agregar pacientes sólo llena los RUT; las fuentes, períodos y entrega se mantienen. Ver [contrato de agenda](../../eloisa-resultados/references/agenda.md).
