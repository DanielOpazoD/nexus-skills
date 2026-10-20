"""Extracción de la tabla de signos vitales (solo urgencia).

PURG0005 (urgencia) incluye una tabla con SAT. O2, F.C., P. Sistólica, etc.
PAMB0005 (ambulatorio) NO trae esta tabla — la función devuelve `{}` y los
campos quedan vacíos; la UI los omite por su regla "no mostrar vacíos".

La heurística para identificar la tabla correcta: que su header contenga
tanto "SAT" como "O2". Evita confundirla con tablas de exámenes o
medicamentos que pueden aparecer en la misma ficha.
"""
from __future__ import annotations

import html as _html
import re


def _row_cells(row: str) -> list[str]:
    """Extrae celdas de una fila HTML, limpiando tags y entidades."""
    return [
        re.sub(r"\s+", " ",
               _html.unescape(re.sub(r"<[^>]+>|&nbsp;", " ", c))).strip()
        for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>",
                             row, re.IGNORECASE | re.DOTALL)
    ]


def extract_signos_vitales(html_str: str) -> dict[str, str]:
    """Busca la tabla cuyo header incluye SAT y O2, devuelve `{HEADER: VALOR}`.

    Formato esperado: 2 filas (header + datos). Si hay más, solo se lee la
    primera fila de datos. Si no hay tabla que matchee, devuelve `{}`.
    """
    sv: dict[str, str] = {}
    for tbl_m in re.finditer(r"<table[^>]*>(.*?)</table>", html_str,
                              re.IGNORECASE | re.DOTALL):
        tbl = tbl_m.group(1)
        if "SAT" not in tbl.upper() or "O2" not in tbl.upper():
            continue
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl,
                           re.IGNORECASE | re.DOTALL)
        if len(rows) < 2:
            continue

        headers = [h.upper() for h in _row_cells(rows[0])]
        if not any("SAT" in h for h in headers):
            continue
        data = _row_cells(rows[1])
        for i, h in enumerate(headers):
            if i < len(data):
                sv[h] = data[i]
        break
    return sv
