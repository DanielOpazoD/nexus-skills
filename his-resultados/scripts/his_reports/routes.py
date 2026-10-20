"""Tablas de rutas de la API JSON.

Antes esto vivía adentro de `handler.py`. El problema: `handler.py` también
hace HTTP mechanics (estáticos, proxy, serialización JSON, body reading) y
mezclar "qué endpoint maneja /api/foo" con "cómo se lee un Content-Length"
empezaba a crecer como una sola responsabilidad falsa.

Separar los routes en su propio módulo tiene dos ganancias:

  1. **Agregar un endpoint queda aislado**: edit this file + implement en
     `api.py`. No hay que leer la mecánica HTTP de handler.py para
     entender cómo conectar la ruta.

  2. **Tests estructurales son un import limpio**: `test_dispatch_tables`
     solo necesita `GET_ROUTES` / `POST_ROUTES`, sin arrastrar el
     `Handler` con toda la superficie de BaseHTTPRequestHandler.

Contrato `Endpoint`: todos los endpoints tienen la misma firma
`(q, body) → (status, dict)` aunque algunos ignoren `q` o `body`. Las
lambdas adaptan las funciones de `api.py` (cada una con su firma real)
a esta forma uniforme para que el dispatch del handler sea un dict lookup.

Si agregás un endpoint que necesita ambas cosas (ej. query string +
body) simplemente `lambda q, b: api.nuevo(q, b)` — la uniformidad de la
firma hace que no haya casos especiales en `_dispatch_api`.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import api

# Firma uniforme de un endpoint JSON. Recibe query parseada
# (`{key: [values]}` de `parse_qs`) y body raw; devuelve
# `(status HTTP, payload JSON-serializable)`.
#
# Los endpoints reales en `api.py` tienen firmas heterogéneas (`status()`
# no toma nada, `atenciones(q)` toma query, `login(b)` toma body). Las
# lambdas en las tablas debajo hacen el shim para que el handler pueda
# tratar todo uniformemente.
Endpoint = Callable[[dict[str, list[str]], bytes], tuple[int, dict[str, Any]]]


GET_ROUTES: dict[str, Endpoint] = {
    "/api/status":             lambda q, b: api.status(),
    "/api/healthz":            lambda q, b: api.healthz(),
    "/api/servicios":          lambda q, b: api.servicios(),
    "/api/atenciones":         lambda q, b: api.atenciones(q),
    "/api/atenciones-por-rut": lambda q, b: api.atenciones_por_rut(q),
    "/api/atencion":           lambda q, b: api.atencion(q),
    # `/api/_diag/*` — endpoints de diagnóstico, no consumidos por el
    # frontend. El prefijo `_diag` señaliza "no es API estable".
    "/api/_diag/sync":         lambda q, b: api.diag_sync(),
}

POST_ROUTES: dict[str, Endpoint] = {
    "/api/login":  lambda q, b: api.login(b),
    "/api/logout": lambda q, b: api.logout(),
}
