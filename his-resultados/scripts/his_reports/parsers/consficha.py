"""Parser de `/hishhr/consficha000.php` — historial por RUT.

Columnas de la tabla de resultados:
  0: Fecha de Atención (DD-MM-YYYY)
  1: Tipo de Atención
  2: Servicio
  3: Ver Documento (link)

El link varía según el tipo de episodio:
  - Urgencia   → `PURG0005.php?id=NNN&noprint=1`
  - Ambulatorio → `PAMB0005.php?id=NNN&noprint=1`

Guardamos `tipoFicha` en la salida para que el frontend pida la ficha
correcta en /api/atencion.
"""
from __future__ import annotations

import re

from ..types import AtencionRow
from ._common import clean_cell, decode_html, iter_cells, iter_rows, iter_tables

_LINK_RE = re.compile(r"(PURG0005|PAMB0005)\.php\?id=(\d+)", re.IGNORECASE)
_FECHA_DMY_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")


def parse_consficha_resultados(html: bytes, rut: str = "") -> list[AtencionRow]:
    """Parsea la tabla de historial de un paciente. `rut` se propaga a cada fila.

    Busca la tabla cuyo encabezado contiene "fecha de atenci" (case-insensitive).
    Filas sin link a ficha se descartan porque no son abribles.
    """
    s = decode_html(html)
    out: list[AtencionRow] = []
    for tbl in iter_tables(s):
        if "fecha de atenci" not in tbl.lower():
            continue
        rows = list(iter_rows(tbl))
        for row in rows[1:]:  # skip header row
            cells = iter_cells(row)
            if len(cells) < 3:
                continue

            def get(i: int, cells: list[str] = cells) -> str:
                # `cells=cells` fija el binding por iteración (evita B023).
                return clean_cell(cells[i]) if i < len(cells) else ""

            fecha_raw = get(0)
            m = _FECHA_DMY_RE.match(fecha_raw)
            fecha_iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else fecha_raw
            tipo = get(1)
            servicio = get(2)

            link = _LINK_RE.search(row)
            if not link:
                continue
            tipo_ficha = "ambulatorio" if link.group(1).upper() == "PAMB0005" else "urgencia"
            out.append({
                "idCuenta": link.group(2),
                "tipoFicha": tipo_ficha,
                "ctacte": link.group(2),
                "rut": rut,
                "fecha": fecha_iso,
                "hora": "",
                "tipoAtencion": tipo,
                "servicio": servicio,
                "destino": "",
                "nombre": "",
                "medico": "",
                "diagnostico": "",
                "ficha": "",
            })
        break  # solo la primera tabla que matchea
    return out
