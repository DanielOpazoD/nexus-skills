---
name: eloisa-resultados
description: Seleccionar pacientes desde la agenda por fecha y buscar atenciones clínicas de Rayen/Eloísa por RUT y período en Hospital Hanga Roa y obtener copias de trabajo y PDF adjuntos originales verificables.
---

# Atenciones Eloísa

Aplicar el [contrato común](../laboratorios-descargas/references/verificacion.md) y ejecutar con [laboratorios-descargas](../laboratorios-descargas/SKILL.md), también para un paciente. El contrato define identidad, entrega parcial, reporte y archivo.

Portal: `https://clinicohangaroa.eloisa.cl/`. Chrome personal `d.opazo.damiani@gmail.com`, ubicación `Hangaroa`; usar autocompletado autorizado sin extraer contraseñas.

- Entrada: RUT con dígito verificador; fuente `eloisa`. `--eloisa-scope medicos|todos`; usar `todos` para todas las atenciones y declarar cualquier filtro médico.
- Modo preferido: **API JSON** mediante el cliente y puente existentes; Chrome para autenticar/renovar sesión o contrastar la ficha.
- [Cliente](scripts/eloisa_download.py): `UsuarioApsRut` en nodo Hanga Roa → `HistorialAtencion`; fecha clínica `FechaCita` cuando existe. Verificar RUT del maestro y de cada atención antes de generar PDF.
- Salida de evoluciones: **copia de trabajo generada**, con identificación, fecha, prestadores y secciones devueltas. Adjuntos: **PDF original**, separado de esas copias. Contrastar dudas con la ficha del portal. Nunca consolidar personas distintas.
- Sesión: el puente unificado obtiene `userSession.accessToken` de la pestaña autenticada y lo pasa por stdin. Usar solo CDP documentado/disponible; no imprimir ni guardar el token. Para Eloísa sola: `{eloisa: tabEloisa}`; añadir `exalab` solo si está seleccionado. Aplicar la recuperación de sesión indicada abajo.

Consulta real cotejada el 19/10/2026: el modo acotado de seis meses coincidió en IDs y contenido con la búsqueda histórica para el paciente autorizado. Usa el período solicitado en la API; `latest` conserva búsqueda amplia. `--eloisa-full-history` permite cotejo diagnóstico sin cambiar el período final. Una comparación no demuestra cobertura universal ni velocidad constante. Referencia de implementación: [rayen-extension](https://github.com/DanielOpazoD/rayen-extension).

## Seleccionar pacientes desde agenda

El selector «Desde agenda» funciona en **Air y Mini**, cada uno con su sesión de Eloísa. Consultar un día de **Mi agenda** (prestador autenticado), mostrar nombre/RUT/hora/estado y agregar solo pacientes marcados al formulario. No inicia descargas. Fecha de agenda y período documental son independientes. Reglas, contrato y límites en [agenda](references/agenda.md).

## Contenidos

`sourceContent.eloisa` / `--source-content`: `medical` (evoluciones médicas), `other` (otros profesionales), `prescriptions` (recetas/prescripciones), `referrals` (interconsultas/derivaciones), `attachments` (documentos adjuntos). El formulario parte con **medical + prescriptions + referrals + attachments**. Una selección explícita reemplaza el corte por `eloisaScope`; sin ese campo se conserva el comportamiento anterior.

Recetas e interconsultas se seleccionan independientemente del profesional, sin incluir su evolución si no se pidió. El filtro actúa sobre categorías estructuradas, no elimina menciones dentro de una evolución elegida. La clasificación profesional sigue los instrumentos/tipo de atención: una profesión desconocida o mixta deja la evolución pendiente de revisión, conservando recetas/interconsultas solicitadas. Los PDF declaran el contenido elegido; cambiarlo exige otra solicitud, no reusar un avance incompatible.

## Documentos adjuntos

`attachments` enumera `ArchivosAdjunto` de las atenciones del paciente y período, independientemente de la selección de evoluciones/profesión. Descargar los PDF originales con el [cliente de adjuntos](scripts/eloisa_attachments.py); no basta imprimir su nombre dentro de una evolución. Los informes de ecocardiograma se buscan aquí: MMRAD contiene sus imágenes, excluidas por preferencia del usuario.

Vincular maestro RUT/IdUsuario → atención → adjunto; comprobar nombre y RUT del encabezado del PDF y el ID de atención si está impreso. No exigir que la fecha del informe sea la de su carga: el período se aplica a la atención. Un adjunto ilegible, sin identidad reconocible, no PDF o no descargable queda pendiente; conservar evoluciones y otras fuentes. Los originales no se reescriben ni desaparecen al agrupar PDF. Guardarlos en `Atenciones Eloisa/Documentos adjuntos/`. Detalles, límites y formato comprobado en [adjuntos](references/adjuntos.md).

## Recuperar sesión: actividad anormal/inusual

El usuario informó que entrar a Eloísa desde otro computador puede cerrar la sesión del Mac mini y mostrar “actividad anormal” o “actividad inusual”. Ante ese aviso, cierre de sesión, retorno al login o token vencido, tratar primero el caso como sesión invalidada; no como ausencia de atenciones ni como contraseña incorrecta sin evidencia.

1. Conservar documentos y `avance.json`. Volver al login de Eloísa en el perfil personal del equipo que está consultando (Air o Mini), seleccionar `Hangaroa` cuando corresponda y enviar el formulario con el autocompletado autorizado. **No pedir permiso de nuevo para este inicio de sesión ni extraer la contraseña.**
2. Comprobar acceso autenticado real; obtener una sesión nueva mediante el puente disponible y reanudar con el avance original. Reutilizar documentos verificados y comprobar otra vez la identidad del paciente al retomar. No seguir enviando el token inválido.
3. Si un nuevo inicio no permite acceder o reaparece el aviso, detener el bucle de reintentos. Si falta autocompletado, hay CAPTCHA, segundo factor o bloqueo persistente, dejar la pantalla para intervención del usuario y comunicar el paso concreto. Continuar las demás fuentes autorizadas y entregar lo verificado.

Este aviso es una señal para intentar reautenticación, no una certeza sobre su causa. No desactivar controles de seguridad ni borrar perfiles/cookies para evitarlo.

Al cerrar la orden, incluir el [resumen numerado de fuentes](../laboratorios-descargas/references/cierre-fuentes.md) en respuesta y TXT, también si esta es la única fuente o queda parcial. No consultar fuentes adicionales para completar ese bloque.
