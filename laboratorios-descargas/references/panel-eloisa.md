# Panel de Eloísa · Nexo 3.6.0

El círculo **N** azul/violeta aparece en Eloísa Ambulatorio, dentro de `/main`. Abre el panel lateral nativo de Chrome junto a la ficha; Chrome permite ajustar su ancho y cerrarlo. El botón de Nexo en la barra de Chrome abre el mismo panel. Requiere Chrome 116 o posterior. **↗** abre el espacio actual en una pestaña completa.

La cabecera comprueba el ejecutor local o la señal de la bandeja Drive recordada al enviar una orden. «Mini disponible» acredita señal reciente del proceso; no sesiones válidas ni acceso actual a cada portal. «Sin comprobar» significa que no hay conexión autorizada para leer esa señal; «sin señal reciente» no demuestra que el Mini esté apagado. Ver [servicio y protocolo](servicio-mini.md).

Dos espacios, sin modificar la ficha:

- **Solicitar:** formulario habitual, agenda, períodos y contenidos propios por fuente, envío a Drive o copia para Codex. Seleccionar pacientes no inicia descargas.
- **Resúmenes:** buscar por nombre o RUT, elegir paciente, leer y pulsar **Copiar resumen**. Muestra fecha del archivo y referencia cuando existen. Nunca pega, firma ni guarda una evolución en Eloísa.

**Usar ficha abierta** aparece solo cuando la pestaña activa de Chrome es Eloísa y su componente de datos de paciente permite comprobar nombre/RUT contra un expediente de la biblioteca. Lee exclusivamente `.patient-name-div` y las filas RUT/RUN de `.info-titles-paciente-by-rut` / `.info-pacient-by-rut`, revisadas en el paquete público `main.0afb86a1.chunk.js` el 20-10-2026. No busca RUT en toda la página, no toma la identidad de `userSession` y no consulta otra pestaña. Ambigüedad, encabezado oculto o cambio del componente mantienen la búsqueda manual. Al copiar una selección procedente de la ficha se vuelve a comprobar esa identidad; un cambio bloquea la copia. Función probada con datos ficticios; falta contraste en una ficha real autorizada.

**Abrir expediente** abre `Lectura y entregas` localmente cuando el lanzador ofrece esa capacidad. Revalida la carpeta y exige un permiso efímero del proceso; nunca recibe una ruta libre del navegador. En el Air se ofrece el enlace web cuando `Control y trazabilidad/Carpeta Drive.json` contiene un ID de carpeta obtenido al confirmar sus ancestros y un archivo remoto, con nombre/RUT coincidentes. Sin enlace confirmado, el acceso web permanece oculto. No abre enlaces arbitrarios ni modifica archivos.

## Biblioteca compartida

En el Mini, el lanzador local abierto sirve la biblioteca del expediente configurado mediante `/api/library` y `/api/library/read`. En el Air —o sin lanzador— elegir una vez **Conectar carpeta de Drive → Seleccionar carpeta**, y seleccionar `Archivos Mac mini/Pacientes` en el Drive sincronizado. El permiso solicitado es de lectura. La procedencia indica «Drive · carpeta sincronizada» o «Mini · archivo local». En **Cambiar conexión de Drive**, **Reconectar carpeta** vuelve a solicitar lectura del acceso recordado, sin repetir el selector. Si el permiso se rechaza o la carpeta cambió, **Seleccionar carpeta** permite elegirla de nuevo. Si no permite elegirla en el panel lateral, abrir **↗** y seleccionarla allí.

Solo se recuerda el identificador de acceso a la carpeta en IndexedDB. Los textos, nombres, RUT y listas no se guardan en el almacenamiento de la extensión. **Desconectar carpeta** elimina esa conexión recordada. La biblioteca no consulta portales, no descarga nuevas fuentes y no necesita Codex para leer o copiar archivos existentes. Esta conexión usa **Google Drive para escritorio**, no la API web de Drive: requiere la carpeta montada y los archivos disponibles; una copia local legible no confirma sincronización remota. No amplía permisos de la cuenta de Google.

Al enviar una orden se recuerda también el acceso a `_Solicitudes Nexo`, sin guardar pacientes. El seguimiento verifica ID/hash del acuse y progreso; puede continuar hasta diez minutos mientras permanezca abierto el formulario. Cambiar la selección o cerrar la vista cancela el seguimiento anterior. Reenviar el mismo pedido recupera el mismo trabajo. Una fuente completa, una entrega preparada y la sincronización confirmada se muestran por separado. Las lecturas de estado y biblioteca tienen espera acotada; el fallo no borra archivos.

