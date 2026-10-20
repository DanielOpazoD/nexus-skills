"""HTTP handler — dispatch de API JSON, estáticos, reverse-proxy.

Arquitectura:

  - Este módulo se limita a HTTP mechanics:
      · leer request (path, query, body)
      · llamar al resolver correspondiente
      · escribir response (status + headers + body) al socket
  - La lógica de cada endpoint vive en `his_reports.api`.
  - El dispatch se define en `his_reports.routes`.
  - Resolución de estáticos vive en `his_reports.static_files` (función
    pura `resolve_static(path, root) -> (status, body, ctype)`).
  - Reverse-proxy vive en `his_reports.proxy` (headers/body rewriting).
"""
from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from lab_hanga.errors import LabHHRError
from lab_hanga.routes import GET_ROUTES as LAB_HHR_GET_ROUTES
from lab_hanga.routes import POST_ROUTES as LAB_HHR_POST_ROUTES
from lab_hanga.scrape import fetch_pdf as _lab_hhr_fetch_pdf
from lab_salvador.errors import LabError
from lab_salvador.routes import GET_ROUTES as LAB_GET_ROUTES
from lab_salvador.routes import POST_ROUTES as LAB_POST_ROUTES
from lab_salvador.scrape import fetch_informe_pdf as _lab_fetch_informe_pdf

from .config import SECURITY_HEADERS, WEB_ROOT
from .errors import HISError
from .http_client import fetch_his, rewrite
from .observability import new_req_id, set_req_id, track_request
from .proxy import filtered_response_headers
from .routes import GET_ROUTES as _HIS_GET_ROUTES
from .routes import POST_ROUTES as _HIS_POST_ROUTES
from .routes import Endpoint
from .static_files import resolve_static

# Merge de tablas de rutas. Los tres módulos definen rutas disjuntas por
# prefijo (`/api/` HIS, `/api/lab/` Salvador, `/api/lab-hhr/` Hanga Roa),
# así que un dict union es suficiente. Si alguna vez se solapan, los
# tests de estructura del dispatch deben loggar duplicados.
GET_ROUTES: dict[str, Endpoint] = {
    **_HIS_GET_ROUTES, **LAB_GET_ROUTES, **LAB_HHR_GET_ROUTES,
}
POST_ROUTES: dict[str, Endpoint] = {
    **_HIS_POST_ROUTES, **LAB_POST_ROUTES, **LAB_HHR_POST_ROUTES,
}

# Paths de bytes binarios — no van por la tabla JSON porque devuelven
# stream, no un dict. El handler los dispatch directamente.
_LAB_PDF_PATH = "/api/lab/orden/pdf"
_LAB_HHR_PDF_PATH = "/api/lab-hhr/pdf"

log = logging.getLogger(__name__)


# CSRF defense para POSTs: comparamos `Origin` contra `Host`. Si el
# `Origin` que reporta el browser no corresponde al hostname+puerto al que
# está llegando la request, rechazamos.
#
# Por qué: el server escucha en loopback, pero un sitio cualquiera que el
# usuario abra en el mismo browser puede hacer `fetch('http://localhost:PORT/
# api/logout')`. Same-origin-policy no protege contra esto porque el request
# lo inicia otro origen contra el nuestro — es CSRF clásico. También cubre
# parcialmente DNS rebinding (el atacante resuelve su dominio a 127.0.0.1).
#
# Por qué comparar contra `Host` en lugar de una constante: el PORT es
# configurable por env var, y los tests de integración usan puerto efímero
# — una allowlist hardcoded no funciona. `Host` viene del mismo browser que
# mandó el Origin, así que comparar ambos campos nos da una validación
# coherente independiente del puerto.
#
# Filosofía del check: si `Origin` viene, exigir match con `Host`. Si no
# viene (típico en requests same-origin que el browser omite, o en curl sin
# flags), dejar pasar — no queremos romper debugging local.


def _origin_matches_host(origin: str | None, host: str | None) -> bool:
    """True si `origin` es aceptable dado que el request llegó a `host`.

    - `origin` None/vacío → True (no hay qué chequear).
    - `host` None/vacío → True (tolerante; en la práctica HTTP/1.1 siempre
      lo manda, pero no queremos romper si un cliente raro no lo hace).
    - `origin == http://<host>` → True.
    - Swap localhost ↔ 127.0.0.1 con mismo puerto → True (el usuario puede
      llegar por cualquiera de las dos y ambas apuntan al mismo proceso).
    - Otro caso → False.

    Pura para testing unitario sin levantar server.
    """
    if not origin:
        return True
    if not host:
        return True
    allowed = {f"http://{host}"}
    # `host` viene como "localhost:8001" o "127.0.0.1:8001"; aceptamos el
    # equivalente con el otro hostname loopback.
    if ":" in host:
        hostname, port = host.rsplit(":", 1)
        if hostname == "localhost":
            allowed.add(f"http://127.0.0.1:{port}")
        elif hostname == "127.0.0.1":
            allowed.add(f"http://localhost:{port}")
    return origin in allowed


