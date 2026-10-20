---
name: eloisa-archivo-drive
description: Archivar por nombre de paciente en Google Drive las fuentes, descargas, resúmenes y formularios del flujo clínico HHR (Eloísa, HIS, Syslab, Exalab, MMRAD, Eloísa Hospitalizados y Correo institucional), conservando originales y versiones. Aplicar al guardar documentos clínicos y revisar el archivo automático del lanzador local.
---

# Archivo clínico por paciente

Destino habitual de las fuentes y productos clínicos HHR obtenidos con Codex; aplicarlo salvo indicación contraria. Respetar pedidos de solo listar o solo chat; conservar el cierre operativo TXT salvo instrucción explícita de no guardar. No ampliar consultas ni cambiar permisos de uso compartido.

## Destino

- Cuenta: `d.opazo.damiani@gmail.com`.
- **Archivos Mac mini**, ID `1hMcac9_0IxeuB4o28LDm5zYCXYOJs3WT` ([Drive](https://drive.google.com/drive/folders/1hMcac9_0IxeuB4o28LDm5zYCXYOJs3WT)).
- Acceso local: `~/Desktop/Archivos Mac mini`.
- Destino real: `~/Library/CloudStorage/GoogleDrive-d.opazo.damiani@gmail.com/Mi unidad/Archivos Mac mini`.

Comprobar que el enlace resuelve dentro de esa cuenta y está disponible. Si Drive está desconectado, conservar localmente y declarar pendiente; **no crear una carpeta sustituta que parezca sincronizada**. Alternativa: conector Drive, leyendo su skill y verificando cuenta/ID. En otro Mac, localizar la misma carpeta sin asumir idéntica ruta.

## Identidad y ubicación

Reutilizar `Pacientes/Nombre completo/`; comprobar nombre y RUT en registro/documento verificado. El RUT verifica identidad, no nombra carpetas. Los estados de descarga existentes pueden acreditar la correspondencia. No unir por similitud; ante identidad incierta, dejar fuera del expediente e informar. Para homónimos verificados, usar un sufijo estable como `(2)` y registrar la identidad correspondiente.

```text
Pacientes/Nombre completo/
  Resumen de antecedentes.docx
  Resumen de antecedentes.txt
  Estado de descargas - DD-MM-AAAA.txt
  Resumen de fuentes - DD-MM-AAAA.txt
  Fuentes primarias/
    Atenciones Eloisa/Originales individuales/
    Atenciones Eloisa/Documentos adjuntos/
    Laboratorio HHR/
    Laboratorio HDS/
    Atenciones HIS HHR/
    Epicrisis Rayen/
    Correo/
    Imagenologia MMRAD/imagenes_pdf/
    Imagenologia MMRAD/originales_dicom/
Documentos generales/
```

Crear solo categorías necesarias. Resúmenes individuales visibles en la raíz del paciente; agendas, índices y registros globales en Documentos generales. Mantener la identificación de copias de trabajo Eloísa/HIS y exportaciones por impresión de Rayen; no presentarlas como PDF originales del servidor. Los PDF adjuntos de Eloísa son originales: conservar sus bytes e identidad, separados de las evoluciones generadas, incluso cuando se pide agrupar. Las epicrisis Rayen descargadas se archivan como fuente hospitalaria separada de Ambulatorio e HIS.

## Copia y comprobación

Fechas de los nombres de salida, estados, resúmenes y sufijos de versión: **DD-MM-AAAA** (ejemplo `19-10-2026`; hora adicional `HH-mm-ss` cuando haga falta). Preservar el contenido de las fuentes originales y los estados técnicos locales.

1. Archivar fuentes efectivamente consultadas y verificadas, exportaciones, reportes, consolidados, individuales y DICOM obtenidos. Exportar registros sin archivo solo cuando el alcance y el flujo lo permitan; registrar los no disponibles. Reutilizar contenido íntegro y vigente; una actualización solicitada puede exigir consultar el portal.
2. Si el cliente necesita `RUT/sitio` y `.avance`, conservar esas rutas locales y **copiar** al expediente. Incluir los originales ocultos de `.avance/ID/originales/RUT/sitio/` y los documentos completos de grupos `incompletos`. No copiar credenciales, sesiones ni estados técnicos de reanudación.
3. Archivar al terminar cada paciente/lote sin esperar a que todas las fuentes estén completas. Una descarga parcial o consolidación fallida no cancela documentos válidos ni su reporte. Registrar pendientes por fuente.
4. Conservar fuentes locales. Reutilizar duplicados idénticos; contenido distinto conserva ambas versiones con fecha/hora Pacific/Easter. Verificar tamaño y SHA-256 de las copias, incluidos DICOM/subcarpetas.
5. Comprobar subida con Drive de escritorio o conector: archivo y carpeta esperados, tamaño/hash cuando estén disponibles. Presencia local o recuento global no acreditan sincronización. Entregar ubicación y pendientes concretos.

Esta skill no modifica el guardado de descargas manuales fuera de Codex.

## Archivo automático del lanzador

[clinical_archive.py](../laboratorios-descargas/scripts/clinical_archive.py) aplica esta estructura al terminar cada ejecución, incluso parcial. Revalida originales del avance, conserva versiones, distingue homónimos por RUT y deja pendiente una carpeta sin identidad comprobable. Incluye PDF publicados, originales, DICOM y estado. No copia sesiones ni la cola. La copia se comprueba por SHA-256; `DriveVerifier` solo confirma nube tras cotejar ruta, tamaño y checksum remotos con acceso autorizado. Sin ese acceso informa pendiente. Configuración y límites en [interfaz local](../laboratorios-descargas/references/interfaz-local.md).

El [cierre de fuentes](../laboratorios-descargas/references/cierre-fuentes.md) se copia aunque no se haya obtenido documentación clínica. Si no hay nombre verificado, usar `Documentos generales/Cierres pendientes de identificar/` para ese TXT, sin crear expediente por RUT. Correo usa sólo mensajes/adjuntos de identidad revisada: copias de trabajo rotuladas, hash vigente y originales separados; no copiar evidencia mezclada con otros pacientes.
