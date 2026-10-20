# Panel de Eloísa · Nexo 3.4.0

El círculo **N** azul/violeta aparece en Eloísa Ambulatorio, dentro de `/main`. Abre el panel lateral nativo de Chrome junto a la ficha; Chrome permite ajustar su ancho y cerrarlo. El botón de Nexo en la barra de Chrome abre el mismo panel. Requiere Chrome 116 o posterior. **↗** abre el espacio actual en una pestaña completa.

Dos espacios, sin modificar la ficha:

- **Solicitar:** formulario habitual, agenda, períodos y contenidos propios por fuente, envío a Drive o copia para Codex. Seleccionar pacientes no inicia descargas.
- **Resúmenes:** buscar por nombre o RUT, elegir paciente, leer y pulsar **Copiar resumen**. Muestra fecha del archivo y referencia cuando existen. Nunca pega, firma ni guarda una evolución en Eloísa.

## Biblioteca compartida

En el Mini, el lanzador local abierto sirve la biblioteca del expediente configurado mediante `/api/library` y `/api/library/read`. En el Air —o sin lanzador— elegir una vez **Conectar carpeta de Drive → Seleccionar carpeta**, y seleccionar `Archivos Mac mini/Pacientes` en el Drive sincronizado. El permiso solicitado es de lectura. Si Chrome requiere concederlo de nuevo, reconectar la carpeta desde ese botón. Si no permite elegirla en el panel lateral, abrir **↗** y seleccionarla allí.

Solo se recuerda el identificador de acceso a la carpeta en IndexedDB. Los textos, nombres, RUT y listas no se guardan en el almacenamiento de la extensión. **Desconectar carpeta** elimina esa conexión recordada. La biblioteca no consulta portales, no descarga nuevas fuentes y no necesita Codex para leer o copiar archivos existentes.

El lector admite únicamente TXT de antecedentes conocidos en `Lectura y entregas`; excluye cierres, estados, sustento, observaciones y fuentes primarias. Las reglas están en `assets/clinical_catalog.json`, compartidas por Python y JavaScript. Límite por archivo: 256 KiB; hasta 100 documentos por paciente y 1.000 pacientes por lectura. La búsqueda muestra hasta 100 coincidencias; precisarla para ver las restantes.

## Identidad y vigencia

La identidad del expediente debe constar en `Control y trazabilidad/Identidad del paciente.txt`, o en encabezados explícitos de estados/cierres históricos coherentes. El nombre de la carpeta debe coincidir. Cada resumen debe repetir el nombre y RUT en su encabezado. Se admite el formato histórico con nombre completo en primera línea y RUT en segunda; nunca un RUT incidental en el cuerpo. Los homónimos conservan su RUT; carpetas duplicadas con el mismo RUT o identidades contradictorias quedan fuera hasta su revisión.

Si existe `Control y trazabilidad/Entregas vigentes.json`, seleccionar exclusivamente el archivo y hash de la entrega basal vigente. `freshness=stale|modified` permite leer con aviso, pero deshabilita la copia. Un archivo que no coincide con su hash no se ofrece. Sin índice, se muestran los TXT históricos identificados; si hay varias versiones, el usuario debe elegir una. Su presencia no certifica actualización clínica.

Antes de cada copia, releer índice, archivo, identidad y hash. Si cambiaron, pedir actualizar la lista; no copiar texto previo. Una respuesta tardía no debe reponer otro paciente. Cambiar de espacio, pestaña activa, paciente u ocultar la vista limpia el texto previo. El historial y los originales permanecen en Drive.

## Fronteras y permisos

El sitio recibe únicamente el botón circular, aislado con Shadow DOM; el panel pertenece a la extensión. No insertar resúmenes en el DOM de Eloísa. El trabajador acepta mensajes de biblioteca solo desde `panel/index.html` de su propia extensión. Las rutas locales son fijas; no acepta URLs ni rutas de archivo libres. No exportar textos por mensajes a la página ni habilitar `web_accessible_resources` para el panel.

`sidePanel` abre la interfaz nativa. `clipboardWrite` permite copiar tras pulsación explícita; no se solicita lectura del portapapeles. Los orígenes clínicos y permisos de sesiones existentes se mantienen. La biblioteca no añade servicios de analítica ni envío de información a terceros. Los permisos para la carpeta Drive se conceden mediante el selector del navegador.

## Actualización y comprobación

Actualizar la misma carpeta instalada, **Recargar** Nexo en Administrar extensiones y recargar la pestaña de Eloísa. No afirmar que una instalación ya está activa por haber copiado sus archivos. El ZIP se empaqueta desde HEAD con `package_extension.py`.

`./check.command` comprueba contratos compartidos, identidades, homónimos, archivos modificados, vigencia, recuperación, mensajería y cambios de contexto con datos ficticios. GitHub Actions prepara el runtime fijado y repite esas comprobaciones en cada PR. Las pruebas visuales se realizan con un expediente ficticio; no equivalen a una descarga clínica ni confirman sincronización Air → Mini.
