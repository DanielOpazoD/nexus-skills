"""Parser de `/hishhr/reporte_atenciones_amb.php` — listado ambulatorio.

Este es el módulo correcto para "REPORTE ATENCIONES AMBULATORIAS Y ESTADO":
lo que el HIS muestra bajo AMBULATORIO → INFORME ATENCIONES. A diferencia de
`ateurg023` (urgencia/DAU), aquí SÍ viene la columna `MEDICO ATIENDE`, por lo
que el listado ya trae el nombre del profesional sin tener que abrir la ficha.

Columnas confirmadas 2026-04 (10 celdas):
  0: CTACTE         1: RUT           2: HC           3: PACIENTE
  4: FECHA CITA     5: SERVICIO      6: FECHA LLEGADA
  7: ESTADO         8: MEDICO ATIENDE   9: ATENCION (icono/link)

Formato de fecha: `DD-MM-YYYY HH:MM:SS` en FECHA CITA y FECHA LLEGADA.
Normalizamos a `fecha` ISO (`YYYY-MM-DD`) + `hora` `HH:MM` para que el
frontend pueda filtrar y ordenar sin reparsing.

El link a la ficha imprimible (`PAMB0005.php?id=CTACTE`) suele vivir en la
columna ATENCION como icono; si el HIS cambia y lo embebe en otra celda
también se detecta (busca en toda la fila).
"""
from __future__ import annotations

import re

from ..types import AtencionRow
from ._common import clean_cell, decode_html, iter_cells, iter_rows

# Acepta ambas fichas por si el HIS mezcla urgencia/ambulatorio en este listado
# (en los hospitales rurales a veces sí).
_LINK_RE = re.compile(r"(PAMB0005|PURG0005)\.php\?id=(\d+)", re.IGNORECASE)
_FECHA_DMY_RE = re.compile(
    r"(\d{2})-(\d{2})-(\d{4})(?:[ T]+(\d{2}:\d{2}(?::\d{2})?))?"
)


def _fecha_iso_hora(cell: str) -> tuple[str, str]:
    """`"10-04-2026 10:00:00"` → `("2026-04-10", "10:00")`.

    Si no matchea, devuelve `(cell, "")` — preservamos el valor crudo para no
    esconder parsing fallido detrás de strings vacíos.
    """
    m = _FECHA_DMY_RE.match(cell.strip())
    if not m:
        return cell, ""
    iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    hora = (m.group(4) or "")[:5]
    return iso, hora


def parse_reporte_atenciones_amb(html: bytes) -> list[AtencionRow]:
    """Parsea la tabla del listado ambulatorio.

    Filtros defensivos:
      - Fila debe tener ≥8 celdas (descarta filas de layout/paginación).
      - Celda 0 debe ser numérica (CTACTE) con ≥3 dígitos.
    Esto descarta filas de header `<th>` (texto "CTACTE") y totales.
    """
    out: list[AtencionRow] = []
    s = decode_html(html)
    for row in iter_rows(s):
        cells = iter_cells(row)
        if len(cells) < 8:
            continue

        def get(i: int, cells: list[str] = cells) -> str:
            # `cells=cells` fija el binding por iteración (evita B023).
            return clean_cell(cells[i]) if i < len(cells) else ""

        ctacte = get(0)
        if not ctacte.isdigit() or len(ctacte) < 3:
            continue

        fecha_cita, hora_cita = _fecha_iso_hora(get(4))
        fecha_llegada, hora_llegada = _fecha_iso_hora(get(6))

        link_m = _LINK_RE.search(row)
        ficha_id = link_m.group(2) if link_m else ctacte
        tipo = ("ambulatorio" if not link_m
                or link_m.group(1).upper() == "PAMB0005"
                else "urgencia")

        nombre = get(3)
        servicio = get(5)
        estado = get(7)
        medico = get(8)

        item: AtencionRow = {
            "idCuenta": ficha_id,
            "tipoFicha": tipo,
            "ctacte": ctacte,
            "rut": get(1),
            "hc": get(2),
            "nombre": nombre,
            # FECHA CITA es la fecha "planificada" — la UI la muestra como
            # fecha de la atención (más útil que llegada para listar por día).
            "fecha": fecha_cita,
            "hora": hora_cita,
            "fechaLlegada": fecha_llegada,
            "horaLlegada": hora_llegada,
            "servicio": servicio,
            "tipoAtencion": servicio,   # alias para la UI
            "estado": estado,
            "medico": medico,
            # Campos que rellena la ficha (no vienen en la tabla):
            "diagnostico": "",
            "destino": "",
            "hospitalizacion": "",
            "nombreSocial": "",
            "dau": "",
            "ficha": "",
        }
        if item["rut"] or item["nombre"] or item["ctacte"]:
            out.append(item)
    return out
