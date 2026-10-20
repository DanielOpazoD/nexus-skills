---
name: syslab-resultados
description: Consultar y descargar PDF de exámenes de Syslab del Hospital de Hanga Roa en 10.4.69.90, por RUT y período, mediante el programa Python local.
---

# Laboratorio Syslab HHR

Aplicar el [contrato común](../laboratorios-descargas/references/verificacion.md) y ejecutar con [laboratorios-descargas](../laboratorios-descargas/SKILL.md), también para un paciente. El contrato define identidad, entrega parcial, reporte y archivo.

Portal: `http://10.4.69.90/syslab/`; búsqueda `parbusqueRut.php`. Requiere red del hospital.

- RUT: el portal busca el **cuerpo sin dígito**, puntos ni guion. El cliente acepta RUT completo con guion, valida el dígito y envía el cuerpo. El adaptador conserva el **RUT completo de la solicitud** para validar PDF y caché; el cuerpo usado en el formulario no sustituye esa identidad. No aplicar esta regla a Exalab.
- Acceso: credenciales propias autorizadas, `SYSLAB_USERNAME`/`SYSLAB_PASSWORD` en entorno del proceso o ingreso interactivo con contraseña oculta. No reutilizar credenciales de otro portal.
- Transporte: **HTTP directo** con formularios PHP, sesión de cookies, lectura del listado HTML y descarga PDF; no se ha confirmado una API JSON independiente. No necesita Chrome en la ejecución habitual.
- Ruta preferida: unificado con `--source syslab` para conservar avance. El [cliente directo](scripts/syslab_download.py) queda para consulta simple/diagnóstico: Python 3.9+, sin paquetes adicionales; `--rut --period --output`, opcionales `--list-only` y `--as-of AAAA-MM-DD`.
- Validación: PDF completo, identidad y folio coincidentes. Folio sin exámenes validados queda no disponible, según las reglas de reanudación; conservar y entregar los demás.

El transporte común reintenta una lectura transitoria como máximo una vez, respeta `Retry-After` y pausa la fuente si persiste; no reintenta contraseñas. No disponibles siguen pendientes sin nuevos intentos automáticos.

Si cambió el sitio o falla el acceso, inspeccionar el flujo visible con el perfil preferido. No cambiar ajustes de seguridad. Consulta exitosa vacía significa únicamente “sin registros en el período”.

Al cerrar la orden, incluir el [resumen numerado de fuentes](../laboratorios-descargas/references/cierre-fuentes.md) en respuesta y TXT, también si esta es la única fuente o queda parcial. No consultar fuentes adicionales para completar ese bloque.
