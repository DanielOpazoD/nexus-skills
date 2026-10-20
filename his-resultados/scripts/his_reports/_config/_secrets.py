"""Credenciales desde variables de entorno. NUNCA se persisten a disco.

El usuario puede exportarlas antes de arrancar el server:
    HIS_USER=rut_sin_dv HIS_PASS=clave python3 server.py

Si ambas están presentes, `auth.auto_login_if_env()` dispara un login al
arrancar — útil para desarrollo.
"""
from __future__ import annotations

import os

HIS_USER_ENV = os.environ.get("HIS_USER", "")
HIS_PASS_ENV = os.environ.get("HIS_PASS", "")
