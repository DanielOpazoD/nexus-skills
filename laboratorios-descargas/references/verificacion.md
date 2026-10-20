# Contrato común del flujo clínico

Aplicar en búsquedas y al integrar documentación. Las fuentes añaden sus comprobaciones particulares.

## Alcance e identidad

Usar pacientes/fuentes autorizados en la tarea vigente; no reutilizar otra tarea ni pedir datos ya aportados. Para búsquedas, completar RUT y período faltantes juntos. Ofrecer 30 días, 3/6 meses, 1/2/5/10 años; respetar “último” y períodos ya indicados. Si el intervalo no es compatible, resolverlo sin ampliarlo silenciosamente.

Normalizar formato y validar dígito disponible sin corregir identidad. Verificar correspondencia entre registro autenticado y documento; no unir por parecido de nombres. RUT discrepante excluye el documento. En epicrisis, el RUN debe pertenecer al encabezado del paciente; no basta aparecer en otro rol. Comparar el episodio rotulado cuando exista. Metadatos ausentes quedan desconocidos.

Registrar fuente, folio/ID, archivo, fecha clínica y de consulta. Distinguir muestra, informe, atención y descarga. Usar Pacific/Easter como referencia temporal; no desplazar fechas sin hora al convertir zonas. “Último” usa fecha clínica de cada portal; en Correo, fecha del mensaje, declarando la fecha clínica aparte. Respetar “solo listar” y “solo chat”.

## Contenidos y contrato

El [catálogo](../assets/clinical_catalog.json) define opciones, rótulos y valores iniciales del panel y puente; `clinical_content.py` valida el mismo archivo. Generar controles con `build_portable_form.py`. `sourceContent` explícito forma parte del avance: no ampliar ni reinterpretar solicitudes antiguas. Paquetes versión 4 incorporan adjuntos Eloísa y el filtro de informes TAC; versiones 1–3 conservan su alcance y rechazan esos contenidos nuevos. El límite de MMRAD a TAC se aplica antes de buscar el último informe, no sólo en el rótulo del panel.

El [validador de entrada](../scripts/clinical_request.py) se comparte entre lanzador y solicitud portátil. Rechaza campos desconocidos, versiones no compatibles, casilleros que no sean booleanos, colecciones nulas, contenidos repetidos y claves JSON duplicadas antes de crear el trabajo o leer credenciales. Omitir una opción histórica conserva su valor anterior; enviarla mal escrita no activa un valor inicial silenciosamente.

CLI, motor y recuperación construyen la misma identidad del avance con `build_request`: pacientes, fuentes, período/fecha, carpeta, filtros, contenidos y consolidación. No basta coincidir RUT y período. El avance atómico compatible es la autoridad; un resumen posterior no puede sustituirlo. Cada paciente/producto tiene una fila: duplicados o metadatos dañados dejan ese grupo pendiente, conservan sus archivos verificables y no invalidan otros grupos. Esta comprobación también se aplica al TXT de cierre.

## Evidencia y fallos

Validar identidad, integridad y páginas legibles. Antes de reportar, contrastar valores/OCR ambiguos, unidades, signos y columnas contra la página. La validación automática del PDF no valida toda su extracción.

Distinguir: verificado; sin registros en el período (consulta exitosa); no disponible (registro sin archivo); parcial; autenticación pendiente; fuente inaccesible; identidad no verificada; no consultado. Un fallo no demuestra ausencia de antecedentes.

Usar sesiones/credenciales propias y mecanismos documentados disponibles; no guardar secretos en archivos, logs o argumentos. Puentes con CDP requieren capacidad real; si falta, usar lanzador/flujo visible permitido o declarar el acceso pendiente. No cambiar seguridad/TLS para entrar. Reintentar de forma acotada tras resolver la causa; detener intentos repetidos sin cambio. No disponibles requieren petición expresa de reintento.

## Entrega y continuidad

**Fechas de presentación:** usar siempre `DD-MM-AAAA` (ejemplo: `19-10-2026`) en nombres y contenido de archivos generados: reportes, formularios, estados, índices, gráficos y fechas añadidas a PDF. Mantener la precisión disponible, sin inventar día/mes. Conservar los originales descargados y las transcripciones literales; los contratos técnicos, API y estados de reanudación mantienen su formato interno. Usar Pacific/Easter al fechar la generación.

**Una fuente parcial no cancela lo verificado.** Conservar, entregar y reportar los documentos completos disponibles de todas las fuentes, incluida la parcial. La falta del consolidado no impide entregar individuales; el código global de error exige leer resultados por fuente. No publicar documentos truncados o de identidad incierta.

Mantener avance local para reanudar. Preservar versiones y fuentes; una copia previa no prueba que no haya novedades si se pidió actualizar. Registrar recuentos conocidos y motivos concretos de pendientes, sin estimarlos.

Para síntesis solicitada, cargar [reporte-clinico](../../reporte-clinico/SKILL.md). Para guardar fuentes/productos, cargar [eloisa-archivo-drive](../../eloisa-archivo-drive/SKILL.md). Cerrar con ubicación, cobertura y sincronización por separado. No cargar ni ejecutar de nuevo etapas ya resueltas.

## Cierre de toda orden

Aplicar [cierre-fuentes](cierre-fuentes.md): bloque numerado `[X]/[~]/[ ]` en respuesta y TXT, incluso sin documento clínico pedido. Distinguir búsqueda exitosa vacía, pendiente y parcial; preservar lo obtenido. En revisiones de archivos existentes declarar «portal no consultado». Correo añade identidad por rol, revisión de mensajes/adjuntos, cuenta institucional y fecha del mensaje según [correo-clinico](../../correo-clinico/SKILL.md).

## Fronteras del programa

- `clinical_domain.py` fija identidad y alcance del avance; `clinical_request.py` valida formulario/paquete sin importar el motor ni leer credenciales.
- `clinical_state.py` concentra transiciones por evento. Cancelar impide arrancar o aceptar sesiones; sólo reanudar explícitamente lo revoca, cuando el proceso ya terminó.
- `clinical_store.py` valida/persiste la cola y aparta trabajos dañados con respaldo. `clinical_recovery.py` devuelve una instantánea y progreso por fuente, sin escribir la cola ni modificar el trabajo de entrada.
- `clinical_jobs.py` coordina procesos, sesiones y publicación de esos resultados. `laboratorios_download.py` ejecuta fuentes y conserva avances/documentos. Archivo y cierre siguen módulos independientes.

Mantener la compatibilidad del contrato de avance durante refactorizaciones: cambiar su representación requiere migración explícita. Las funciones públicas del motor siguen reexportando el contrato común para CLI y clientes existentes.
