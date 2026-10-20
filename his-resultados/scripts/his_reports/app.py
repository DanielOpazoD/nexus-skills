"""Entry point: `python3 server.py` o `python3 -m his_reports`."""
from __future__ import annotations

import logging

from .auth import auto_login_if_env
from .config import HIS_USER_ENV, PORT
from .handler import Handler, Server
from .observability import install_logging


def main() -> None:
    install_logging(level=logging.INFO)
    log = logging.getLogger("his_reports")
    srv = Server(("127.0.0.1", PORT), Handler)
    log.info("Web Reportes: http://localhost:%s", PORT)
    if HIS_USER_ENV:
        log.info("auto-login: HIS_USER detectado (%s), intentando sesión…",
                 HIS_USER_ENV)
        auto_login_if_env()
    else:
        log.info("Sin HIS_USER/HIS_PASS en env. Usa el formulario de login "
                 "en la página.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print()  # deja la terminal en línea limpia al Ctrl-C
