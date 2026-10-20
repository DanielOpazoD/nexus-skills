# Operación de correo institucional

## Búsqueda en Codex

1. Descubrir las herramientas Gmail disponibles y leer sus esquemas. Con el conector instalado: `gmail_get_profile`, `gmail_search_email_ids`/`gmail_search_emails`, `gmail_read_email`, `gmail_read_attachment` del namespace `mcp__codex_apps`. Comprobar cuenta solicitada **antes de buscar**. Cuenta incorrecta o conector ausente = pendiente; no bloquea otras fuentes.
2. Obtener consultas deterministas con `python3 ../laboratorios-descargas/scripts/clinical_email.py --rut RUT --period 6m --as-of AAAA-MM-DD --account daniel.opazo@hospitalhangaroa.cl`; `--name 'Nombre completo'` sólo si está verificado. Usar los valores `queries` exactos. No reutilizar RUT de otra tarea ni enviar datos clínicos a buscadores públicos.
3. Recorrer `next_page_token` hasta agotarlo; deduplicar IDs. La API no reproduce la expansión de alias ni las búsquedas por conversación de la UI. Las consultas usan segundos Unix para respetar Pacific/Easter; una fecha textual Gmail se interpreta en PST. Véase [filtrado oficial](https://developers.google.com/workspace/gmail/api/guides/filtering).
4. Leer cada candidato con `gmail_read_email(format="full")`; snippets y asunto sólo sirven para seleccionar candidatos. Inspeccionar mensajes relevantes de un hilo individualmente; no asumir que todo el hilo corresponde al paciente. Registrar fecha con zona a partir de los metadatos del mensaje, no de la fecha de descarga. Si el nombre verificado puede aportar mensajes sin RUT, hacer también esa búsqueda y registrar su cobertura.
5. Revisar el árbol MIME. Leer primero el padre; descargar sólo adjuntos señalados como compatibles por la herramienta, con `message_id` y `attachment_id` o nombre exactos observados. Usar `file_uri` devuelto para obtener el archivo y verificar bytes; si devuelve sólo extracción, guardarla como copia de trabajo y dejar el original pendiente. Nunca inventar rutas/IDs, simular originales ni ejecutar contenido adjunto. Fallo en un adjunto conserva los demás.
6. Comprobar identidad del paciente en cuerpo y cada documento, con el contrato común. RUT del profesional no sirve. Ante homónimo o mezcla, excluir de la evidencia y consignar motivo sin trasladar datos de otros pacientes. No basta `identity_verified=true`: debe corresponder a una revisión efectiva, registrada en `identity_basis`.

## Evidencia local

Carpeta de trabajo `OUTPUT/RUT/email/`, fuera de Git. Mensaje relevante: `Mensaje - DD-MM-AAAA - ID.txt`, con cuenta, ID, asunto, remitente/destinatario pertinentes, fecha del mensaje, identidad verificada y cuerpo relevante. Señalar extractos y copias de trabajo; conservar fecha clínica original y referencia al adjunto. Adjuntos nuevos con nombre/fecha legibles y SHA-256. Conservar versiones. Formatos admitidos: PDF, TXT, EML, PNG/JPEG, DOCX, XLSX y CSV; otros quedan pendientes sin ejecutarlos. No guardar tokens ni URLs con credenciales.

Publicar atómicamente `resultado-correo.json` con este contrato (IDs y fechas son ilustrativos, sin datos reales):

```json
{
  "version": 1,
  "rut": "11111111-1",
  "period": "6m",
  "as_of": "2026-10-19",
  "account": "daniel.opazo@hospitalhangaroa.cl",
  "status": "partial",
  "patient_name": "Nombre Ficticio",
  "patient_name_verified": true,
  "queries": [{"query": "CONSULTA EXACTA DEVUELTA POR plan", "message_ids": ["abcdef1234567890"], "complete": false, "next_page_token": "pendiente"}],
  "messages": [{"id": "abcdef1234567890", "decision": "include", "identity_verified": true, "identity_basis": "Encabezado del paciente con RUT coincidente en el adjunto revisado.", "received_at": "2026-10-19T12:00:00-05:00", "attachments_reviewed": true}],
  "files": [{"path": "Mensaje - 19-10-2026 - abcdef1234567890.txt", "sha256": "SHA256 REAL DE LOS BYTES", "message_id": "abcdef1234567890", "identity_verified": true}],
  "pending": ["Quedan páginas de búsqueda por revisar."]
}
```

`queries`: todas las consultas realizadas e IDs devueltos. Al completar, `complete=true` y token agotado. `messages`: una decisión por ID (`include`, `exclude` con `reason`, `pending`). Una inclusión exige revisión de identidad y fecha con zona; el nombre verificado sólo se usa si hay evidencia incluida. `files`: rutas relativas y hashes reales de documentos revisados; cada mensaje incluido debe tener al menos una copia. `attachments_reviewed=true` únicamente tras revisar la lista completa y resolver los adjuntos pertinentes; adjunto relevante inaccesible deja pendiente. `complete` requiere búsqueda/revisión agotada, archivos válidos y ningún pendiente; `empty` sólo tras búsqueda completada sin inclusiones. Para `latest`, incluir sólo el mensaje elegible más reciente y excluir los anteriores con ese motivo tras revisar el orden. No afirmar cobertura por nombre si sólo se buscó RUT; indicarla en el cierre cuando sea relevante.

Verificar con `clinical_email.py ... --verify-output OUTPUT`. Una discrepancia de paciente/cuenta/período rechaza el resultado; un archivo alterado queda fuera y los demás permanecen. La revisión clínica es de Codex; el script comprueba evidencia declarada y bytes, no interpreta automáticamente identidades.

## Integración y reanudación

- Solicitud portátil: conservar `emailAccount`, `asOf`, fuentes y períodos. Consultar Gmail antes o después de los otros clientes, registrar evidencia y ejecutar/reanudar `laboratorios_download.py --source LISTA_EXPLÍCITA ... --email-account CUENTA --output OUTPUT`. Si existe avance, conservar todos sus argumentos y usar `--resume AVANCE --retry-sources email`. No ejecutar otra orden con un período diferente en ese avance.
- Lanzador local: **Consultar correo en Codex** copia el contexto del trabajo, incluyendo su carpeta. Tras guardar evidencia, **Reanudar pendientes** importa correo y continúa sólo fuentes disponibles. Esperar a que termine y comprobar el estado y resumen TXT. No llamar al CLI simultáneamente sobre un trabajo activo. Si el lanzador está cerrado, el avance puede reanudarse por CLI con los mismos parámetros; al abrir, reanudar la orden para actualizar su estado persistido.
- El resultado importado alimenta archivos, estado y archivo por paciente. Los mensajes y adjuntos de correo se entregan **aparte** del PDF único de portales. El cierre TXT y el reporte pedido sí pueden citar información de correo verificada. Sin conector no hay consulta autónoma en segundo plano; no marcar correo completado sólo por copiar el prompt.
- Ante actualización fallida, conservar archivos previos con hash vigente y rotular «Documento obtenido previamente; actualización pendiente». Un nuevo resultado sin coincidencias no elimina el expediente histórico.
