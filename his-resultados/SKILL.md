---
name: his-resultados
description: Buscar atenciones del HIS Hanga Roa por RUT y período y exportar fichas clínicas a PDF de trabajo con verificación de paciente.
---

# Atenciones HIS Hanga Roa

Aplicar el [contrato común](../laboratorios-descargas/references/verificacion.md) y ejecutar con [laboratorios-descargas](../laboratorios-descargas/SKILL.md), también para un paciente. El contrato define identidad, entrega parcial, reporte y archivo.

Antes de consultar, leer el [estado operativo fechado](references/estado-servicio.md): hay una incidencia comunicada por el usuario; no es prueba de indisponibilidad permanente. Una comprobación fallida no bloquea otras fuentes ni invalida copias previas verificadas; declarar su fecha y actualización pendiente.

- Una prueba TCP de hasta 2 s precede al login; lecturas con un reintento transitorio y circuito de dos fallos. Un fallo de servicio pausa HIS para el resto del lote; no se confunde con credenciales rechazadas.
- Fuente `his`; unificado con RUT completo, período y salida. El portal busca por **cuerpo del RUT** en `consficha`.
- Acceso propio: llavero/formulario local o `HIS_USER`/`HIS_PASS` en CLI, con ingreso interactivo como alternativa. No escribir la contraseña en argumentos, Git, logs ni Visualize.
- Modo preferido: **HTTP directo** con formularios y lectura de HTML; no se ha confirmado una API JSON remota. El módulo local `his_reports/api.py` no demuestra que el servidor HIS ofrezca una API pública. Una caída del servidor también afecta al cliente programático.
- [Cliente](scripts/his_download.py): cookie autenticada; ficha HTML por ID/tipo. Verificar RUT, tipo, ID y fecha. Aceptar solo HTTPS `his.hospitalhangaroa.cl/hishhr/`, sin redirecciones a otros orígenes.
- PDF: **copia de trabajo generada**, no original del servidor. Una ficha incompleta/no verificable queda pendiente; entregar las demás. Contrastar dudas con la ficha del portal.

Lector [his_reports](scripts/his_reports/) basado en [his-reports](https://github.com/DanielOpazoD/his-reports), commit `0ec98caa42676c30599a8ae3990bee7ac1052f83`. Usar datos ficticios en pruebas.

Al cerrar la orden, incluir el [resumen numerado de fuentes](../laboratorios-descargas/references/cierre-fuentes.md) en respuesta y TXT, también si esta es la única fuente o queda parcial. No consultar fuentes adicionales para completar ese bloque.
