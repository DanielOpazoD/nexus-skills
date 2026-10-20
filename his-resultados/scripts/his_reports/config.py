"""Configuración central — fachada pública del paquete `_config/`.

Todas las constantes de configuración siguen importándose desde aquí:
    from .config import HIS_BASE, HOP_HEADERS, PORT, ...

La implementación vive en el sub-paquete `_config/`, donde cada módulo
cubre un dominio (server, HIS, HTTP, secrets). Si agregás una constante,
ponela en el submódulo que corresponda y exportala también desde
`_config/__init__.py`.
"""
from __future__ import annotations

from ._config import (
    ATENCIONES_FORM,
    ATENCIONES_LIST,
    CONSULTA_FICHA,
    FICHA_AMB,
    FICHA_URG,
    HEALTHZ_CACHE_TTL,
    HIS_BACKOFF_BASE,
    HIS_BASE,
    HIS_BASE_PATH,
    HIS_CIRCUIT_FAILURE_THRESHOLD,
    HIS_CIRCUIT_OPEN_SECONDS,
    HIS_MAX_BODY_BYTES,
    HIS_MAX_RETRIES,
    HIS_ORIGIN,
    HIS_PASS_ENV,
    HIS_READ_CHUNK_BYTES,
    HIS_TIMEOUT,
    HIS_USER_ENV,
    HOP_HEADERS,
    LOGIN_ACTION,
    LOGIN_ROOT,
    MENU,
    PORT,
    REPORTE_FORM,
    REPORTE_LIST,
    SECURITY_HEADERS,
    SERVICIOS_CACHE_TTL,
    UA,
    WEB_ROOT,
)

# `__all__` explícito — mypy en modo strict (no_implicit_reexport) necesita
# el listado para tratar el módulo como "public re-export". Coincide con el
# de `_config/__init__.py` y se mantiene alfabético para ruff RUF022.
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
