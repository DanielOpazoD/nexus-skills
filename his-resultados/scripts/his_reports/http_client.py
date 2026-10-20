"""Cliente HTTP para el HIS con cookie jar compartida.

Expone:
  - `fetch_his(path, ...)`: GET/POST al HIS, devuelve (status, headers, body).
  - `is_login(body)`: ¿este body es la página de login del HIS?
  - `rewrite(body, content_type)`: reescribe URLs absolutas del HIS a locales.

Las cookies viven en `session.Session.cookie_jar` (acceso vía `get_session()`),
no en este módulo — ver `session.py` para el racional.

Características del cliente:
  - Timeout configurable vía `HIS_TIMEOUT` (default 30s).
  - Retry automático en fallos transitorios — `URLError` (red/DNS) y HTTP
    502/503/504 — con backoff exponencial. Configurable con
    `HIS_MAX_RETRIES` (default 2 → hasta 3 intentos totales). Todos los
    endpoints HIS que usamos son read-only desde el punto de vista de la
    app (aunque algunos se envían por POST), así que reintentar es seguro.
  - Decodificación automática de gzip/deflate.
  - **Cap de body** (`HIS_MAX_BODY_BYTES`, default 10 MB): lectura por
    chunks; aborta si el upstream devuelve más. Defensa contra HIS
    misbehaving (PDF gigante por accidente) y DoS parcial.
  - **Circuit breaker** (`_circuit.py`): después de N fallos consecutivos
    no se pega al HIS durante T segundos. Evita martillar a un upstream
    ya degradado y libera al frontend rápido en lugar de esperar timeouts.

Los `print` previos se reemplazaron por `logging` para respetar niveles.
"""
from __future__ import annotations

import contextlib
import gzip
import logging
import time
import zlib
from pathlib import Path
import sys
_COMMON = Path(__file__).resolve().parents[3] / "laboratorios-descargas" / "scripts"
if _COMMON.is_dir() and str(_COMMON) not in sys.path: sys.path.insert(0, str(_COMMON))
from clinical_transport import tls_context, ReliableOpener
from http import HTTPStatus
from typing import Protocol
from urllib import request as urlreq
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from ._circuit import get_breaker
from .config import (
    HIS_BACKOFF_BASE,
    HIS_BASE,
    HIS_MAX_BODY_BYTES,
    HIS_MAX_RETRIES,
    HIS_ORIGIN,
    HIS_READ_CHUNK_BYTES,
    HIS_TIMEOUT,
    UA,
)
from .session import get_session

log = logging.getLogger(__name__)


class _Readable(Protocol):
    """Subset de la interfaz `HTTPResponse` que `_read_with_cap`
    consume — `.read(n)` y `.close()`. `urllib`'s `HTTPError` también
    los expone (porque hereda de `addinfourl`), así que aplicamos el
    mismo cap a respuestas de error sin un cast.
    """
    def read(self, n: int = ..., /) -> bytes: ...
    def close(self) -> None: ...

# Contador thread-local no necesario — los reintentos son síncronos y cada
# request fetch_his() tiene su propio ámbito.

# HTTP statuses que típicamente indican un hiccup transitorio del upstream.
# 502 (bad gateway), 503 (unavailable), 504 (gateway timeout).
_TRANSIENT_STATUSES = frozenset({429, 502, 503, 504})


