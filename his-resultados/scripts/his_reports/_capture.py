"""Captura de bodies HIS para diagnóstico de estado de sesión.

Pensado para ejecutarse **a demanda** cuando se reproduce el bug "chip
'Conectado' verde pero las búsquedas devuelven vacío" — síntoma de sesión
semi-expirada en algún módulo HIS que `is_login()` no detecta. El endpoint
`/api/_diag/sync` dispara una pasada de sondas y guarda los bodies
redactados a disco, para que podamos diseñar markers nuevos sobre datos
reales en lugar de adivinar.

Decisiones:

- **No es instrumentación constante.** Los bodies se guardan en
  `~/.his_reports/captures/` (fuera del repo) y conviene revisarlos +
  borrarlos manualmente. Si un día querés rotación automática, agregar
  acá.
- **PHI redactada antes de tocar disco.** Reusamos `_diagnostics._redact_phi`
  — RUTs y nombres en mayúsculas se reemplazan por `[RUT]` / `[NOMBRE]`
  preservando estructura HTML. En estado degradado (login page, sesión
  expirada, tabla vacía) en general no hay PHI, pero la redacción cubre
  el caso "capturé esto cuando la sesión sí servía y devolvió pacientes".
- **Snippets en JSON, body completo en disco.** El JSON del endpoint
  trae un snippet corto + métricas estructurales (`tr_count`,
  `table_count`, `no_data_marker`). El body completo redactado va a
  disco — lo abrís en el editor cuando querés mirar markup.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import TypedDict

from ._diagnostics import _redact_phi

# Directorio de captura: bajo HOME para que no entre al repo por accidente
# y para que persista entre runs del server.
CAPTURE_DIR = Path.home() / ".his_reports" / "captures"

# Snippet de body que viaja en JSON. 600 chars suelen ser suficientes para
# distinguir "página de login" / "tabla vacía" / "error genérico" sin
# inflar la respuesta.
_SNIPPET_LEN = 600

# Misma lista que `_diagnostics._NO_DATA_MARKERS`. Duplicada acá para que
# `_capture` no tenga que importar nombres privados de `_diagnostics` más
# allá del redactor — minimizar el surface acoplado.
_NO_DATA_MARKERS = (
    "sin resultados",
    "no existen datos",
    "no se encontraron",
    "no hay registros",
    "no se han encontrado",
    "su sesión ha expirado",
    "vuelva a iniciar sesi",
)

_TR_RE = re.compile(rb"<tr[^>]*>", re.IGNORECASE)
_TABLE_RE = re.compile(rb"<table[^>]*>", re.IGNORECASE)
_FILE_LABEL_RE = re.compile(r"[^A-Za-z0-9_-]+")


class CaptureMeta(TypedDict):
    """Metadata estructural de un body capturado.

    Lo que devuelve `/api/_diag/sync` por probe. El body completo
    (redactado) queda en disco — `saved_to` es la ruta para inspección
    manual.
    """
    label: str
    method: str
    his_path: str
    status: int
    bytes: int
    sha256_short: str
    looks_login: bool
    tr_count: int
    table_count: int
    no_data_marker: str | None
    snippet: str
    saved_to: str | None  # None si falló el write a disco


def _file_label(label: str) -> str:
    """Sanitiza un label arbitrario a algo seguro como filename."""
    safe = _FILE_LABEL_RE.sub("_", label).strip("_")
    return safe[:40] or "capture"


def capture_body(
    label: str,
    method: str,
    his_path: str,
    status: int,
    body: bytes,
    *,
    looks_login: bool,
) -> CaptureMeta:
    """Guarda `body` redactado a disco y devuelve metadata estructural.

    `looks_login` viene del caller (que ya invoca `is_login(body)`); lo
    pasamos en vez de re-evaluar para que esta función quede sin
    dependencias en `http_client`.

    Si el write a disco falla (disco lleno, permisos), `saved_to` queda
    `None` y el resto de la metadata se devuelve igual — un endpoint de
    diagnóstico que se cae por un disco lleno no ayuda a nadie.
    """
    body_str = body.decode("utf-8", errors="replace")
    redacted = _redact_phi(body_str)

    ts = time.strftime("%Y%m%dT%H%M%S")
    fname = f"{ts}_{_file_label(label)}.html"
    path = CAPTURE_DIR / fname
    saved: str | None
    try:
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(redacted, encoding="utf-8")
        saved = str(path)
    except OSError:
        saved = None

    text_lower = body_str[:8000].lower()
    no_data = next((m for m in _NO_DATA_MARKERS if m in text_lower), None)

    return {
        "label": label,
        "method": method,
        "his_path": his_path,
        "status": status,
        "bytes": len(body),
        "sha256_short": hashlib.sha256(body).hexdigest()[:16],
        "looks_login": looks_login,
        "tr_count": len(_TR_RE.findall(body)),
        "table_count": len(_TABLE_RE.findall(body)),
        "no_data_marker": no_data,
        "snippet": _redact_phi(body_str[:_SNIPPET_LEN]),
        "saved_to": saved,
    }
