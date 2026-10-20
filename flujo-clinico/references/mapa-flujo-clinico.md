# Mapa del flujo clínico HHR

Arquitectura documentada al 19-10-2026, instalada localmente en el Mac mini. [PDF de los dos esquemas](esquemas/mapa-flujo-clinico.pdf). Este mapa explica capacidades y responsabilidades; la disponibilidad de cada portal se comprueba en la ejecución.

## Organización de las skills

![Organización de las doce skills clínicas y apoyo de Chrome](esquemas/mapa-1.png)

`flujo-clinico` coordina y carga solo los módulos necesarios. `laboratorios-descargas` comparte ejecución, verificación y reanudación entre seis clientes de portal y una importación de correo revisado. `reporte-clinico` define la síntesis; `formularios-clinicos`, el formulario solicitado; `eloisa-archivo-drive`, la copia al expediente. Los productos también pueden partir de archivos existentes verificados, sin abrir portales. El [enrutamiento principal](../SKILL.md) enlaza cada skill.

```mermaid
flowchart TB
    U["Paciente · período · fuentes · entrega"] --> F["$flujo-clinico"]
    F --> D["laboratorios-descargas"]
    F --> R["reporte-clinico"]
    F --> C["formularios-clinicos"]
    subgraph S["Siete skills de fuente"]
      direction LR
      SY["syslab-resultados"]
      EX["exalab-resultados"]
      EL["eloisa-resultados"]
      HI["his-resultados"]
      MM["mmrad-resultados"]
      RA["rayen-epicrisis"]
      EM["correo-clinico"]
    end
    D --> S
    S --> V["Fuentes verificadas"]
    X["Archivos existentes verificados"] --> V
    V -. "si se solicita" .-> R
    V -. "si se solicita" .-> C
    V --> A["eloisa-archivo-drive"]
    R --> A
    C --> A
    A --> G["Drive: Pacientes / Nombre completo"]
    B["chrome-perfil-personal: inicio o renovación"] -.-> EL
    B -.-> EX
    B -.-> RA
```

Las flechas describen coordinación y movimiento de documentos; no implican ejecutar todas las etapas. Consola, puente Codex y formulario local integran siete fuentes; correo usa Gmail en Codex y luego importa su evidencia. El lanzador añade cola persistente y archivo automático por paciente. Una solicitud de solo listar o solo chat conserva esos límites, con cierre operativo TXT obligatorio salvo instrucción posterior contraria.

## Acceso y recorrido de los datos

![Acceso a fuentes, verificación, trabajo local y expediente en Drive](esquemas/mapa-2.png)

API JSON y HTTP con formularios/HTML son accesos programáticos distintos. Chrome inicia o renueva las sesiones que lo requieren; los clientes realizan las consultas y descargas. Los detalles de transporte, autenticación y procedencia del PDF están en la [matriz de acceso](../../laboratorios-descargas/references/modos-acceso.md).

```mermaid
flowchart TB
    U["Paciente, período y fuentes autorizadas"] --> J["Cola local persistente: fuentes disponibles primero"]
    J --> M["Gmail conectado a Codex: identidad de mensajes y adjuntos"]
    M --> V
    J --> D["Descargador y clientes de fuente"]
    B["Chrome: Eloísa, Exalab y Rayen"] -. "sesión temporal" .-> D
    K["Sesión propia: Syslab, HIS y MMRAD"] -.-> D
    D --> E["API JSON: Eloísa y Rayen<br/>Adjuntos Eloísa: PDF original desde Azure"]
    D --> H["HTTP: Syslab, Exalab, HIS y MMRAD"]
    E --> V["Verificar identidad, fecha, episodio e integridad"]
    H --> V
    X["Documentos existentes"] --> V
    V --> L["Trabajo local: OUTPUT/RUT/fuente + .avance"]
    L --> O["Originales y copias de trabajo identificadas"]
    L -. "si se solicita" .-> P["Resumen, formulario o consolidado"]
    L --> T["Cierre obligatorio: respuesta + TXT [X] / [~] / [ ]"]
    T --> A
    O --> A["Copiar al expediente por nombre"]
    P --> A
    A --> G["Archivos Mac mini / Pacientes / Nombre completo"]
    G --> C["Copia SHA-256 + ruta/tamaño/checksum remoto en Drive"]
    C -. "sin acceso autorizado" .-> PEND["Copia conservada; sincronización pendiente"]
    D -. "fallo o descarga parcial" .-> N["Conservar lo verificado; registrar pendientes"]
    V -. "discrepancia" .-> Q["Separar documento pendiente de revisión"]
    N -. "tras recuperar acceso" .-> D
```

- **Área local:** `.trabajos/cola.json` conserva solicitudes, historial y estados; las sesiones permanecen en memoria o llavero. Cancelar conserva los documentos íntegros; al reiniciar se reconstruye el avance y se solicita acceso solo para fuentes pendientes. las rutas técnicas por RUT y `.avance/ID/originales/RUT/fuente/` permiten reanudar y preservar originales. El RUT identifica registros; no da nombre al expediente de Drive. Procesar primero documentos y después imágenes. Conservar DICOM obtenidos además del PDF derivado.
- **Expediente en Drive:** resúmenes, formularios y estado de descargas en `Pacientes/Nombre completo/`; fuentes bajo `Fuentes primarias/`, separadas por origen. Agendas e índices globales van a `Documentos generales/`. Crear solo categorías necesarias. El [archivo por paciente](../../eloisa-archivo-drive/SKILL.md) mantiene el árbol exacto, la ruta local del escritorio, la cuenta y los criterios de copia/verificación.
- **Sesiones:** transferir tokens/cookies por el mecanismo temporal previsto por cada cliente; no copiarlos al expediente ni a registros. Los estados técnicos de reanudación y cachés permanecen locales.
- **Continuidad:** una fuente parcial no invalida los documentos completos de esa fuente ni de las otras. Un error de acceso no equivale a ausencia de registros. En Eloísa, ante actividad inusual, intentar una vez el inicio autorizado, obtener una sesión nueva y reanudar; si persiste un bloqueo/desafío, dejarlo pendiente. Ver [acceso y continuidad](../../laboratorios-descargas/references/continuidad.md).
- **Cierre:** resumen numerado de siete fuentes en respuesta y TXT, incluso sin documento adicional; distinguir documentos obtenidos, cobertura del período y sincronización. La presencia de un archivo en la carpeta local no acredita su subida a la nube.

## Mantenimiento del mapa

Al cambiar fuentes, autenticación, responsabilidades o destinos, actualizar estos Mermaid y las imágenes/PDF enlazados desde `SKILL.md`. Mantener los detalles operativos en sus referencias de origen y usar ejemplos sin pacientes reales. Estos esquemas documentan Codex y el lanzador local. La cola funciona mientras el lanzador está abierto; abrirlo recupera trabajos pendientes. No crean tareas programadas.