class _HISRedirect(urlreq.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != "https" or target.netloc != "his.hospitalhangaroa.cl" or not target.path.startswith("/hishhr/"):
            raise URLError("HIS intentó redirigir fuera de su origen autorizado")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urlreq.OpenerDirector:
    # Resolvemos la cookie jar en cada request, no al importar el módulo:
    # así `reset_default_session()` (tests) se propaga sin referencias stale.
    return urlreq.build_opener(urlreq.HTTPSHandler(context=tls_context()), _HISRedirect(), urlreq.HTTPCookieProcessor(get_session().cookie_jar))


def _decode(raw: bytes, enc: str) -> bytes:
    """Decodifica Content-Encoding (gzip/deflate). Si falla, devuelve `raw`."""
    if not enc:
        return raw
    e = enc.lower().strip()
    try:
        if e == "gzip":
            return gzip.decompress(raw)
        if e == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except OSError:
        return raw
    return raw


# Marcadores que indican "este body es el HIS pidiendo que reinicies sesión".
# Se chequean en lowercase contra los primeros 8KB del body. Cualquier match
# basta — favorecemos especificidad (literales del HIS) sobre cobertura
# (regex genéricos) para evitar falsos positivos.
#
# Hay tres familias, todas confirmadas con captures reales (`/api/_diag/sync`):
#
#   1) **Form de login clásico** (`acceso1.php`): el HIS lo sirve cuando
#      navegás directo al root sin sesión. Estos markers cubren atributos
#      del <form> y los <input> esperados.
#
#   2) **GETs degradados** (sesión expirada, navegando módulos): el HIS
#      sirve un HTML uniforme con un `<div class="alert alert-danger">¡ALERTA!
#      Error de Acceso. Vuelva a iniciar.</div>` y un botón "Volver a Ingresar"
#      que linkea a `index.php`. Captured 2026-04-28: el sha256 del body es
#      idéntico para `ateurg022.php`, `reporte_atenciones_amb.php` y
#      `consficha000.php` — middleware HIS global. NO contiene el form de
#      login, por eso los markers (1) no matcheaban y el chip quedaba verde.
#
#   3) **POSTs degradados** (búsquedas con sesión muerta): el HIS responde
#      121 bytes con `<script>top.window.location.href = '...hishhr/';</script>
#      <script>location.reload();</script>` — redirect JS forzado al root,
#      sin renderizar form. El `parse_*` no encuentra tabla → la UI dice
#      "Sin resultados" pero el chip dice "Conectado".
_LOGIN_MARKERS = (
    # (1) form de login clásico
    'action="acceso1', "action='acceso1", "/acceso1.php",
    'name="password"', "name='password'",
    'name="login"', "name='login'",
    'name="clave"',
    "acceso al sistema",
    "iniciar sesi",
    "ingresar usuario",
    # (2) GETs degradados — alert "Error de Acceso. Vuelva a iniciar"
    "error de acceso. vuelva a iniciar",
    # Botón "Volver a Ingresar" linkeando a index.php — segunda señal del
    # mismo body, para tolerar variaciones menores de copy.
    'href="index.php" role="button">volver a ingresar',
    # (3) POSTs degradados — redirect JS al root del HIS
    "top.window.location.href = 'https://his.hospitalhangaroa.cl/hishhr/'",
)


def is_login(body: bytes) -> bool:
    """Heurística: ¿este body es el HIS pidiendo que reinicies sesión?

    Cualquier match de `_LOGIN_MARKERS` en los primeros 8KB → True.
    Cubre tres familias de respuesta: form de login clásico, alert de
    "error de acceso" en GETs, y redirect JS en POSTs (ver `_LOGIN_MARKERS`).
    """
    t = body[:8000].decode("utf-8", errors="ignore").lower()
    return any(m in t for m in _LOGIN_MARKERS)


def _backoff(attempt: int) -> float:
    """Delay antes del próximo intento: base * 2**attempt.

    Con defaults (base=0.5, retries=2) da 0.5s, 1s, luego se da por vencido.
    """
    return float(HIS_BACKOFF_BASE * (2 ** attempt))


# Sentinela retornada por `_read_with_cap` cuando el body excedió el
# tope de bytes. Mantengo el shape `tuple[int, headers, bytes]` para no
# romper callers — el status sintético es 502 (gateway misbehaving).
_BODY_TOO_LARGE_STATUS = HTTPStatus.BAD_GATEWAY


def _read_with_cap(resp: _Readable, cap: int) -> tuple[bytes, bool]:
    """Lee el body de `resp` en chunks hasta `cap` bytes.

    Devuelve `(body, exceeded)`:
      - `exceeded=False`: la respuesta cabe en el cap, body completo.
      - `exceeded=True`: la respuesta superó el cap, body trunco (lo
        leído hasta el momento del corte). El caller decide qué hacer.

    Cierra el `resp` cuando termina o se excede — sin esto, la
    conexión queda colgada hasta que GC la libere.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = resp.read(HIS_READ_CHUNK_BYTES)
            if not chunk:
                return b"".join(chunks), False
            chunks.append(chunk)
            total += len(chunk)
            if total > cap:
                return b"".join(chunks), True
    finally:
        # `resp` viene del opener; cerrar suelta el socket subyacente.
        # `close()` es idempotente, así que llamarlo siempre es seguro.
        # `suppress` cubre el caso de un `resp` sin red ya cerrado.
        with contextlib.suppress(Exception):
            resp.close()


def _single_fetch(req: urlreq.Request) -> tuple[int, dict[str, str], bytes]:
    """Una sola llamada HTTP al HIS. Puede lanzar URLError (no HTTPError:
    lo capturamos y lo convertimos a tupla para dejar que el retry loop
    decida según el status).

    Lee el body en chunks con cap `HIS_MAX_BODY_BYTES`. Si excede,
    retorna `(502, ..., body_parcial)` con un payload sintético para
    que `fetch_his` no continúe con un body roto.
    """
    try:
        resp = _opener().open(req, timeout=HIS_TIMEOUT)
        body, exceeded = _read_with_cap(resp, HIS_MAX_BODY_BYTES)
        if exceeded:
            log.warning(
                "HIS body excedió cap (%d bytes) — truncando y retornando 502",
                HIS_MAX_BODY_BYTES,
            )
            return (
                _BODY_TOO_LARGE_STATUS,
                {"content-type": "text/plain"},
                f"body excede {HIS_MAX_BODY_BYTES} bytes".encode(),
            )
        return resp.status, dict(resp.getheaders()), body
    except HTTPError as e:
        headers = dict(e.headers.items()) if e.headers else {}
        # Los errores también pueden venir con body grande — aplicamos
        # el mismo cap. `e.read()` de urllib es leer-hasta-EOF, así que
        # leemos a mano por chunks.
        body = b""
        if hasattr(e, "read"):
            try:
                body, _exc = _read_with_cap(e, HIS_MAX_BODY_BYTES)
            except Exception:  # pragma: no cover - defensive
                body = b""
        return e.code, headers, body


def fetch_his(
    path_and_query: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    extra: dict[str, str | None] | None = None,
    allow_origin_referer: bool = False,
    read_only: bool = False,
) -> tuple[int, dict[str, str], bytes]:
    """Llama al HIS (absoluto o relativo a `HIS_ORIGIN`).

    Devuelve `(status, headers_dict, body_bytes)`. Maneja HTTPError (captura
    cuerpo) y URLError (devuelve 502 sintético tras agotar retries).
    Decodifica gzip/deflate.

    Blocked headers: `host` y `cookie` siempre; `origin`/`referer` también,
    salvo que el caller pase `allow_origin_referer=True` (flujos de login
    y POSTs donde el HIS valida estos headers).

    Retry: ante URLError o HTTP 502/503/504, reintenta hasta
    `HIS_MAX_RETRIES` veces con backoff exponencial. Safe porque todos los
    endpoints HIS que usamos son lecturas (aunque vengan por POST).

    Circuit breaker: antes de pegar consulta `_circuit.get_breaker()`. Si
    el breaker está abierto, retorna 503 inmediato sin tocar al HIS.
    El resultado del intento (éxito vs. fallo) se registra para que el
    breaker decida si cerrar o reabrir.
    """
    breaker = get_breaker()
    if not breaker.allow():
        log.warning("HIS circuit-breaker abierto — short-circuit %s",
                     path_and_query)
        return (
            HTTPStatus.SERVICE_UNAVAILABLE,
            {"content-type": "text/plain"},
            b"HIS temporalmente no disponible (circuit breaker abierto)",
        )

    url = HIS_ORIGIN + path_and_query if path_and_query.startswith("/") else path_and_query
    target = urlsplit(url)
    if target.scheme != "https" or target.netloc != "his.hospitalhangaroa.cl" or not target.path.startswith("/hishhr/"):
        raise ValueError("La ruta HIS no pertenece al origen autorizado.")
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "es-CL,es;q=0.9",
        "Referer": HIS_BASE + "/",
    }
    blocked = {"host", "cookie"}
    if not allow_origin_referer:
        blocked |= {"origin", "referer"}
    if extra:
        for k, v in extra.items():
            if k.lower() in blocked:
                continue
            if v is None:
                headers.pop(k, None)
                continue
            headers[k] = v
    req = urlreq.Request(url, data=data, method=method, headers=headers)

    status: int = 0
    raw_headers: dict[str, str] = {}
    body: bytes = b""
    last_err: str | None = None
    retries = HIS_MAX_RETRIES if method == "GET" or read_only else 0
    for attempt in range(retries + 1):
        try:
            status, raw_headers, body = _single_fetch(req)
        except URLError as e:
            last_err = str(e)
            if attempt < retries:
                delay = _backoff(attempt)
                log.warning("HIS URLError %s→ retry %d/%d en %.1fs",
                             path_and_query, attempt + 1,
                             HIS_MAX_RETRIES, delay)
                time.sleep(delay)
                continue
            log.error("HIS URLError definitivo %s tras %d intentos: %s",
                      path_and_query, attempt + 1, last_err)
            # Registramos fallo: agotamos retries por error de red. Es lo
            # que el breaker está pensado para detectar.
            breaker.record_failure()
            return 502, {"content-type": "text/plain"}, \
                   f"proxy error: {last_err}".encode()

        if status in _TRANSIENT_STATUSES and attempt < retries:
            headers_ci = {k.lower():v for k,v in raw_headers.items()}
            delay = ReliableOpener(None).delay({"Retry-After": headers_ci["retry-after"]}) if "retry-after" in headers_ci else _backoff(attempt)
            if delay > 5: break
            log.warning("HIS %s %s → retry %d/%d en %.1fs",
                         status, path_and_query, attempt + 1,
                         HIS_MAX_RETRIES, delay)
            time.sleep(delay)
            continue
        break

    # Registrar outcome final en el breaker. Solo HTTP 5xx (o status
    # 0 que no debería darse) cuentan como fallo — 4xx son problemas
    # del cliente (auth, validation) y no significan que el HIS esté
    # mal. 502/503/504 sí: estamos en este punto porque agotamos retries.
    if status >= 500 or status == 0:
        breaker.record_failure()
    else:
        breaker.record_success()

    ce = raw_headers.get("Content-Encoding") or raw_headers.get("content-encoding") or ""
    if ce:
        body = _decode(body, ce)
        raw_headers = {k: v for k, v in raw_headers.items() if k.lower() != "content-encoding"}
    return status, raw_headers, body


def rewrite(body: bytes, ct: str) -> bytes:
    """Reescribe URLs absolutas al HIS por rutas locales /hishhr/... en bodies
    HTML/JS/JSON/CSS. Evita que el navegador salga del proxy local."""
    ct = (ct or "").lower()
    if not any(t in ct for t in ("text/html", "javascript", "application/json", "text/css")):
        return body
    try:
        s = body.decode("utf-8")
    except UnicodeDecodeError:
        try:
            s = body.decode("latin-1")
        except Exception:
            return body
    s = s.replace("https://his.hospitalhangaroa.cl/hishhr", "/hishhr")
    s = s.replace("http://his.hospitalhangaroa.cl/hishhr", "/hishhr")
    return s.encode("utf-8")
