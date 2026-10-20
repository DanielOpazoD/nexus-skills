"""Helpers compartidos por los parsers de tabla del HIS.

Centralizamos aquí las tres operaciones repetitivas que hacen todos los
parsers de tabla HIS:

  1. Decodificar bytes→str con fallback latin-1 implícito (errors="ignore").
  2. Extraer filas/celdas con regex (BeautifulSoup no está disponible —
     dependencia cero por política del proyecto).
  3. Limpiar texto de celda: quitar tags, `&nbsp;`, entidades, colapsar
     whitespace.
"""
from __future__ import annotations

import html as _html
import re
from collections.abc import Iterator

# RUT chileno normalizado con o sin puntos. Ej: 12345678-9 o 12.345.678-9.
RUT_RE = re.compile(r"(\d{1,2}\.?\d{3}\.?\d{3}-[\dkK])")

_TAG_RE = re.compile(r"<[^>]+>|&nbsp;")
_WS_RE = re.compile(r"\s+")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.IGNORECASE | re.DOTALL)
_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)


def decode_html(raw: bytes) -> str:
    """Decodifica bytes→str sin explotar ante bytes mal formados."""
    return raw.decode("utf-8", errors="ignore")


def clean_cell(raw: str) -> str:
    """Quita tags, `&nbsp;`, entidades y colapsa whitespace."""
    v = _TAG_RE.sub(" ", raw)
    v = _html.unescape(v)
    return _WS_RE.sub(" ", v).strip()


def iter_rows(html: str) -> Iterator[str]:
    """Itera filas `<tr>...</tr>` como strings (contenido interior)."""
    return (m.group(1) for m in _ROW_RE.finditer(html))


def iter_cells(row: str) -> list[str]:
    """Extrae las celdas `<td>` o `<th>` de una fila como HTML crudo.

    (No limpia: quien necesite texto plano pasa cada celda por `clean_cell`.)
    """
    return _CELL_RE.findall(row)


def iter_tables(html: str) -> Iterator[str]:
    """Itera tablas `<table>...</table>` como strings (contenido interior)."""
    return (m.group(1) for m in _TABLE_RE.finditer(html))
