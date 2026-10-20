"""Extrae el catálogo de especialidades/servicios del HIS.

Fuente: `reporte_atenciones_amb.php` — form visible para todos los roles
(aunque el submit esté denegado para el rol internista). El `<select>`
relevante normalmente se llama `cboser` y sus options tienen como nombres
"URGENCIA", "MEDICINA INTERNA", "PEDIATRIA", etc.

**Dedupe por nombre**: el catálogo del HIS suele tener múltiples `<option>`
con el mismo nombre pero `value` distinto — p.ej. "AMB AGENDA PRÓTESIS
DENTAL FIJA" aparece 3-5 veces (una por agenda / box / profesional).
Desde la perspectiva del usuario (el médico) esas son la misma
"especialidad"; quiere filtrar por el nombre y obtener TODAS las
atenciones del grupo. Agrupamos los IDs con coma y el backend
`_fetch_por_servicios` ya hace fan-out paralelo cuando recibe
`servicio=1,2,3`, así que no hay cambio de contrato del API.
"""
from __future__ import annotations

import re

from ..types import Servicio
from ._common import decode_html

# Preferimos selects con name/id que contenga "servicio". Si no existe, cae
# al fallback: cualquier select cuyas options incluyan urgencia/medicina/
# pediatria (marcadores altamente específicos del catálogo real).
_SELECT_PREF_RE = re.compile(
    r'<select[^>]*(?:name|id)\s*=\s*["\']?servicio[^>]*>(.*?)</select>',
    re.IGNORECASE | re.DOTALL,
)
_SELECT_ANY_RE = re.compile(
    r"<select[^>]*>(.*?)</select>",
    re.IGNORECASE | re.DOTALL,
)
_HINT_RE = re.compile(r"medicina|urgen|pediatr", re.IGNORECASE)

_OPTION_RE = re.compile(
    r'<option[^>]*value\s*=\s*["\']?([^"\'>\s]+)["\']?[^>]*>(.*?)</option>',
    re.IGNORECASE | re.DOTALL,
)

# Cap defensivo: si un nombre tiene >20 IDs subyacentes, algo raro pasa
# (el HIS podría estar devolviendo el catálogo inflado). Evitar que el
# front dispare cientos de requests por una sola selección del usuario.
_MAX_IDS_POR_NOMBRE = 20


def parse_servicios(html: bytes) -> list[Servicio]:
    """Devuelve `[{id, nombre}, ...]` con las especialidades disponibles.

    - Salta placeholders como "-- Seleccione --" y opciones con valor vacío.
    - Agrupa opciones con el mismo nombre (normalizado: trim + collapse
      whitespace + case-insensitive) en un solo item. El `id` resultante
      es una lista de IDs separados por coma, en orden de aparición en
      el `<select>`. El nombre preservado es el de la primera ocurrencia
      (respeta capitalización del HIS).
    - Orden de salida: orden del primer `<option>` de cada grupo — así la
      UX del dropdown es estable (no cambia si el HIS reordena options
      duplicadas).
    """
    txt = decode_html(html)
    selects = _SELECT_PREF_RE.findall(txt)
    if not selects:
        selects = [s for s in _SELECT_ANY_RE.findall(txt) if _HINT_RE.search(s)]
    if not selects:
        return []
    # Agrupamos en un dict keyed por nombre normalizado. `groups[key]`
    # mantiene el nombre de display y la lista de IDs en orden.
    groups: dict[str, dict[str, object]] = {}
    for m in _OPTION_RE.finditer(selects[0]):
        val = m.group(1).strip()
        nom = re.sub(r"\s+", " ", m.group(2)).strip()
        if not val or val == "0" or re.search(r"seleccion", nom, re.IGNORECASE):
            continue
        key = nom.casefold()
        if not key:
            continue
        g = groups.get(key)
        if g is None:
            groups[key] = {"nombre": nom, "ids": [val]}
        else:
            ids_list = g["ids"]
            assert isinstance(ids_list, list)
            # Dedup de IDs dentro del mismo nombre (por si el HIS repite
            # literalmente el mismo value=N dos veces).
            if val not in ids_list and len(ids_list) < _MAX_IDS_POR_NOMBRE:
                ids_list.append(val)
    items: list[Servicio] = []
    for g in groups.values():
        ids = g["ids"]
        name = g["nombre"]
        assert isinstance(ids, list) and isinstance(name, str)
        items.append({"id": ",".join(ids), "nombre": name})
    return items
