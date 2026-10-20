"""Sondas de reachability al HIS (process-level, cacheadas).

Antes esto vivía en `api.py` como `_HEALTHZ_PROBE_CACHE` + `_probe_his()`.
El problema: `api.py` orquesta endpoints — no debería dueño de un cache
module-level cuya vida es todo-el-proceso, no por-request. Mezclaba dos
capas y enterraba la razón de existir del cache (la sonda, no el endpoint).

Acá la sonda tiene su propio módulo porque su lifecycle es distinto al
resto:

  - Las caches de sesión viven dentro de `Session`, se limpian en logout.
  - La reachability del HIS es process-wide: no depende de qué usuario
    está conectado (ni siquiera de si hay alguien conectado). Un monitor
    externo pooleando `/api/healthz` cada segundo comparte el mismo cache
    entre todas las sesiones del proceso.

El TTL es corto (`HEALTHZ_CACHE_TTL`, default 5s) porque la sonda es
"¿hay red hacia el HIS?" — queremos responder rápido a una caída, pero
sin martillar al HIS. 5s dedupe pollers agresivos sin ocultar fallas
reales más de unos segundos.

API pública:
  - `probe_his()` → `(status, latency_ms, reachable)`, usando el cache.
  - `invalidate_probe_cache()` → fuerza próxima llamada a re-sondear.
    Usada por tests; no esperamos callers de producción.
"""
from __future__ import annotations

import time

from .cache import TTLCache
from .config import HEALTHZ_CACHE_TTL, LOGIN_ROOT
from .http_client import fetch_his

# `tuple[int, float, bool]` = (status HTTP, latencia ms, reachable?).
# Tupla plana en vez de dataclass porque son 3 campos primitivos y el
# único caller lo desempaqueta inmediatamente; una clase acá sería
# ceremony sin beneficio.
_HEALTHZ_PROBE_CACHE: TTLCache[tuple[int, float, bool]] = TTLCache(
    HEALTHZ_CACHE_TTL
)


def probe_his() -> tuple[int, float, bool]:
    """Sondea la reachability del HIS y cachea el resultado.

    Devuelve `(status, latency_ms, reachable)`:
      - `status`: código HTTP recibido, o 0 si la request falló antes de
        llegar (DNS, connection refused, etc.).
      - `latency_ms`: tiempo de la request redondeado a 0.1ms.
      - `reachable`: True si `status < 500` — "el HIS responde algo
        razonable". Un 401 o redirect a login cuentan como reachable
        (la red va, el HIS está vivo).

    Captura `Exception` (no `URLError` específico) porque queremos que
    healthz nunca crashee — un bug en `fetch_his` no debe tirar el
    endpoint que justamente existe para decir "algo anda mal".
    """
    cached = _HEALTHZ_PROBE_CACHE.get()
    if cached is not None:
        return cached
    t0 = time.monotonic()
    try:
        # LOGIN_ROOT es lightweight (no dispara warm-up ni nada).
        his_status, _, _ = fetch_his(LOGIN_ROOT)
        his_reachable = his_status < 500
    except Exception:
        his_status = 0
        his_reachable = False
    his_latency_ms = round((time.monotonic() - t0) * 1000, 1)
    result = (his_status, his_latency_ms, his_reachable)
    _HEALTHZ_PROBE_CACHE.set(result)
    return result


def invalidate_probe_cache() -> None:
    """Fuerza que la próxima `probe_his()` haga una sonda real al HIS.

    Usado por tests para aislamiento; no tiene caller de producción (el
    TTL natural se encarga). Si algún día aparece un "refresh manual" en
    la UI de monitoreo, este es el hook.
    """
    _HEALTHZ_PROBE_CACHE.invalidate()
