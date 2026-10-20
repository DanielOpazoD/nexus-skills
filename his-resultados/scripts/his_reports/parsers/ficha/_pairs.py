"""Fase 1 del parsing de ficha: HTML → `{LABEL: valor}`.

El HIS expone la ficha con una estructura muy simple: pares
`<b>LABEL:</b><br>VALUE` dentro de divs. Este módulo se enfoca SOLO en
extraer ese dict — no sabe nada de médicos, signos vitales ni del
vocabulario del HIS. La fase 2 (`_mapping.py`) traduce las labels a la
forma tipada que espera el frontend.

Separar las dos fases permite testearlas independientemente: las sutilezas
de regex viven acá (bullets con `<br>`, cortes por `</div>`), mientras que
el mapeo es solo un diccionario de sinónimos.
"""
from __future__ import annotations

import html as _html
import re

# Etiqueta <b>TEXTO:</b> — 2-80 chars, sin colons ni tags internos.
_LABEL_RE = re.compile(r"<b>([^<:]{2,80}):</b>", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_MULTISPACE_RE = re.compile(r"[ \t]+")
# Comentarios HTML pueden contener literales tipo "<b>LABEL:</b>" que la
# regex de etiquetas capturaría por error. Los quitamos antes de parsear.
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def extract_pairs(html_str: str) -> dict[str, str]:
    """Extrae `{LABEL_UPPER: VALUE}` de un HTML con `<b>LABEL:</b>VALUE`.

    Reglas:
      - Label se uppercasea, se desescapa y se colapsa whitespace.
      - Valor va desde `</b>` hasta el mínimo entre el próximo `<b>LABEL:</b>`
        y el próximo `</div>`. Esto corta el valor justo donde termina su
        contenedor visual, evitando "pegar" el siguiente campo.
      - `<br>` internos → `\\n` (preserva bullets de INDICACIONES).
      - Strip-tags del resto (por si el HIS envuelve el valor en `<span>`
        o similares).
      - Primera ocurrencia gana (ignora labels duplicadas).

    El caller es responsable de pasar HTML ya saneado (sin comentarios).
    El mapper `parse_ficha_purg` lo hace antes de llamar.
    """
    matches = list(_LABEL_RE.finditer(html_str))
    pairs: dict[str, str] = {}
    for i, m in enumerate(matches):
        lbl = _html.unescape(m.group(1)).replace("\xa0", " ").strip().upper()
        lbl = re.sub(r"\s+", " ", lbl)
        value_start = m.end()
        next_b = matches[i + 1].start() if i + 1 < len(matches) else len(html_str)
        next_div = html_str.find("</div>", value_start)
        if next_div == -1:
            next_div = next_b
        value_end = min(next_b, next_div)
        raw = html_str[value_start:value_end]
        val = _BR_RE.sub("\n", raw)
        val = _TAG_RE.sub("", val)
        val = _html.unescape(val).replace("\xa0", " ")
        lines = [_MULTISPACE_RE.sub(" ", line).strip() for line in val.split("\n")]
        val = "\n".join(line for line in lines if line)
        if lbl not in pairs:
            pairs[lbl] = val
    return pairs
