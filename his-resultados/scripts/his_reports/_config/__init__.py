"""Configuración interna — dividida por dominio, re-exportada via `config.py`.

Los consumidores deben seguir importando desde `his_reports.config`
(`from .config import PORT, HIS_BASE, ...`). Este paquete `_config` es un
detalle de implementación y puede reorganizarse sin romper clientes.

Dominios:
  - `_server.py`    → puertos, paths del disco local
  - `_his.py`       → URLs y endpoints del HIS Hanga Roa
  - `_http.py`      → timeouts, retries, cache TTLs, headers HTTP
  - `_secrets.py`   → credenciales desde env (nunca a disco)
"""
from ._his import (
    ATENCIONES_FORM,
    ATENCIONES_LIST,
    CONSULTA_FICHA,
    FICHA_AMB,
    FICHA_URG,
    HIS_BASE,
    HIS_BASE_PATH,
    HIS_ORIGIN,
    LOGIN_ACTION,
    LOGIN_ROOT,
    MENU,
    REPORTE_FORM,
    REPORTE_LIST,
)
from ._http import (
    HEALTHZ_CACHE_TTL,
    HIS_BACKOFF_BASE,
    HIS_CIRCUIT_FAILURE_THRESHOLD,
    HIS_CIRCUIT_OPEN_SECONDS,
    HIS_MAX_BODY_BYTES,
    HIS_MAX_RETRIES,
    HIS_READ_CHUNK_BYTES,
    HIS_TIMEOUT,
    HOP_HEADERS,
    SECURITY_HEADERS,
    SERVICIOS_CACHE_TTL,
    UA,
)
from ._secrets import HIS_PASS_ENV, HIS_USER_ENV
from ._server import PORT, WEB_ROOT

# Alfabético — ruff RUF022 lo exige. Los dominios están documentados arriba
# (imports por submódulo) y en el docstring del módulo; mantener acá un orden
# temático duplicaba esa información y peleaba con la convención.
__all__ = [
    "ATENCIONES_FORM",
    "ATENCIONES_LIST",
    "CONSULTA_FICHA",
    "FICHA_AMB",
    "FICHA_URG",
    "HEALTHZ_CACHE_TTL",
    "HIS_BACKOFF_BASE",
    "HIS_BASE",
    "HIS_BASE_PATH",
    "HIS_CIRCUIT_FAILURE_THRESHOLD",
    "HIS_CIRCUIT_OPEN_SECONDS",
    "HIS_MAX_BODY_BYTES",
    "HIS_MAX_RETRIES",
    "HIS_ORIGIN",
    "HIS_PASS_ENV",
    "HIS_READ_CHUNK_BYTES",
    "HIS_TIMEOUT",
    "HIS_USER_ENV",
    "HOP_HEADERS",
    "LOGIN_ACTION",
    "LOGIN_ROOT",
    "MENU",
    "PORT",
    "REPORTE_FORM",
    "REPORTE_LIST",
    "SECURITY_HEADERS",
    "SERVICIOS_CACHE_TTL",
    "UA",
    "WEB_ROOT",
]
