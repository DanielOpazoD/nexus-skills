# Plantillas de entrega

Espacio para los formatos del usuario. El 19-10-2026 se recibió el ejemplo de telereumatología: sus secciones y estilo están disponibles en [telereumatologia](../telereumatologia/SKILL.md), sin datos del paciente. La generación automática mediante plantillas institucionales sigue pendiente; el resto de los formatos espera recepción.

- [Epicrisis](epicrisis/)
- [Telemedicina · Reumatología](telemedicina-reumatologia/)
- [Telemedicina · Gastroenterología](telemedicina-gastroenterologia/)
- [Evolución · Eloísa ambulatoria](evolucion-ambulatoria/)
- [Evolución · Hospitalizados](evolucion-hospitalizados/)

[Catálogo de recepción](catalogo.json): ubicación, archivo, versión y fecha. Los IDs coinciden con el [catálogo del programa](../reporte-clinico/references/modelos-entrega.json). Reservar la carpeta o recibir un archivo no habilita automáticamente su generación; siguen pendientes hasta mapear los campos, validar identidad/episodio y probar la salida.

Subir únicamente formatos vacíos autorizados. Las copias completadas se guardan en el expediente privado del paciente, fuera de Git. Fechas visibles y nombres de versiones: DD-MM-AAAA. El archivo original recibido debe conservarse. Revisar cada incorporación y añadir su ruta explícita a `.gitignore`; no eludir la lista permitida con `git add -f`.

La entrega libre, el TXT basal de antecedentes y la opción «Sin formato adicional» no requieren plantilla institucional. El TXT basal acompaña cada corrida, según [su skill](../resumen-antecedentes/SKILL.md).
