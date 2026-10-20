"""Parsers de HTML del HIS Hanga Roa.

Todos puros (`bytes` → `dict` o `list[dict]`), sin side-effects ni red.
Eso los hace trivialmente testeables con fixtures HTML capturadas.
"""
from .atenciones import parse_atenciones_023
from .consficha import parse_consficha_resultados
from .ficha import count_pairs, parse_ficha_purg
from .reporte_amb import parse_reporte_atenciones_amb
from .servicios import parse_servicios

__all__ = [
    "count_pairs",
    "parse_atenciones_023",
    "parse_consficha_resultados",
    "parse_ficha_purg",
    "parse_reporte_atenciones_amb",
    "parse_servicios",
]
