# Cierre obligatorio de cada orden clínica

Al cerrar **toda orden** de búsqueda, descarga, revisión o elaboración clínica, incluir un resumen en texto en la respuesta y guardar ese mismo bloque como `Resumen de fuentes - DD-MM-AAAA.txt`. Rige con `deliveryModel=documents`, sin plantilla, sin resultados, con error, cancelación o entrega parcial. No agregarlo a conversaciones generales o al mantenimiento del programa. Una instrucción posterior explícita de no crear archivos prevalece; en ese caso declarar que sólo se entregó el bloque en chat.

Formato estable: `[marca] número. Fuente — estado · archivos verificados · período · pendiente concreto`. Marcas:

- `[X]`: consulta solicitada completada; puede ser **sin registros** si la búsqueda terminó correctamente, o «listado completado; sin descarga solicitada» cuando el encargo fue solo listar.
- `[~]`: parcial, faltantes o documentación previa conservada con actualización pendiente.
- `[ ]`: pendiente/no consultada/no solicitada, con la palabra correspondiente. No convertir error o acceso vencido en «sin registros».

Orden: 1 Syslab; 2 Exalab; 3 Eloísa Ambulatorio; 4 HIS; 5 Eloísa Hospitalizados; 6 MMRAD; 7 Correo institucional. Mostrar las siete para dejar explícita la cobertura, sin consultar las no solicitadas. MMRAD agrupa informes/imágenes elegidos; ficha completa y epicrisis comparten Hospitalizados: un producto pendiente impide `[X]` global. Contar archivos con hash vigente, no snippets, enlaces ni registros aún no descargados. El cierre no cuenta como archivo clínico obtenido.

Ejemplo **ficticio**, fragmento:

```text
[X] 3. Eloísa Ambulatorio — consulta completada · 4 archivos verificados · 19-04-2026 → 19-10-2026
[~] 5. Eloísa Hospitalizados — parcial · 1 archivo verificado · epicrisis obtenida; ficha completa pendiente
[ ] 7. Correo institucional — pendiente · cuenta aún no conectada
```

Declarar paciente/RUT y fecha de referencia al inicio. Si sólo se revisaron archivos existentes, usar «revisión de archivos» y «portal no consultado», sin atribuir una búsqueda nueva. Indicar filtros contenidos/productos aplicados y cobertura por nombre/RUT del correo cuando sea relevante. Documentos guardados y documentos efectivamente leídos son recuentos distintos. Citas clínicas siguen el formato `[S1, p. 2]`; estos corchetes son únicamente el cierre operativo.

## Programa

[clinical_receipt.py](../scripts/clinical_receipt.py) genera el bloque por paciente y lo guarda atómicamente, conservando versiones. `run_batch` lo incluye en `summary.receipts` y el CLI lo imprime; el lanzador lo conserva incluso antes de obtener accesos y al cancelar, y ofrece copiar el texto o descargar TXT. El panel revalida archivos al consultar un trabajo y al restaurar el historial, incluso si antes estaba completo; un original recuperado y validado cuenta como documento disponible. La comprobación de contenido usa caché en memoria invalidada por cambios de archivo, sin alterar el hash esperado. Fuente completa con archivo ausente/modificado se muestra parcial tanto en el TXT como en el estado de la cola; las demás fuentes permanecen completas. Biopsias queda fuera de esta lista hasta implementar su módulo. `all` CLI conserva seis portales por compatibilidad; para las siete usar `syslab,exalab,eloisa,his,rayen,mmrad,email`. Las UI envían listas explícitas.

Para regenerar desde un resumen JSON válido: `python3 scripts/clinical_receipt.py RESUMEN.json --output OUTPUT`. Leer el bloque y enlazar el TXT en la respuesta. Para una orden ejecutada fuera del motor, construir el bloque con evidencia observada y guardarlo en la carpeta de trabajo; no fabricar un JSON de descarga completa. En reanudaciones, entregar el último cierre y conservar los anteriores como versiones, sin atribuirles vigencia actual.

Archivo: raíz del expediente por nombre junto a los resúmenes. Si aún falta nombre verificado, conservar el cierre local y copiar a `Documentos generales/Cierres pendientes de identificar/`, sin crear una carpeta por RUT ni inventar identidad. Cuando se identifique, copiar el último cierre al expediente; no mover documentos por similitud de nombres. La copia SHA-256 y la subida a Drive se comprueban por separado; este bloque no certifica la sincronización. Informar en la respuesta el estado de copia/nube conocido y pendientes.
