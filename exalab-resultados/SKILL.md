---
name: exalab-resultados
description: Buscar y descargar PDF de laboratorio de Exalab SSMO por RUT y período mediante Python, reutilizando la sesión ClaveÚnica del perfil personal de Chrome.
---

# Laboratorio Exalab SSMO

Aplicar el [contrato común](../laboratorios-descargas/references/verificacion.md) y ejecutar con [laboratorios-descargas](../laboratorios-descargas/SKILL.md), también para un paciente. El contrato define identidad, entrega parcial, reporte y archivo.

Portal: `https://exalab.saludoriente.cl/web_ssmo/index.php`; fuente `exalab`. Entrada: **RUT completo con dígito**, sin puntos y con guion.

## Acceso y verificación

Chrome personal `d.opazo.damiani@gmail.com` (“daniel”), sesión ClaveÚnica. El usuario autorizó autocompletado y pulsar “INGRESA”; no extraer contraseñas ni usar credenciales Syslab. Verificar “Consulta Exámenes”. Si el autocompletado no permite entrar, pedir inicio de sesión al usuario.

Modo preferido: **HTTP directo** mediante el cliente Python tras autenticar en Chrome; procesa el listado HTML y descarga PDF con la sesión autorizada. No se ha confirmado una API JSON independiente. El procedimiento visible siguiente es referencia de verificación/diagnóstico, no un paso manual obligatorio en cada descarga.

En la interfaz, consultar y esperar a que termine “Espere por favor”. En “Folios Asociados”, verificar paciente/fecha/folio. “Último” exige comparar fechas. Abrir el número de examen y descargar el PDF incrustado. Cada PDF corresponde a un folio; un número de orden interno puede ser diferente: verificar RUT y fecha/hora contra la lista autenticada y el enlace obtenido para ese folio.

## Ejecución

Preferir el unificado para avance/reanudación. Antes del lote comprueba por HTTP que aparece el buscador autenticado; si falta, clasifica sesión pendiente y continúa las otras fuentes. La recuperación está en [continuidad](../laboratorios-descargas/references/continuidad.md). Antes de usar el [cliente directo](scripts/exalab_download.py), su [puente](scripts/exalab_chrome_bridge.mjs) o diagnosticar navegación, leer [cliente directo](references/cliente-directo.md).

El puente obtiene solo `PHPSESSID`, `cf_clearance` y User-Agent aplicables al portal; los envía por stdin sin persistencia. Conservar HTTPS/TLS. Las rutas de laboratorio devueltas son parámetros de Exalab, no una autorización para conectarse a sus servidores internos.

Al cerrar la orden, incluir el [resumen numerado de fuentes](../laboratorios-descargas/references/cierre-fuentes.md) en respuesta y TXT, también si esta es la única fuente o queda parcial. No consultar fuentes adicionales para completar ese bloque.
