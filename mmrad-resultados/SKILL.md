---
name: mmrad-resultados
description: Consultar MMRAD RIS por RUT y período, descargar informes TAC y radiografías; conservar DICOM y excluir imágenes de ecocardiogramas.
---

# MMRAD: informes e imágenes

Aplicar el [contrato común](../laboratorios-descargas/references/verificacion.md) y ejecutar con [laboratorios-descargas](../laboratorios-descargas/SKILL.md), también para un paciente. El contrato define identidad, entrega parcial, reporte y archivo.

[Cliente](scripts/mmrad_download.py), fuente `mmrad`, RUT completo. Portal: `https://ris.mmrad.cl/web/guest/home`.

## Acceso e informes

Credenciales propias: `MMRAD_USERNAME`/`MMRAD_PASSWORD` en entorno o servicios homónimos del llavero; el puente admite `secrets.mmrad={username,password}` por stdin. No usar credenciales Eloísa ni la función Netlify de HHR, que tiene autorización distinta. Mantener secretos y HTML clínico fuera de logs, argumentos, Git y Visualize.

Modo preferido: **HTTP directo** para acceso, búsqueda e informes; **SockJS/DDP y descarga WADO por el proxy del visor** para DICOM. Todo está implementado en Python; Chrome queda para diagnóstico si cambia el portal. No implica una API REST pública.

El cliente obtiene acciones dinámicas Liferay, valida URL/redirecciones contra `https://ris.mmrad.cl` y busca con `idpaciente`, `fechaexamendesde`/`fechaexamenhasta` (`DD/MM/YYYY`). Descargar solo `informePDF` con Referer del panel; validar firma/cierre, páginas y RUT rotulado cuando exista.

## Selección y ausencias

Distribución actual informada por el usuario: **radiografías sin informes**, **TAC habitualmente con informe**, **ecocardiogramas con imágenes en MMRAD e informe adjunto en Eloísa Ambulatorio**. No buscar el informe de ecocardiograma en MMRAD ni descargar sus imágenes.

El formulario compacto ofrece **Informes TAC** y **Radiografías**, ambos preseleccionados al habilitar MMRAD. Transmite `--mmrad-mode reports|images|both`, `--mmrad-image-types radiographs` y, si pide informes, `sourceContent.mmrad=["ct_reports"]`. Este último filtro limita realmente la consulta de informes a modalidad CT, incluso en `latest`. No descarga imágenes TAC. Buscar informes de ecocardiograma en Eloísa únicamente si esa fuente y `attachments` están seleccionados.

Compatibilidad: solicitudes antiguas sin `ct_reports` conservan su alcance de informes; el CLI aún admite `ultrasounds` explícito para ecografías no cardíacas. **Excluir siempre imágenes de ecocardiografías**, cualquiera sea el cliente. El cliente comprueba la descripción del RIS y las descripciones de estudio/series del visor antes de descargar DICOM; registrar las exclusiones. Una descripción errónea o sin identificación cardíaca puede requerir revisión. `latest` amplía las ventanas hasta encontrar un estudio elegible para los tipos seleccionados, sin detenerse en una ecocardiografía excluida.

- CR/DX/DR y US sin informe PDF: informe no esperado, no fallo por sí solo.
- CT sin `informePDF`: pendiente/no disponible; sin reintentos automáticos.
- HTML, comprobante y visor DICOM no son informes PDF. Un error de autenticación no significa cero estudios.

Para imágenes, leer [DICOM](references/dicom.md): conservar originales y generar un PDF separado por estudio, sin capturas del visor. El avance por instancia evita repetir descargas parciales; hasta dos trabajadores optativos con sesiones aisladas (`--image-workers 2`). Si falta una instancia, no publicar ese PDF; conservar lo obtenido y entregar los otros estudios verificados.

Al cerrar la orden, incluir el [resumen numerado de fuentes](../laboratorios-descargas/references/cierre-fuentes.md) en respuesta y TXT, también si esta es la única fuente o queda parcial. No consultar fuentes adicionales para completar ese bloque.
