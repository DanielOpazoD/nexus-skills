---
name: correo-clinico
description: Buscar información clínica de pacientes autorizados en el correo institucional conectado a Codex, verificar mensajes y adjuntos, conservar evidencia y cerrar con resumen de fuentes en TXT.
---

# Correo clínico

Fuente `email`. Cuenta elegida: **daniel.opazo@hospitalhangaroa.cl**; conservar `emailAccount` de cada solicitud. Consultar sólo pacientes y período autorizados, con herramientas Gmail conectadas a Codex. El programa local prepara/importa esta etapa; todavía no consulta Gmail autónomamente.

Antes de buscar, leer [operación y contrato de evidencia](references/operacion.md). Comprobar perfil conectado; si la cuenta no coincide, dejar correo pendiente y continuar las otras fuentes. No trasladar la búsqueda a la cuenta personal ni abrir otro acceso por suposición.

Buscar variantes del RUT; añadir el nombre completo sólo cuando esté verificado. Paginar, leer mensajes completos y revisar adjuntos pertinentes. Una coincidencia del buscador no acredita identidad: vincular el RUT al paciente, distinguir profesional/familiar y homónimos. Sin RUT en el mensaje, exigir nombre completo y otro identificador independiente contrastado con una fuente verificada. Identidad ambigua queda pendiente, fuera del expediente.

Guardar sólo material del paciente solicitado: cuerpo relevante en TXT como copia de trabajo y adjuntos verificados. Si contiene otros pacientes, preparar extracto identificado; no archivar el mensaje íntegro mezclado. Registrar cuenta, ID, remitente, asunto, fecha del mensaje, fecha clínica cuando conste y fundamento de identidad. Correo es correspondencia: atribuir sus afirmaciones al remitente, sin convertirlas en diagnósticos confirmados.

La ventana se aplica a la **fecha del mensaje**. Declarar por separado la fecha clínica del documento; `latest` selecciona el mensaje elegible más reciente, no garantiza el documento clínico más reciente. No deducir ausencia de antecedentes de un fallo, paginación incompleta o adjunto inaccesible. Conservar todo lo verificado aunque otra descarga falle.

Registrar `resultado-correo.json` e importar con el cliente unificado según la referencia. Su validador comprueba alcance, integridad y revisión declarada; **no sustituye la revisión de identidad por Codex**. En Drive: `Pacientes/Nombre completo/Fuentes primarias/Correo/`, siguiendo [archivo por paciente](../eloisa-archivo-drive/SKILL.md). No enviar, reenviar, etiquetar, borrar ni crear borradores como parte de esta búsqueda.

Cerrar siempre la orden con el [resumen numerado de fuentes](../laboratorios-descargas/references/cierre-fuentes.md), en la respuesta y en TXT. Fechas generadas `DD-MM-AAAA`; estados técnicos ISO. La plantilla clínica de entrega sigue siendo opcional.
