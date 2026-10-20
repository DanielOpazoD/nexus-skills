# Capacidades y pendientes — 19-10-2026

Referencia de alcance, no comprobación de disponibilidad actual de los portales. El estado se informa por solicitud y fuente; las pruebas ficticias no acreditan accesos clínicos reales.

| Función | Alcance implementado | Lo que aún falta |
|---|---|---|
| Solicitud Air → Mini | HTML/extensión con «Enviar a Drive», JSON+marcador y receptor en el lanzador del Mini con acuse e ID estable; copiar/guardar como respaldo | Verificar distribución en el Air y traslado real entre equipos. El lanzador debe quedar abierto; el acuse solo confirma importación. |
| Seis portales | Clientes existentes, sesiones independientes, períodos y descargas; cola local persistente | Disponibilidad y sesión vigentes en cada ejecución. El Mini concentra el trabajo; Syslab/Exalab requieren su red. |
| Adjuntos Eloísa | Enumeración por atención, descarga de PDF original, identidad del encabezado, caché, parciales y archivo; ecocardiograma real comprobado | Formatos no PDF, escaneados o encabezados no reconocidos: revisión manual pendiente. |
| MMRAD actual | Informes TAC y radiografías por selección; ecocardiografías excluidas | Informes ausentes de TAC quedan pendientes. Informe de ecocardiograma: adjunto Eloísa. |
| Agenda Eloísa | Selector por día de Mi agenda en panel y extensión; Air y Mini usan sesión propia, pacientes deduplicados y selección explícita sin iniciar descarga | Selector de otros profesionales y citas grupales. Instalación/verificación del puente en cada equipo. |
| Hospitalizados | Epicrisis por cliente; ficha completa identificada mediante visor oficial | Descarga automática y validación completa de la ficha del visor. |
| Correo institucional | Consulta con conector en Codex, revisión de identidad/mensajes/adjuntos e importación al trabajo | Consulta autónoma desde el lanzador. No confundir coincidencia del buscador con documento verificado. |
| Cierre y continuidad | TXT obligatorio, bytes comprobados, recuperación de originales, reanudación selectiva y conservación de parciales | El estado describe la solicitud y los bytes verificados, no garantiza que el portal carezca de información nueva posterior. |
| Expediente en Drive | Carpeta por nombre con identidad por RUT, copia verificada y versiones | La confirmación remota requiere conexión OAuth del lanzador. Una copia local no prueba subida. |
| Formato de entrega | Opcional; selección de modelo o encargo libre para Codex | Plantillas institucionales del usuario y generación integrada. No firma ni envío a la ficha. |
| Resumen basal de antecedentes | Skill predeterminada, registro por paciente ligado a evidencia y fechas, validación, sustento TXT y copia comprobada; vigencia y recuperación tras reinicio | Redacción y cotejo clínico en Codex. El descargador independiente no redacta síntesis; fuentes completas no acreditan entrega. |
| Biopsias | Pendiente; señal visual sin selección ni consulta | Identificar fuente y acceso autorizado; implementar antes de habilitar. |

## Próximo módulo: Biopsias

Antes de diseñar el cliente, identificar el portal/repositorio y un informe de ejemplo autorizado. Definir qué fecha delimita la búsqueda (toma de muestra, recepción o informe) y qué productos se solicitan. Vincular RUT del paciente, identificador de muestra/biopsia, órgano/sitio y episodio cuando esté disponible; no inferir identidad por una mención incidental.

Conservar versiones preliminares, definitivas y adendas con su estado y fecha; un nuevo informe no borra los previos. Informar hallazgos de forma fiel a la fuente, sin interpretación añadida. Integrar después con solicitud, ejecución independiente, expediente, cierre y pruebas de paciente distinto, varias muestras, informe corregido y descarga parcial. Hasta entonces, una solicitud de biopsias queda «módulo pendiente», nunca «sin resultados».

## Criterio común

«Fuentes completadas», «documento redactado», «copia verificada» y «sincronización confirmada» son cuatro resultados distintos. Al reabrir/reanudar, comprobar los bytes esperados sin volver a certificar un archivo modificado con un hash nuevo. Mantener lo verificable y señalar solo lo que falta. Las pruebas de integridad usan datos ficticios y no vuelven a consultar pacientes por motivo de mantenimiento.
