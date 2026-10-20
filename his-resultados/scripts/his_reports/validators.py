"""Validadores de input de los endpoints JSON.

Cada función devuelve un error legible (`str`) o `None` si el valor es
válido. Llamadas típicas:

    err = valid_iso_date(desde)
    if err:
        return HTTPStatus.BAD_REQUEST, {"error": err}

La idea es rechazar basura antes de llegar al HIS — evita requests que
sabemos que van a fallar y nos ahorra latencia + ruido en los logs. No
estamos haciendo validación "estricta" al nivel del HIS (que al final
tiene la verdad), solo filtrando errores obvios del cliente.

Contrato uniforme sobre valores vacíos:

  - Por default, **vacío → None** (tratado como "no se pasó, nada que
    validar"). El endpoint decide si ausencia es error antes de llamar.
  - Si el endpoint exige el valor, pasa `required=True` y el validador
    devuelve un mensaje de error sobre el vacío.

Este contrato elimina el patrón `validator(x) if x else None` que antes
ensuciaba los callers. Ver `api.atenciones` / `api.atencion` para ejemplos.
"""
from __future__ import annotations

import datetime
import re

# --------- fechas ---------

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_iso_date(v: str, *, field: str = "fecha") -> str | None:
    """Acepta `YYYY-MM-DD` parseable por `date.fromisoformat`.

    Vacío → None (no es un error — el endpoint decide si es opcional).
    """
    if not v:
        return None
    if not _ISO_RE.match(v):
        return f"{field} debe ser YYYY-MM-DD"
    try:
        datetime.date.fromisoformat(v)
    except ValueError:
        return f"{field} no es una fecha válida"
    return None


def valid_date_range(desde: str, hasta: str) -> str | None:
    """Si ambas están presentes, `desde` no puede ser posterior a `hasta`."""
    if not desde or not hasta:
        return None
    # Asumimos que ya pasaron por valid_iso_date.
    try:
        d = datetime.date.fromisoformat(desde)
        h = datetime.date.fromisoformat(hasta)
    except ValueError:
        return None  # ya se reportó antes
    if d > h:
        return "desde no puede ser posterior a hasta"
    return None


# --------- RUT chileno ---------

# Acepta: 12345678-9, 12.345.678-9, 12345678, 123456789 (sin sep)
_RUT_CLEAN_RE = re.compile(r"[.\-\s]")


def _rut_dv(num: int) -> str:
    """Calcula el DV del RUT chileno (módulo 11)."""
    total = 0
    mult = 2
    while num > 0:
        total += (num % 10) * mult
        num //= 10
        mult = 2 if mult == 7 else mult + 1
    r = 11 - (total % 11)
    if r == 11:
        return "0"
    if r == 10:
        return "K"
    return str(r)


def valid_rut(v: str, *, required: bool = False) -> str | None:
    """Valida un RUT chileno. Acepta formatos con/sin puntos y guión.

    Devuelve None si es válido o si está vacío y `required=False` (caso
    típico en filtros opcionales). Con `required=True` el vacío devuelve
    un mensaje de error.
    """
    if not v:
        return "rut requerido" if required else None
    cleaned = _RUT_CLEAN_RE.sub("", v).upper()
    if len(cleaned) < 2:
        return "rut demasiado corto"
    body, dv = cleaned[:-1], cleaned[-1]
    if not body.isdigit():
        return "rut inválido: cuerpo no numérico"
    if dv not in "0123456789K":
        return "rut inválido: dv debe ser 0-9 o K"
    # Rangos razonables — descarta 1-2 dígitos (probablemente un typo) y
    # >10 (no existe). El HIS aceptará cualquier cosa en este rango.
    if not (7 <= len(body) <= 9):
        return "rut inválido: cuerpo fuera de rango"
    expected = _rut_dv(int(body))
    if dv != expected:
        return "rut inválido: dígito verificador no coincide"
    return None


# --------- identificadores numéricos ---------

def valid_numeric_id(v: str, *, field: str = "id", min_len: int = 1,
                     max_len: int = 12,
                     required: bool = False) -> str | None:
    """id/ctacte/servicio: solo dígitos, longitud razonable.

    Con `required=False` (default), vacío → None. Con `required=True`,
    vacío devuelve el mensaje de requerido.
    """
    if not v:
        return f"{field} requerido" if required else None
    if not v.isdigit():
        return f"{field} debe ser numérico"
    if not (min_len <= len(v) <= max_len):
        return f"{field} fuera de rango"
    return None


# --------- fuentes enumeradas ---------

_FUENTES_VALIDAS = frozenset({"ambulatorio", "urgencia"})


def valid_fuente(v: str) -> str | None:
    """`fuente` del listado de atenciones. Si se pasa, debe ser uno de los
    valores conocidos; vacío → None (el endpoint usa su default)."""
    if not v:
        return None
    if v.lower() not in _FUENTES_VALIDAS:
        return f"fuente inválida (usa: {', '.join(sorted(_FUENTES_VALIDAS))})"
    return None
