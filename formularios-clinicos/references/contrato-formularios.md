# Contrato por formulario

El catálogo `variables.json` identifica conceptos; el manifiesto identifica casilleros de una
plantilla. El PDF puede repetir un nombre varias veces sin crear nuevas variables del paciente.
No es necesario migrar `PatientData` para usar nombres canónicos en un adaptador de lectura.

## Estructura

Un manifiesto tiene `catalogVersion`, `formId`, `templateRevision`, `localVariables` y `bindings`.
La revisión debe identificar la plantilla concreta; al implementarla asociar su archivo y hash
verificados. Los IDs de `localVariables` llevan el prefijo del formulario (`medif_...`). No copian
variables ya comunes con otro nombre. Las magnitudes numéricas nuevas deben declarar unidad
y momento de medición cuando corresponda; no convertir un dato ausente en cero. Cada binding tiene un `fieldId` real y único, `entryMode`,
`required` booleano y `format`: `text`, `date_dmy` o `mark_x`.

| entryMode | Fuente | Entrada y salida |
|---|---|---|
| editable | `variable` común o local | Un control editable por variable; puede recibir propuesta del censo. |
| linked | `variable` común o local | Copia del mismo valor, sin otro control independiente. |
| fixed | `constant` definido para la plantilla | Sin obligación de completar; se imprime la constante. |
| suppressed | `variable` o `constant` de esa plantilla | Sin obligación de completar; salida vacía aunque exista un valor. |

`date_dmy` imprime DD-MM-AAAA y requiere una variable de tipo `date`. No convierte ni adivina fechas inválidas.
`mark_x` requiere una variable booleana y `equals: true` o `equals: false`. El valor null deja
ambas alternativas vacías. Escribir false no debe marcar la opción «no» cuando el dato falta.
Para marcar una opción, comparar explícitamente el valor observado con `equals`.

El binding puede añadir `kind: "signature"`; sólo admite entrada manual o supresión. El nombre
del médico no es su firma. `justification` documenta una excepción semántica pedida para esa
plantilla, no una autorización general. Los ejemplos no contienen datos de personas.

## Estado de los datos y preferencias

El snapshot de formulario mantiene `mode` (`hospitalized` o `manual`), valores canónicos, contexto
de origen y procedencia por campo. Por ejemplo, un valor puede registrar `source: "hhr"`,
`sourcePath: "beds.R1.clinicalCrib.admissionDate"`, `recordDate`, `sourceLastUpdated`,
`transformation`, `editedByUser` y `requiresReview`. Registrar sólo lo necesario; los identificadores
internos se usan para vincular, no se imprimen ni exportan a preferencias por defecto.

Las preferencias mantienen `formId`, revisión y configuración de campos permitida; no valores.
La supresión tiene prioridad sobre required, constantes opcionales y propuestas de llenado.
Para una constante que el usuario quiera dejar vacía, cambiar su modo a suppressed mediante la
configuración del formulario, no inventar una variable del paciente que contenga esa constante.
Las copias de una respuesta deben compartir su política de supresión para evitar filtrarla en
otra página del mismo formulario. Otro formulario puede usar el mismo dato canónico sin suprimirlo.

## Validar

Desde la carpeta de la skill:

```sh
python3 scripts/validar_contrato.py
python3 scripts/validar_contrato.py --manifest references/ejemplo-medif.json
python3 scripts/validar_contrato.py --manifest /ruta/al/nuevo-formulario.json
python3 scripts/validar_contrato.py --manifest references/ejemplo-medif.json --field-inventory /ruta/a/medifSchema.json
```

El script comprueba tipos del contrato, referencias, duplicados, controles repetidos, fechas,
marcas y firmas. No comprueba el significado clínico, dígitos verificadores, geometría PDF ni
la presencia física de un casillero. `--field-inventory` permite cotejar sus IDs con un esquema
JSON verificado, pero no inspecciona el PDF. Revisar el significado y la impresión en la plantilla real.
La salida de un PDF suprimido debe probarse con datos canónicos presentes, no sólo con vacíos.

## Motor de ejecución HHR

El PR #863 incorpora un formato de ejecución ya integrado: los JSON de
`src/features/clinical-library/domain/forms/` describen `fields` (una entrada por variable)
y `targets` (sus posiciones PDF). El enlace repetido es implícito por compartir la entrada;
la supresión se configura por variable y se aplica a todos sus targets. La revisión incluye
SHA-256 de la plantilla y fuente, páginas y rectángulos en puntos desde arriba a la izquierda.

Al ampliar ese motor, mantener ese formato y ejecutar las pruebas `clinicalFormPdf`,
`clinicalFormDraft`, `clinicalFormPatient` y `ClinicalFormEditor` del repositorio. El validador
portátil de esta skill valida catálogos y manifiestos `bindings`; no valida los JSON `fields`.
Los cuatro modos conceptuales siguen vigentes: no equiparar una preferencia de supresión con
un dato fijo o una copia enlazada. La fecha de emisión tiene valor por documento y el dato
de paciente puede compartirse entre documentos del mismo sujeto.
