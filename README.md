# Nexo · Consulta clínica

<img src="laboratorios-descargas/assets/brand/nexo-128.png" width="80" height="80" alt="Icono de Nexo">

Aplicación local, extensión de Chrome y skills de Codex para preparar solicitudes clínicas, consultar fuentes autorizadas y organizar documentación por paciente. Desarrollada para el flujo del Hospital Hanga Roa.

## Qué incluye

| Componente | Ubicación |
|---|---|
| Aplicación local, cola persistente y clientes | [laboratorios-descargas](laboratorios-descargas/) |
| Extensión Nexo (Manifest V3) | [chrome-bridge](laboratorios-descargas/chrome-bridge/) |
| Formulario HTML portátil | [solicitud-portatil.html](laboratorios-descargas/assets/solicitud-portatil.html) |
| Coordinación principal de Codex | [flujo-clinico](flujo-clinico/SKILL.md) |
| Fuentes | Syslab, Exalab, Eloísa Ambulatorio, HIS, MMRAD, Eloísa Hospitalizados y correo institucional |
| Reportes, formularios y archivo en Drive | [reporte-clinico](reporte-clinico/), [formularios-clinicos](formularios-clinicos/), [eloisa-archivo-drive](eloisa-archivo-drive/) |
| Plantillas institucionales pendientes | [plantillas](plantillas/) |
| Alcance y funciones pendientes | [Estado de capacidades](flujo-clinico/references/estado-capacidades.md) |

## Empezar

```sh
git clone https://github.com/DanielOpazoD/nexus-skills.git
cd nexus-skills/laboratorios-descargas
python3.12 scripts/setup_runtime.py
./open-local.command
```

Requiere macOS, Python 3.12 y Node.js 22. El instalador prepara dependencias fijadas con hashes y verifica el conjunto. El panel se abre en `http://127.0.0.1:8765/`. Consultar [instalación](laboratorios-descargas/references/instalacion.md) para entornos, actualización y recuperación. Las credenciales/sesiones y el acceso a cada portal se configuran en cada equipo; clonar el repositorio no concede acceso. Revisar las rutas y cuentas documentadas antes de usarlo fuera del entorno original.

### Extensión para Chrome

Descargar el ZIP de [Releases](https://github.com/DanielOpazoD/nexus-skills/releases), descomprimirlo y cargar esa carpeta mediante «Cargar descomprimida» en Administrar extensiones de Chrome, con modo desarrollador. También se puede cargar directamente `laboratorios-descargas/chrome-bridge`. Al actualizar una instalación existente, conservar su carpeta y recargar la extensión.

El círculo **N** dentro de Eloísa Ambulatorio y el botón **Nexo** de Chrome abren el panel lateral: **Solicitar** y **Resúmenes**. La biblioteca busca por nombre/RUT y permite copiar antecedentes después de verificar identidad y archivo. Usa el lanzador del Mini o una carpeta `Pacientes` de Drive seleccionada una vez en el Air; no necesita Codex para leer textos existentes. Consultar [panel y biblioteca](laboratorios-descargas/references/panel-eloisa.md).

«Desde agenda» usa la sesión de Eloísa de ese Mac y permite seleccionar pacientes de la agenda propia por fecha; el Air y el Mini tienen el mismo acceso a esa selección. «Enviar a Drive» deja la orden en una bandeja privada; el lanzador abierto del Mini la valida, importa y acusa. Copiar/guardar para Codex queda como respaldo. El HTML abierto como archivo permite introducir RUT manualmente; para consultar agenda usar la extensión. Seleccionar pacientes no inicia descargas.

Cada paciente tiene `Lectura y entregas` para PDF integrados e informes/resúmenes preparados, `Control y trazabilidad` para cierres de fuentes, estados, observaciones e identidad, y `Fuentes primarias` para originales y adjuntos. Los PDF integrados van de la fecha clínica más reciente a la más antigua; su nombre indica el rango real incluido y `PARCIAL` si faltan documentos. `python3 laboratorios-descargas/scripts/clinical_archive.py --apply` corrige títulos conocidos de expedientes previos, verificando cada reubicación dentro del mismo paciente.

### Skills de Codex

Las carpetas clínicas con `SKILL.md` forman el paquete. Instalarlas juntas como carpetas hermanas en el directorio de skills de Codex, respaldando cualquier versión anterior; no reemplazar otras skills. La entrada principal es `$flujo-clinico`. Leer [su guía](flujo-clinico/SKILL.md) y las skills necesarias. Instalar la extensión no instala las skills.

Toda corrida clínica incorpora [Resumen de antecedentes](resumen-antecedentes/SKILL.md): `DD-MM-AAAA Resumen antecedentes.txt` por paciente, en Lectura y entregas, además de cualquier otro formato. La síntesis se redacta en Codex leyendo documentos verificados; el descargador independiente no la redacta automáticamente. El panel permite copiar ese encargo incluso con «Sin formato adicional».

## Plantillas pendientes

[plantillas/](plantillas/) reserva cinco formatos: epicrisis, telemedicina reumatológica, telemedicina gastroenterológica, evolución ambulatoria y evolución de hospitalizados. Se reciben vacíos, se versionan y se integran después de validarlos. Hasta entonces los modelos institucionales permanecen pendientes; la descarga de documentos es independiente.

## Verificación y empaquetado

Desde `laboratorios-descargas`:

```sh
./check.command
python3 scripts/package_extension.py --output /tmp/Nexo-extension.zip
```

Las pruebas usan datos ficticios y se repiten en GitHub Actions en cada PR. No prueban disponibilidad permanente de portales ni sincronización de cada equipo. Los activos del formulario se regeneran con `python3 scripts/build_portable_form.py`. El empaquetador toma los archivos de la extensión del commit HEAD y produce un ZIP reproducible.

## Estado de esta publicación

Versión de extensión 3.4.0 en el paquete fuente; requiere Chrome 116 o posterior. Recargar la extensión y la pestaña de Eloísa para activar el círculo. El [registro de entregas](laboratorios-descargas/references/entregas-verificadas.md) separa fuentes, redacción, archivo y sincronización, liga cada informe a su evidencia y conserva versiones fuera de la lectura principal. Codex sigue redactando y cotejando la prosa clínica; el motor verifica y archiva. Agenda: consulta real autorizada comprobada; el recorrido completo desde la extensión recargada y el traslado Air → Mini siguen pendientes de verificación. También están pendientes biopsias, las otras plantillas institucionales y los límites detallados en [capacidades](flujo-clinico/references/estado-capacidades.md).

El repositorio contiene el programa, las skills clínicas, pruebas, documentación y activos. El historial anterior de trabajo permanece local; la publicación inicial omitió el identificador personal de acceso que figuraba en instrucciones antiguas. No se incluyen expedientes, descargas clínicas, sesiones, contraseñas, entornos virtuales ni colas de trabajos.

Un fallo de una fuente conserva la documentación verificada de las demás. Copia local y sincronización remota se informan por separado. El programa no firma ni publica automáticamente documentos en las fichas clínicas.
