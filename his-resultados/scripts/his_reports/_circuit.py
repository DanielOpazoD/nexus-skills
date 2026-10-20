"""Circuit breaker para llamadas al HIS.

Cuando el HIS se cae completamente, los reintentos del cliente HTTP
multiplican la carga sobre un upstream ya degradado:

    request del frontend → fetch_his
      → _single_fetch (intento 1) → URLError
      → backoff 0.5s
      → _single_fetch (intento 2) → URLError
      → backoff 1s
      → _single_fetch (intento 3) → URLError
      → 502 sintético

Si llegan 50 búsquedas en cola con el HIS muerto, son **150 calls** que
no sirven a nadie. Este breaker corta el ciclo: después de M fallos
consecutivos, responde 503 sin tocar al HIS por T segundos.

Estados:

    closed     (normal): cada call va al HIS.
                Transición → `open` si los últimos M intentos fallaron.

    open       (HIS caído): cada call retorna 503 sin pegar al HIS.
                Transición → `half_open` cuando pasa T segundos en `open`.

    half_open  (recovery): la PRÓXIMA call va al HIS como sonda.
                Transición → `closed` si la sonda responde OK.
                Transición → `open` si la sonda falla (otros T segundos).

Thread safety: el server es `ThreadingHTTPServer`, varias requests
pueden chequear/registrar concurrentemente. Un `threading.Lock` protege
las transiciones; los reads no toman lock (consistencia eventual está
bien para un fallback heurístico).

Diseño:
  - Singleton lazy por proceso (`get_breaker()`), igual que `Session`.
  - Función de tiempo inyectable para tests (`now=time.monotonic` por default).
  - No depende de `Session` ni de `http_client` — vive aislado y se
    consume desde `fetch_his`.

No es un Hystrix completo: no hay rolling window, no hay porcentaje de
fallos como umbral, no hay bulkheads. Es lo mínimo útil — un contador
con reset.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Literal

from .config import (
    HIS_CIRCUIT_FAILURE_THRESHOLD,
    HIS_CIRCUIT_OPEN_SECONDS,
)

log = logging.getLogger(__name__)

CircuitState = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    """Breaker simple consecutive-failure. Ver docstring del módulo."""

    def __init__(
        self,
        failure_threshold: int = HIS_CIRCUIT_FAILURE_THRESHOLD,
        open_seconds: float = HIS_CIRCUIT_OPEN_SECONDS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self._now = now
        self._lock = threading.Lock()
        self._state: CircuitState = "closed"
        # Contador de fallos consecutivos. Se incrementa con cada fallo;
        # se resetea con un éxito o cuando el breaker cierra de nuevo.
        self._consecutive_failures = 0
        # Timestamp de cuando el breaker se abrió. Solo significativo en
        # estado `open` — se compara con `now()` para decidir si pasamos
        # a `half_open`.
        self._opened_at: float = 0.0

    @property
    def state(self) -> CircuitState:
        """Estado actual. Lectura sin lock — consistencia eventual."""
        return self._state

    def allow(self) -> bool:
        """True si la call puede proceder al HIS; False si está abierto.

        Side effect: si el breaker estaba en `open` y pasó el tiempo de
        recovery, transiciona a `half_open` y retorna `True` (deja pasar
        la sonda). Por eso necesita lock — dos hilos no pueden ambos
        creer ser la sonda.
        """
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                elapsed = self._now() - self._opened_at
                if elapsed >= self.open_seconds:
                    self._state = "half_open"
                    log.info("circuit: open → half_open (sonda autorizada)")
                    return True
                return False
            # half_open: la primera call pasa, las siguientes esperan
            # el resultado de la sonda. Estrictamente, esto deja pasar
            # más de una si llegan en paralelo antes que se registre
            # el outcome — aceptable; el peor caso es 2-3 sondas
            # simultáneas que casi siempre dan el mismo resultado.
            return True

    def record_success(self) -> None:
        """Registra una call exitosa. Cierra el breaker si estaba
        recuperándose."""
        with self._lock:
            if self._state in ("open", "half_open"):
                log.info("circuit: %s → closed (recovery exitoso)", self._state)
            self._state = "closed"
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Registra un fallo. Abre el breaker si supera el umbral."""
        with self._lock:
            self._consecutive_failures += 1
            if self._state == "half_open":
                # Sonda falló → volver a abrir con timer fresco.
                self._state = "open"
                self._opened_at = self._now()
                log.warning("circuit: half_open → open (sonda falló, "
                             "%d fallos consecutivos)",
                             self._consecutive_failures)
                return
            if (self._state == "closed"
                    and self._consecutive_failures >= self.failure_threshold):
                self._state = "open"
                self._opened_at = self._now()
                log.warning("circuit: closed → open (%d fallos consecutivos "
                             "≥ %d umbral, %ds de bloqueo)",
                             self._consecutive_failures,
                             self.failure_threshold,
                             int(self.open_seconds))

    def reset(self) -> None:
        """Fuerza estado `closed`. Para tests y para un futuro endpoint
        de admin que quiera limpiar manualmente."""
        with self._lock:
            self._state = "closed"
            self._consecutive_failures = 0
            self._opened_at = 0.0


_default: CircuitBreaker | None = None


def get_breaker() -> CircuitBreaker:
    """Singleton lazy por proceso. La lazy-construction evita efectos al
    importar (consistente con `get_session()` en `session.py`)."""
    global _default
    if _default is None:
        _default = CircuitBreaker()
    return _default


def reset_default_breaker() -> None:
    """Recrea el singleton — para tests que necesitan aislamiento
    (ej. `setUp` que arranca con breaker fresh)."""
    global _default
    _default = CircuitBreaker()
