"""Parser de `/hishhr/ateurg023.php` — listado cross-usuario de atenciones.

Formato confirmado 2026-04: una tabla con 11 columnas por fila.
  0: DAU (numérico)       1: CTACTE          2: RUT
  3: HC                   4: PACIENTE        5: NOMBRE_SOCIAL
  6: FECHA_LLEGADA        7: DERIVA (svc)    8: (vacía / link "ver")
  9: HOSPITALIZACIÓN      10: ANULAR

El link a la ficha imprimible está embebido en la fila como
`PURG0005.php?id=CTACTE`. `ateurg023` solo produce links de urgencia
(DAU); los ambulatorios entran por `parsers.consficha`.
"""
from __future__ import annotations

import re

from ..types import AtencionRow
from ._common import clean_cell, decode_html, iter_cells, iter_rows

_LINK_RE = re.compile(r"(PURG0005|PAMB0005)\.php\?id=(\d+)", re.IGNORECASE)
_FECHA_HORA_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T]?(\d{2}:\d{2}(?::\d{2})?)?")


def _tipo_ficha_from_row(row_html: str) -> str:
    """Detecta si el link es de urgencia (PURG0005) o ambulatorio (PAMB0005)."""
    m = _LINK_RE.search(row_html)
    if not m:
        return ""
    return "ambulatorio" if m.group(1).upper() == "PAMB0005" else "urgencia"


def parse_atenciones_023(html: bytes) -> list[AtencionRow]:
    """Parsea la tabla del listado y devuelve una lista de atenciones.

    Filtros aplicados:
      - Fila debe tener ≥9 celdas (descarta tablas de layout).
      - Celda 0 debe ser numérica con ≥3 dígitos (descarta headers de <th>).
    """
    out: list[AtencionRow] = []
    s = decode_html(html)
    for row in iter_rows(s):
        cells = iter_cells(row)
        if len(cells) < 9:
            continue
        raw0 = clean_cell(cells[0])
        if not raw0.isdigit() or len(raw0) < 3:
            continue

        def get(i: int, cells: list[str] = cells) -> str:
            # `cells=cells` fija el binding por iteración (evita B023).
            return clean_cell(cells[i]) if i < len(cells) else ""

        ctacte = get(1)
        fecha_hora = get(6)
        fecha, hora = "", ""
        m = _FECHA_HORA_RE.match(fecha_hora)
        if m:
            fecha = m.group(1)
            hora = (m.group(2) or "")[:5]

        link_m = _LINK_RE.search(row)
        ficha_id = link_m.group(2) if link_m else ctacte
        tipo = _tipo_ficha_from_row(row) or "urgencia"

        item: AtencionRow = {
            "idCuenta": ficha_id,
            "tipoFicha": tipo,                 # "urgencia" | "ambulatorio"
            "dau": get(0),
            "ctacte": ctacte,
            "rut": get(2),
            "hc": get(3),
            "nombre": get(4),
            "nombreSocial": get(5),
            "fecha": fecha or fecha_hora,
            "hora": hora,
            "tipoAtencion": get(7),            # p.ej. "MÉDICO GENERAL"
            "servicio": get(7),                # alias para la UI
            "hospitalizacion": get(9),
            "destino": get(9) or "",
            "diagnostico": "",                 # solo viene en la ficha
            "medico": "",
            "ficha": get(3),
        }
        if item["rut"] or item["nombre"]:
            out.append(item)
    return out
