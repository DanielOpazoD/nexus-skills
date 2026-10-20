# Actualización incremental

El lanzador pasa `--cache-dir ~/Documents/Descargas clínicas/.cache-documentos` a sus trabajadores. Es una optimización privada del Mini; no se archiva en Drive ni Git. No modifica ID, fecha de referencia, fuentes, períodos, selección de contenidos ni los documentos de pedidos anteriores. El CLI puede indicar su propia carpeta; `--fresh` evita la reutilización entre pedidos de esta capa.

Siempre consultar primero el listado autenticado dentro del período solicitado. Un archivo previo no demuestra resultados actuales si esa consulta falla. Cada pedido conserva sus propias copias verificadas y cierre, aunque reutilice bytes.

- **Eloísa, evoluciones:** reutilizar PDF solo con coincidencia de RUT, atención, fecha, nombre, nodo, alcance, contenidos, contenido estructurado actual y versión del renderizador. Una corrección cambia la clave. Volver a validar identidad/atención y hash al leer la copia. Adjuntos: su nombre/ruta no acredita que sus bytes sigan iguales; descargarlos y verificarlos nuevamente.
- **Syslab, Exalab y PDF MMRAD:** usar validación HTTP condicional con `ETag` o `Last-Modified` únicamente si el servidor los entrega. En cada consulta del PDF, el servidor debe responder 304 para reutilizar una copia cuyo hash e identidad siguen siendo válidos. Una respuesta 200 se descarga y valida nuevamente; errores de sesión/red no habilitan una copia antigua. Sin validadores, con `no-store` o con `Vary`, no habilitar esa optimización. URL completa y credenciales no se persisten en metadatos.
- **Hospitalizados:** compartir entre pedidos la caché HTTP de epicrisis ya existente, con su revalidación condicional e identidad/episodio. No sustituye el flujo pendiente de ficha completa del visor.
- **HIS e imágenes:** mantienen su descarga y avance existentes; la huella de una fila del listado no acredita que todo el documento o estudio siga igual.

La caché guarda PDF completos validados, nombrados por SHA-256, y metadatos mínimos. Corrupción, falta de archivo o fallo al guardar producen una lectura nueva, sin borrar originales. El resultado técnico por fuente informa descargas, revalidaciones HTTP y reutilizaciones estructuradas de esta capa; no equivale a una medida de cobertura clínica.

Las pruebas simulan documentos corregidos, cambio de contenido/paciente, sesión vencida, fallo de red, caché corrupta, 200/304 y servidores sin validadores. La presencia real de validadores y el ahorro de tiempo por portal deben medirse en una consulta clínica autorizada; las pruebas ficticias no lo demuestran. Referencia: [RFC 9111, validación](https://www.rfc-editor.org/rfc/rfc9111.html#section-4.3).
