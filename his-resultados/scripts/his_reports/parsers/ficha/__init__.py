"""Parser de PURG0005.php / PAMB0005.php — ficha imprimible.

Arquitectura en dos fases separadas en submódulos:

  · `_pairs.py`   → Fase 1: extrae el dict `{LABEL: VALUE}` del HTML.
  · `_medico.py`  → Helper: encuentra el médico con 3 estrategias.
  · `_signos.py`  → Helper: parsea la tabla de signos vitales (solo urgencia).
  · `_mapping.py` → Fase 2: traduce las labels a la estructura tipada del frontend.

El público de este paquete es:
  - `parse_ficha_purg(body)` → la estructura tipada completa.
  - `extract_pairs(body)`   → el dict crudo `{LABEL: VALUE}` (expuesto para tests).
  - `count_pairs(body)`     → estimación rápida de "¿este HTML es una ficha
    válida?" sin parsear todo. La usa la API para detectar fichas vacías
    (por ejemplo, cuando el HIS devuelve 200 con una página casi en blanco).
"""
import re

from ._mapping import parse_ficha_purg
from ._pairs import extract_pairs

# Detector heurístico de una ficha HIS: cuenta cuántos pares `<b>LABEL:</b>`
# aparecen en el body crudo. Una ficha real tiene decenas; una respuesta
# "vacía" (p. ej. ficha incorrecta o permisos) tiene 0-2.
_PAIR_COUNT_RE = re.compile(rb"<b>[^<:]{2,80}:</b>")


def count_pairs(body: bytes) -> int:
    """Cuenta pares `<b>LABEL:</b>` en el HTML crudo de una ficha.

    Útil para validar que una respuesta sea una ficha estructurada antes de
    gastar el parsing completo. Umbral práctico: `>= 5` indica ficha real.
    """
    return len(_PAIR_COUNT_RE.findall(body))


__all__ = ["count_pairs", "extract_pairs", "parse_ficha_purg"]