class Handler(BaseHTTPRequestHandler):
    """Dispatch: estáticos, endpoints JSON, reverse-proxy."""

    server_version = "WebReportesProxy/0.3"

    # Dirigir logs de BaseHTTPRequestHandler a nuestro logger.
    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    # ----- helpers de respuesta -----

    def _send_security_headers(self) -> None:
        """Agrega los headers de seguridad comunes (CSP, X-Content-Type-Options,
        Referrer-Policy). Llamado desde `_json` y `_static` — NO desde
        `_proxy`, que debe preservar los headers del HIS.
        """
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        # La resolución (path → archivo + ctype, con check de traversal) vive
        # en `static_files.py` como función pura. Acá solo la mecánica HTTP.
        status, body, ctype = resolve_static(path, WEB_ROOT)
        if status != HTTPStatus.OK:
            self.send_error(status)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, path_and_query: str, method: str = "GET") -> None:
        # Agrupamos todos los paths del HIS en un bucket "/hishhr/*" para no
        # inflar el dict de métricas con una entrada por URL HIS distinta.
        # El proxy existe solo para debugging, pero contar sus respuestas en
        # healthz ayuda a ver uso anómalo (p. ej. scraping accidental).
        with track_request("/hishhr/*") as ctx:
            body_in = None
            clen = int(self.headers.get("Content-Length") or 0)
            if clen > 0:
                body_in = self.rfile.read(clen)
            ct_in = self.headers.get("Content-Type")
            extra: dict[str, str | None] | None = (
                {"Content-Type": ct_in} if ct_in else None
            )
            status, headers, body = fetch_his(path_and_query, method=method,
                                               data=body_in, extra=extra)
            ctx["status"] = status
            ct = headers.get("Content-Type") or headers.get("content-type") or ""
            body = rewrite(body, ct)
            self.send_response(status)
            # Filtrado (hop-by-hop out, Location reescrita) vive en proxy.py.
            for k, v in filtered_response_headers(headers.items()):
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(body)

    # ----- dispatch de API -----

    def _dispatch_api(self, routes: dict[str, Endpoint], path: str,
                       q: dict[str, list[str]], body: bytes) -> bool:
        """Ejecuta el endpoint correspondiente a `path`. Captura `HISError`.

        Devuelve True si encontró una ruta (y respondió); False si no.

        Alrededor del llamado envolvemos un `track_request` para:
          - medir latencia por path
          - contar éxitos/errores por bucket (2xx/4xx/5xx)
          - el req-id ya está seteado en do_GET/do_POST
        """
        fn = routes.get(path)
        if fn is None:
            return False
        with track_request(path) as ctx:
            try:
                status, payload = fn(q, body)
            except HISError as e:
                status, payload = e.status, {"error": e.message}
            except LabError as e:
                # `LabError` se traduce igual que `HISError` — `.code` ya
                # trae el HTTP status correcto, y `str(e)` es seguro de
                # mostrar (el constructor garantiza no incluir passwords).
                status, payload = e.code, {"error": str(e)}
            except LabHHRError as e:
                # Igual que `LabError`. El mensaje incluye "scraper Node
                # no está corriendo" cuando el upstream está apagado —
                # se muestra al usuario para que sepa qué hacer.
                status, payload = e.code, {"error": str(e)}
            except Exception:
                log.exception("Unhandled error en %s", path)
                status, payload = HTTPStatus.INTERNAL_SERVER_ERROR, {
                    "error": "INTERNAL_ERROR"
                }
            ctx["status"] = status
        self._json(status, payload)
        return True

    def _lab_pdf(self, q: dict[str, list[str]]) -> None:
        """GET `/api/lab/orden/pdf` — stream-through del PDF del lab.

        Está separado de `_dispatch_api` porque devuelve bytes binarios,
        no JSON. Pasa los bytes directamente al socket sin parsing.

        Si el lab rechaza la sesión, responde 401 JSON; si el upstream
        falla, 502 JSON. Solo el path feliz devuelve PDF.
        """
        ord_enc = (q.get("ord") or [""])[0].strip()
        prt = (q.get("prt") or [""])[0].strip()
        if not ord_enc:
            self._json(HTTPStatus.BAD_REQUEST,
                       {"error": "falta ord (OrdenEncryptada)"})
            return
        with track_request(_LAB_PDF_PATH) as ctx:
            try:
                pdf_bytes, ctype = _lab_fetch_informe_pdf(ord_enc, prt)
            except LabError as e:
                ctx["status"] = e.code
                self._json(e.code, {"error": str(e)})
                return
            except Exception:
                log.exception("Unhandled error en %s", _LAB_PDF_PATH)
                ctx["status"] = HTTPStatus.INTERNAL_SERVER_ERROR
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR,
                           {"error": "INTERNAL_ERROR"})
                return
            ctx["status"] = HTTPStatus.OK
            self.send_response(HTTPStatus.OK)
            # Forzamos `application/pdf` si el lab lo etiquetó como
            # `application/octet-stream` (común en algunos backends ASP.NET).
            # El navegador abre PDF inline solo con el ctype correcto.
            if "pdf" in ctype.lower() or "octet" in ctype.lower():
                ctype = "application/pdf"
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(pdf_bytes)))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(pdf_bytes)

    def _lab_hhr_pdf(self, q: dict[str, list[str]]) -> None:
        """GET `/api/lab-hhr/pdf?link=<url>` — stream-through del PDF
        del scraper Node de Syslab.

        Separado del JSON dispatch porque devuelve bytes binarios.
        El parámetro es `link` (URL absoluta de Syslab), no un ID
        encriptado — así viene del Node y así se lo devolvemos.
        """
        link = (q.get("link") or [""])[0].strip()
        if not link:
            self._json(HTTPStatus.BAD_REQUEST,
                       {"error": "falta link (URL del detalle de Syslab)"})
            return
        with track_request(_LAB_HHR_PDF_PATH) as ctx:
            try:
                pdf_bytes, ctype = _lab_hhr_fetch_pdf(link)
            except LabHHRError as e:
                ctx["status"] = e.code
                self._json(e.code, {"error": str(e)})
                return
            except Exception:
                log.exception("Unhandled error en %s", _LAB_HHR_PDF_PATH)
                ctx["status"] = HTTPStatus.INTERNAL_SERVER_ERROR
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR,
                           {"error": "INTERNAL_ERROR"})
                return
            ctx["status"] = HTTPStatus.OK
            self.send_response(HTTPStatus.OK)
            if "pdf" in ctype.lower() or "octet" in ctype.lower():
                ctype = "application/pdf"
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(pdf_bytes)))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(pdf_bytes)

    def _read_body(self) -> bytes:
        clen = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(clen) if clen else b""

    # ----- verbos HTTP -----

    def do_GET(self) -> None:
        set_req_id(new_req_id())
        u = urlparse(self.path)
        path = u.path
        if path in ("/", "/index.html"):
            self._static("/index.html")
            return
        if path.startswith("/css/") or path.startswith("/js/"):
            self._static(path)
            return
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if path.startswith("/api/"):
            q = parse_qs(u.query)
            # PDFs binarios fuera del dispatch JSON.
            if path == _LAB_PDF_PATH:
                self._lab_pdf(q)
                return
            if path == _LAB_HHR_PDF_PATH:
                self._lab_hhr_pdf(q)
                return
            if self._dispatch_api(GET_ROUTES, path, q, b""):
                return
        if path.startswith("/hishhr/") or path == "/hishhr":
            self._proxy(self.path, "GET")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        set_req_id(new_req_id())
        u = urlparse(self.path)
        # CSRF defense: rechazar POSTs con `Origin` de un sitio distinto al
        # nuestro. Solo para `/api/*` — el reverse-proxy `/hishhr/*` existe
        # para debugging y no queremos agregar fricción ahí.
        if u.path.startswith("/api/"):
            origin = self.headers.get("Origin")
            host = self.headers.get("Host")
            if not _origin_matches_host(origin, host):
                log.warning("POST %s rechazado: Origin=%r, Host=%r",
                            u.path, origin, host)
                self._json(HTTPStatus.FORBIDDEN,
                           {"error": "origin no permitido"})
                return
            body = self._read_body()
            q = parse_qs(u.query)
            if self._dispatch_api(POST_ROUTES, u.path, q, body):
                return
        if u.path.startswith("/hishhr/"):
            self._proxy(self.path, "POST")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:
        u = urlparse(self.path)
        if u.path.startswith("/hishhr/"):
            self._proxy(self.path, "HEAD")
            return
        self.send_response(HTTPStatus.OK)
        self.end_headers()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
