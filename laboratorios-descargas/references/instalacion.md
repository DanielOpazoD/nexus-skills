# Instalación y verificación del paquete clínico

Requiere las carpetas clínicas hermanas del repositorio, CPython 3.12 y Node.js 22 para las pruebas. `requirements.lock` fija siete dependencias y hashes oficiales de sus wheels para macOS Apple Silicon/Intel. Python 3.12.14, Node 22.22.0 y Apple Silicon se verificaron localmente el 19-10-2026; no se verificó instalación física en el MacBook Air ni en Intel. No copiar un entorno virtual de un Mac a otro. Los decodificadores DICOM adicionales no incluidos quedan fuera de esta instalación; un formato no soportado mantiene el original y declara la conversión pendiente.

Desde `~/.codex/skills/laboratorios-descargas`, instalar con un Python 3.12 existente:

```sh
python3.12 scripts/setup_runtime.py
```

Si se usa el runtime de Codex, el ejecutable es `~/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`; comprobar su versión. El instalador crea un entorno privado en `~/Library/Application Support/HHR Clinical/runtime/<huella-del-lock>/`, instala únicamente wheels con hashes y ejecuta toda la verificación. Habilita `runtime.ok` sólo al terminar correctamente. No toca credenciales, portales, colas ni expedientes. Un fallo conserva el diagnóstico y no habilita ese entorno. Para instalar sin red, añadir `--wheelhouse RUTA_A_WHEELS`; pip exige los mismos hashes. No desactivar TLS ni omitir la comprobación de hashes.

Para abrir el panel: doble clic en `open-local.command`. Para comprobar todo, un único comando desde esa misma carpeta:

```sh
./check.command
```

Comprueba versiones, compatibilidad de dependencias, sintaxis, frontmatter y enlaces de las skills clínicas, coherencia de los formularios generados, pruebas Python y Node. Usa casos ficticios, incluida conversión DICOM/PDF; no consulta fuentes clínicas ni demuestra autenticación, sincronización real o cobertura de cada formato DICOM. Los registros quedan en una carpeta temporal con fecha DD-MM-AAAA. Cualquier fallo devuelve código distinto de cero y la ruta del registro. `LABS_PYTHON` permite elegir un intérprete de diagnóstico explícitamente; la verificación exige las versiones fijadas.

## Actualizar y volver atrás

1. Conservar un commit limpio y revisar cambios; no añadir documentos, colas, sesiones ni entornos al repositorio. Mantener el límite de archivos permitido por `.gitignore`.
2. Si cambian dependencias, renovar versiones **y hashes** desde distribuciones oficiales, instalar un entorno nuevo y ejecutar `check.command`. No actualizar paquetes a mano dentro del entorno usado por el lanzador.
3. Si cambia la interfaz, regenerar con `scripts/build_portable_form.py`, verificar y distribuir sólo el HTML vacío. No basta con cambiar controles del formulario sin actualizar contratos/puente.
4. Para sustituir código o intérprete del servicio, comprobar primero que no haya trabajo activo; cerrar el lanzador y abrirlo nuevamente. La cola migra con respaldo y los cancelados no se reactivan.
5. Para volver a un commit, usar el entorno de su propio lock; conservar los anteriores. Una versión de cola futura se rechaza sin sobrescribirla. Restaurar un respaldo de cola sólo con el lanzador cerrado y revisando los trabajos posteriores para no duplicar búsquedas. Git no guarda expedientes ni sustituye su respaldo.

Al abrir el lanzador en el Mini, el receptor observa `_Solicitudes Nexo` si Drive está montado. No instala un servicio permanente; con el lanzador cerrado no recibe trabajos. El HTML/extensión actualizados en el Air escriben JSON+marcador en esa carpeta; `submit_request.py` sigue siendo el respaldo manual. Biopsias y plantillas institucionales permanecen pendientes.