El lector admite únicamente TXT de antecedentes conocidos en `Lectura y entregas`; excluye cierres, estados, sustento, observaciones y fuentes primarias. Las reglas están en `assets/clinical_catalog.json`, compartidas por Python y JavaScript. Límite por archivo: 256 KiB; hasta 100 documentos por paciente y 1.000 pacientes por lectura. La búsqueda muestra hasta 100 coincidencias; precisarla para ver las restantes.

## Identidad y vigencia

La identidad del expediente debe constar en `Control y trazabilidad/Identidad del paciente.txt`, o en encabezados explícitos de estados/cierres históricos coherentes. El nombre de la carpeta debe coincidir. Cada resumen debe repetir el nombre y RUT en su encabezado. Se admite el formato histórico con nombre completo en primera línea y RUT en segunda; nunca un RUT incidental en el cuerpo. Los homónimos conservan su RUT; carpetas duplicadas con el mismo RUT o identidades contradictorias quedan fuera hasta su revisión.

Si existe `Control y trazabilidad/Entregas vigentes.json`, abrir directamente el archivo de la entrega basal vigente; no recorrer ni leer los TXT históricos. Validar ruta, identidad y hash antes de ofrecerlo. `freshness=stale|modified` permite leer con aviso, pero deshabilita la copia. Un archivo que no coincide con su hash no se ofrece. Sin índice, se muestran los TXT históricos identificados; si hay varias versiones, el usuario debe elegir una. Su presencia no certifica actualización clínica.

Las entregas nuevas conservan las versiones de fuentes y huellas de originales conocidos al registrarse. Un pedido posterior con documentos distintos —también adjuntos— deja el resumen previo pendiente de revisión; copiar de nuevo bytes idénticos no lo invalida. Rearchivar una entrega antigua conserva su vínculo y vigencia anteriores: no la actualiza por sí solo. La detección se aplica a documentación verificada por Nexo, no a cualquier archivo añadido manualmente a Drive.

Abrir o copiar relee únicamente el expediente elegido, resolviendo su ruta desde la carpeta autorizada; no vuelve a recorrer todos los pacientes. Antes de cada copia, comprobar permiso, identidad y hash; releer el índice antes y después del archivo para detectar reemplazos durante la lectura. Una entrega anteriormente indexada no puede pasar a histórica porque desapareció su índice. Si cambiaron, pedir actualizar la lista; no copiar texto previo. Una respuesta tardía no debe reponer otro paciente. Cambiar de espacio, pestaña activa, paciente u ocultar la vista limpia el texto previo. Al volver a una vista visible de Resúmenes se actualiza la biblioteca; ↻ permite actualizarla manualmente. La lista muestra la fecha disponible más reciente, sin elegir automáticamente entre versiones históricas. El historial y los originales permanecen en Drive.

## Fronteras y permisos

El sitio recibe únicamente el botón circular, aislado con Shadow DOM; el panel pertenece a la extensión. No insertar resúmenes en el DOM de Eloísa. El trabajador acepta mensajes de biblioteca solo desde `panel/index.html` de su propia extensión. Las rutas locales son fijas; no acepta URLs ni rutas de archivo libres. No exportar textos por mensajes a la página ni habilitar `web_accessible_resources` para el panel.

`sidePanel` abre la interfaz nativa. `clipboardWrite` permite copiar tras pulsación explícita; no se solicita lectura del portapapeles. Los orígenes clínicos y permisos de sesiones existentes se mantienen. La biblioteca no añade servicios de analítica ni envío de información a terceros. Los permisos para la carpeta Drive se conceden mediante el selector del navegador.

## Actualización y comprobación

Actualizar la misma carpeta instalada, **Recargar** Nexo en Administrar extensiones y recargar la pestaña de Eloísa. No afirmar que una instalación ya está activa por haber copiado sus archivos. El ZIP se empaqueta desde HEAD con `package_extension.py`.

`./check.command` comprueba contratos compartidos, identidades, homónimos, archivos modificados, vigencia, lectura acotada al expediente, reemplazo de índice durante la lectura, reconexión de permiso, recuperación, mensajería y cambios de contexto con datos ficticios. GitHub Actions prepara el runtime fijado y repite esas comprobaciones en cada PR. Las pruebas visuales se realizan con un expediente ficticio; no equivalen a una descarga clínica ni confirman sincronización Air → Mini.

Referencia de plataforma: [File System Access, permisos y handles recordados](https://developer.chrome.com/docs/capabilities/web-apis/file-system-access). La autorización se solicita por pulsación; no desde una actualización automática.
