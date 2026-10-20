"""Config del server local (puertos, paths del disco)."""
from __future__ import annotations

import os

PORT = int(os.environ.get("PORT", "8001"))

# WEB_ROOT apunta al directorio que contiene `index.html`, `css/`, `js/`.
# Subimos dos niveles desde este archivo: `_config/_server.py` → `his_reports/`
# → repo root.
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_ROOT = os.path.dirname(_PKG_DIR)
