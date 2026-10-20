"""Caches en memoria. Thread-safe, TTL simple.

Casos actuales:
  - `Session.servicios_cache` — catálogo de especialidades (TTL 10min).
    Raramente cambia (meses), pero se pide cada vez que abrís el
    selector → una request al HIS. Cache elimina flicker + tráfico.
  - `probes._HEALTHZ_PROBE_CACHE` — resultado de la sonda al HIS para
    healthz (TTL 5s). Evita martillar el HIS con pollers externos.

Este módulo solo define la clase `TTLCache[T]`. Las instancias concretas
viven cerca de donde se usan — en `Session` las de sesión, como módulo-
local las de proceso. Así se limpian juntas con su dueño (logout limpia
las de sesión; el healthz cache persiste entre logins, que es correcto
porque la reachability del HIS no depende de la sesión).

Alcance deliberadamente acotado: solo un valor por cache, sin keys. Si
aparece un caso que requiere cachear múltiples entradas por key (ej.
fichas por id), el patrón sería agregar una clase hermana `KeyedTTLCache`
con `get(key)` / `set(key, value)` — no generalizar ésta. Hacerlo ahora
serían ~50 líneas de código speculativo sin callers reales.

Tipado: `TTLCache[T]` parametriza el valor cacheado, eliminando `Any`
en los call sites. `get()` devuelve `T | None` (None = vacío/expirado,
no "miss" diferenciado — el caller trata ambos casos igual).
"""
from __future__ import annotations

import threading
import time
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Cache con un único valor (no key-based). Thread-safe.

    Parametrizar con el tipo concreto al instanciar:

        cache: TTLCache[list[Servicio]] = TTLCache(600.0)
        cache.set([...])
        items = cache.get()  # list[Servicio] | None
    """

    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._value: T | None = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def get(self) -> T | None:
        with self._lock:
            if self._value is None or time.monotonic() > self._expires_at:
                return None
            return self._value

    def set(self, value: T) -> None:
        with self._lock:
            self._value = value
            self._expires_at = time.monotonic() + self._ttl

    def invalidate(self) -> None:
        with self._lock:
            self._value = None
            self._expires_at = 0.0
