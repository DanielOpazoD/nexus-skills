# Agenda de Eloísa — 19-10-2026

## Flujo

En Chrome, pulsar la extensión «Nexo · Consulta clínica» (antes «Puente local de descargas clínicas») versión 3 → **Desde agenda** → fecha → **Cargar agenda** → marcar uno, varios o todos → **Agregar seleccionados**. También está en el panel local. Cada equipo usa su propia sesión: no transmitir tokens entre Air y Mini. El HTML portátil abierto como archivo permite entrada manual; la agenda requiere la extensión o el panel con puente actualizado.

Esta versión consulta **Mi agenda**, identificada por el prestador autenticado y nodo Hanga Roa (5576). No permite seleccionar otro profesional. Si el usuario solicita otra agenda, no sustituirla silenciosamente por la propia. La fecha inicial se calcula en Pacific/Easter; mostrar y exportar DD-MM-AAAA. Se consulta un día, separado del período de antecedentes. Agregar pacientes conserva RUT manuales y opciones de fuentes/fechas/entrega; no encola ni consulta sus fichas. El pedido exportado conserva el contrato habitual y destino Mini.

## Contrato de lectura

Implementación: `laboratorios-descargas/assets/agenda_core.js`, `agenda_ui.js` y `chrome-bridge/agenda_worker.js`. El trabajador obtiene `userSession.accessToken` en la pestaña autenticada, identifica `nodo` y `funcionarioPrestador` (objetos o JSON serializado) y admite claves explícitas equivalentes. Rechazar identidad ausente/ambigua o nodo distinto; no usar IDs genéricos ni un profesional fijo. La sesión y su token no llegan al formulario, archivos ni Drive.

GET fijo de Eloísa: `/API/api/rayen/Citas/ListaPacientesCitados/{nodo}/{parámetros}`. Parámetros separados por punto y coma: FechaHoraInicio y FechaHoraTermino del mismo día (000000–235959), IdsDeRecursos del prestador, EsAnulado=2, EsGrupal=2, TraerLlamadosPaciente=true, TraerTeleconsulta=true. Patrón reutilizado de [rayen-extension](https://github.com/DanielOpazoD/rayen-extension). No usar un rango multidía: la referencia documenta que devuelve solo el primer día.

Solo devolver campos mínimos para elegir: RUT validado, nombre, horas, estados e IDs de cita. Verificar fecha exacta y las identidades de cita/paciente; cotejar prestador/nodo cuando estén disponibles. Duplicar la misma persona agrupa citas; homónimos con RUT distinto permanecen separados. Una contradicción de identidad o del mismo ID de cita bloquea ese grupo. Filas inválidas quedan pendientes y no eliminan las válidas. No preseleccionar pacientes; citas anuladas no se seleccionan. Máximo 200 pacientes por solicitud.

## Continuidad y privacidad

Sesión vencida o error ≠ agenda vacía. Reautenticar una vez según la skill del equipo; conservar la lista/selección previa de la misma fecha si falla una actualización. Cambiar fecha borra selección de agenda e invalida respuestas tardías, sin borrar los RUT ya agregados. La agenda vive solo en memoria de la página; cerrar/recargar descarta la lista. El trabajador limita tiempo, tamaño, origen y emisor, sin redirecciones con credenciales. Los datos recibidos se insertan con textContent; los scripts de la extensión son locales y externos conforme a [CSP Manifest V3](https://developer.chrome.com/docs/extensions/reference/manifest/content-security-policy).

## Verificación

Pruebas ficticias: contratos de sesión/fecha/identidad, homónimos, duplicados, anuladas, parciales, emisores no autorizados, sesión vencida, respuestas tardías, reintentos y selección sin ejecución. La consulta autorizada de Daniel Opazo del 20-10-2026 devolvió 9 citas de 9 pacientes distintos, con identidad completa, sin anuladas ni grupales y con prestador/nodo coincidentes, tras renovar la sesión. El selector pasó la prueba visual con datos ficticios y el conjunto pasó 203 pruebas. La versión 3 quedó copiada localmente; el usuario dejó para después recargar la extensión. Sigue pendiente verificar el recorrido completo con la extensión recargada y su instalación en el Air. La validación de una agenda no demuestra cobertura universal de citas grupales ni otros profesionales. No registrar datos identificatorios de pacientes en pruebas ni Git.
