"""Observabilidad mínima sin dependencias externas.

Objetivos modestos y muy concretos:

1. **Request-id** — cada request HTTP recibe un id corto (8 hex) que se
   propaga vía `ContextVar`. Todos los logs durante esa request lo
   llevan prefijado, para que puedas seguir una request entre líneas de
   log al debuggear (sobre todo en sesiones concurrentes).

2. **Timings** — `track_request(path)` es un context manager que mide
   wall-clock y cuenta status en un contador global. `metrics_snapshot()`
   devuelve una vista de los contadores para `/api/healthz`.

3. **Filtro de logging** — inyecta `req_id` en los `LogRecord`, con un
   formatter compatible que lo renderiza como `[rid]`. Si no hay request
   activa (logs del arranque del server, errores al inicio, etc.), sale
   `[----]`.

Sin dependencias — todo stdlib: `contextvars`, `threading.Lock`, `secrets`,
`time.monotonic`.
"""
from __future__ import annotations

import contextlib
import logging
import secrets
import threading
import time
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

# --------- request-id ---------

_REQ_ID: ContextVar[str] = ContextVar("req_id", default="")


def new_req_id() -> str:
    """8 hex characters — suficiente para distinguir requests en un proceso.
    No es un UUID; no pretende ser globalmente único."""
    return secrets.token_hex(4)


def set_req_id(rid: str) -> None:
    _REQ_ID.set(rid)


def get_req_id() -> str:
    return _REQ_ID.get()


# --------- contadores ---------

# Estructura: counters[path][status_bucket] = count
#   status_bucket: "2xx" | "4xx" | "5xx" | "err"
# Lock simple — el server es Threading, podríamos tener contención bajo
# carga alta pero en la práctica nunca la vamos a ver (uso local, pocos
# usuarios simultáneos).
_COUNTERS_LOCK = threading.Lock()
_COUNTERS: dict[str, dict[str, int]] = {}
# Latencias acumuladas por path, en segundos. Usamos max+suma+count para
# calcular avg sin guardar todos los samples. El p95 real no lo tenemos;
# para eso ya pediríamos prometheus. Con avg/max basta para health.
_LATENCIES: dict[str, dict[str, float]] = {}


def _bucket(status: int) -> str:
    if status >= 500:
        return "5xx"
    if status >= 400:
        return "4xx"
    if status >= 200:
        return "2xx"
    return "err"


def _record(path: str, status: int, elapsed: float) -> None:
    bucket = _bucket(status)
    with _COUNTERS_LOCK:
        row = _COUNTERS.setdefault(path, {})
        row[bucket] = row.get(bucket, 0) + 1
        lat = _LATENCIES.setdefault(path, {"sum": 0.0, "max": 0.0, "n": 0})
        lat["sum"] += elapsed
        lat["max"] = max(lat["max"], elapsed)
        lat["n"] += 1


@contextlib.contextmanager
def track_request(path: str) -> Iterator[dict[str, Any]]:
    """Timing + conteo automático. El caller debe asignar `ctx['status']`
    antes de salir del `with`; si no, se cuenta como `err`.

    Ejemplo:
        with track_request("/api/atenciones") as ctx:
            ctx["status"] = 200  # asignado tras responder
    """
    t0 = time.monotonic()
    ctx: dict[str, Any] = {"status": 0}
    try:
        yield ctx
    finally:
        elapsed = time.monotonic() - t0
        status = int(ctx.get("status") or 0)
        _record(path, status, elapsed)


def metrics_snapshot() -> dict[str, Any]:
    """Vista estática de los contadores. Usado por `/api/healthz`.

    Formato:
        {
          "routes": {
            "/api/atenciones": {
              "count": {"2xx": 12, "4xx": 1, "5xx": 0},
              "latency": {"avg": 0.12, "max": 0.45, "n": 13}
            },
            ...
          },
          "req_id_current": "a1b2c3d4"
        }
    """
    with _COUNTERS_LOCK:
        routes: dict[str, dict[str, Any]] = {}
        for path, counts in _COUNTERS.items():
            lat = _LATENCIES.get(path, {"sum": 0.0, "max": 0.0, "n": 0})
            avg = (lat["sum"] / lat["n"]) if lat["n"] else 0.0
            routes[path] = {
                "count": dict(counts),
                "latency": {
                    "avg": round(avg, 3),
                    "max": round(lat["max"], 3),
                    "n": int(lat["n"]),
                },
            }
    return {"routes": routes, "req_id_current": get_req_id() or None}


def reset_metrics() -> None:
    """Utilidad para tests. No la llames en producción sin razón."""
    with _COUNTERS_LOCK:
        _COUNTERS.clear()
        _LATENCIES.clear()


# --------- logging ---------

class _ReqIdFilter(logging.Filter):
    """Inyecta `req_id` en todos los LogRecord (4 chars, o '----')."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = _REQ_ID.get()
        record.req_id = rid if rid else "----"
        return True


def install_logging(level: int = logging.INFO) -> None:
    """Configura logging global con formato que incluye req_id.

    Idempotente — instalado dos veces no duplica handlers. Pensado para
    llamarse una vez desde `app.main()`.
    """
    root = logging.getLogger()
    # Evitar duplicar handlers si se llama más de una vez (ej. tests).
    for h in list(root.handlers):
        if getattr(h, "_his_reports_observability", False):
            return

    handler = logging.StreamHandler()
    handler._his_reports_observability = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(req_id)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    ))
    handler.addFilter(_ReqIdFilter())
    root.addHandler(handler)
    root.setLevel(level)
