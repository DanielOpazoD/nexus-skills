"""Endpoints de la API JSON como funciones puras.

Responsabilidad acotada: ESTE módulo solo orquesta.

  Input → parse query → valida → delega en `scrape.py` → compone respuesta.

No toca URLs del HIS, ni HTML, ni warm-ups — eso vive en `scrape.py`. Esto
hace que agregar validaciones o reglas de negocio (ej. filtrar por RUT en
memoria) quede en un solo lugar, sin mezclarse con la mecánica HTTP del
HIS.

Contrato común: cada endpoint devuelve `(status_int, payload_dict)` o lanza
`HISError`. El handler HTTP (`handler.py`) traduce la tupla a JSON y
captura `HISError` en un solo lugar.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

from . import scrape
from ._capture import CAPTURE_DIR, CaptureMeta, capture_body
from .auth import try_login
from .config import (
    ATENCIONES_FORM,
    ATENCIONES_LIST,
    CONSULTA_FICHA,
    HIS_BASE,
    HIS_ORIGIN,
    REPORTE_FORM,
    REPORTE_LIST,
)
from .http_client import fetch_his, is_login
from .observability import metrics_snapshot
from .probes import probe_his
from .session import get_session
from .types import AtencionRow
from .validators import (
    valid_date_range,
    valid_fuente,
    valid_iso_date,
    valid_numeric_id,
    valid_rut,
)

log = logging.getLogger(__name__)

# Alias de la firma pública que devuelve cada endpoint. El handler espera
# `(status_int, json_serializable_dict)` — los TypedDicts del parser se
# convierten a dict plano antes de retornar (ver `atencion`).
ApiResponse = tuple[int, dict[str, Any]]

# `parse_qs` devuelve `dict[str, list[str]]`; usamos ese tipo para que
# `_qs()` sepa que hay que des-listar.
Query = dict[str, list[str]]

# Firma de los fetchers de listado (`scrape.fetch_atenciones_*`): toman
# `(desde, hasta, servicio)` ya validados y devuelven filas. Tenerlo como
# alias tipado permite que `_fetch_por_servicios` preserve el tipo de la
# fila devuelta en vez de caer a `Any`.
FetcherListado = Callable[[str, str, str], list[AtencionRow]]


# ----------------- helpers de query -----------------

def _norm_rut(v: str) -> str:
    """Normaliza RUT para comparar (quita puntos, guiones, lowercase)."""
    return re.sub(r"[^0-9kK]", "", v or "").lower()


def _qs(q: Query, key: str, default: str = "") -> str:
    """Extrae un valor escalar de un `parse_qs` dict (que da listas)."""
    v = q.get(key)
    if not v:
        return default
    # `parse_qs` siempre da lista; acomodamos un valor escalar por si algún
    # caller pasa un dict ya normalizado.
    if isinstance(v, list):
        return v[0] if v else default
    return str(v)


def _first_error(*errors: str | None) -> str | None:
    """Primera validación que falle (ignora `None`)."""
    for e in errors:
        if e:
            return e
    return None


# ----------------- status / login -----------------

def status() -> ApiResponse:
    """Estado rápido de sesión. Hace una request al HIS para saber si las
    cookies siguen siendo válidas — por eso no es tan barato como healthz."""
    has = get_session().has_his_cookies()
    authed = False
    if has:
        # Verificamos contra la landing del form (GET ateurg022.php)
        # porque ateurg023.php solo responde a POST.
        s, _, b = fetch_his(ATENCIONES_FORM)
        authed = (s == HTTPStatus.OK and not is_login(b))
    return HTTPStatus.OK, {"cookies": has, "authenticated": authed,
                           "his_base": HIS_BASE}


def login(body: bytes) -> ApiResponse:
    try:
        payload = json.loads((body or b"{}").decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return HTTPStatus.BAD_REQUEST, {"error": "JSON inválido"}
    user = (payload.get("user") or "").strip()
    password = payload.get("pass") or ""
    if not user or not password:
        return HTTPStatus.BAD_REQUEST, {"error": "faltan user/pass"}
    ok, msg = try_login(user, password)
    if ok:
        return HTTPStatus.OK, {"ok": True}
    return HTTPStatus.UNAUTHORIZED, {"ok": False, "error": msg}


def logout() -> ApiResponse:
    # `Session.reset()` limpia cookies + caches en una operación atómica.
    # Antes era "acordate de llamar a COOKIE_JAR.clear() Y a invalidate_all()"
    # — dos operaciones con acoplamiento implícito. Ahora es una sola llamada.
    get_session().reset()
    return HTTPStatus.OK, {"ok": True}


# ----------------- servicios -----------------

def servicios() -> ApiResponse:
    """Catálogo de especialidades. Cacheado con TTL (ver config).

    El HIS sirve este listado como un `<select>` dentro del form de
    ambulatorio, así que pedirlo hace una request completa al HIS. Con
    cache evitamos N requests por sesión (cada vez que el usuario abre el
    selector). Cache se invalida en logout.
    """
    cache = get_session().servicios_cache
    cached = cache.get()
    if cached is not None:
        return HTTPStatus.OK, {"servicios": cached, "_cached": True}
    items = scrape.fetch_servicios()
    cache.set(items)
    return HTTPStatus.OK, {"servicios": items}


# ----------------- listado de atenciones -----------------

def _parse_servicios(raw: str) -> list[str]:
    """Parsea el param `servicio` en una lista de IDs. Acepta:

      - "" (vacío)              → [] (= "todos", el backend pasa serv=0)
      - "123"                   → ["123"]
      - "123,456, 789"          → ["123", "456", "789"] (dedup, sin vacíos)

    El HIS solo acepta un `serv` por POST — si pedimos >1 hacemos fan-out
    (N requests) y mergeamos las filas. Acá la única responsabilidad es
    parsear; el orquestador de abajo decide si hace 1 o N calls.
    """
    seen: set[str] = set()
    out: list[str] = []
    for chunk in raw.split(","):
        s = chunk.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def atenciones(q: Query) -> ApiResponse:
    """Listado por rango + servicio(s) (+ filtros RUT/médico/estado),
    ambulatorio o urgencia según `fuente`.

    Parámetros query:
      - `desde`, `hasta` (YYYY-MM-DD)
      - `servicio` (id | id,id,... con coma) — multi-selección supportada.
        Con >1 id, hacemos fan-out (una request al HIS por servicio) y
        concatenamos los resultados; el HIS no tiene un endpoint "N servicios
        a la vez". Dedup por `idCuenta` (defensivo — en la práctica una
        atención pertenece a un único servicio).
      - `rut` (opcional) — match exacto sobre RUT normalizado
      - `medico` (opcional) — substring case-insensitive sobre MEDICO ATIENDE
      - `estado` (opcional) — substring case-insensitive sobre columna ESTADO.
        La UI manda valores cortos ("atendido", "anulada", "no se presenta",
        "pendiente", "en atención") que matchean los estados del HIS por
        substring — así "atendido" captura tanto "Paciente atendido" como
        "Paciente atendido y con alta" en una sola selección.
      - `fuente` (opcional) — "ambulatorio" (default) | "urgencia"
    """
    desde = _qs(q, "desde")
    hasta = _qs(q, "hasta")
    servicio_raw = _qs(q, "servicio")
    servicios = _parse_servicios(servicio_raw)
    rut = _qs(q, "rut")
    medico = _qs(q, "medico")
    estado = _qs(q, "estado")
    fuente = _qs(q, "fuente", "ambulatorio").lower()

    if not (desde or hasta or servicios or rut or medico or estado):
        return HTTPStatus.BAD_REQUEST, {
            "error": "Indica al menos un filtro "
                     "(desde/hasta/servicio/rut/medico/estado)"
        }
    # Validación: fechas ISO, rango coherente, fuente conocida, cada
    # servicio numérico, RUT con DV correcto. Todos opcionales — el
    # endpoint sólo exige ≥1 filtro arriba (checkeado antes).
    err = _first_error(
        valid_iso_date(desde, field="desde"),
        valid_iso_date(hasta, field="hasta"),
        valid_date_range(desde, hasta),
        valid_fuente(fuente),
        valid_rut(rut),
    )
    if err:
        return HTTPStatus.BAD_REQUEST, {"error": err}
    # Validar cada ID de servicio individualmente.
    for sid in servicios:
        e = valid_numeric_id(sid, field="servicio", max_len=6)
        if e:
            return HTTPStatus.BAD_REQUEST, {"error": e}

    fetcher = (scrape.fetch_atenciones_urgencia if fuente.startswith("urg")
               else scrape.fetch_atenciones_ambulatorio)
    rows = _fetch_por_servicios(fetcher, desde, hasta, servicios)

    if rut:
        rn = _norm_rut(rut)
        rows = [a for a in rows if _norm_rut(a.get("rut", "")) == rn]
    if medico:
        needle = medico.strip().lower()
        rows = [a for a in rows if needle in (a.get("medico") or "").lower()]
    if estado:
        # Substring case-insensitive — el HIS devuelve frases completas
        # ("Paciente atendido y con alta") mientras que la UI manda el
        # sustantivo ("atendido"). Usamos `in` para cubrir todas las
        # variantes sin enumerarlas una por una acá.
        needle = estado.strip().lower()
        rows = [a for a in rows if needle in (a.get("estado") or "").lower()]

    # `filtros.servicio` conserva el raw pasado por la UI (puede ser "1,2")
    # para que el frontend pueda eco-plotear los chips sin re-armar.
    return HTTPStatus.OK, {
        "atenciones": rows,
        "filtros": {"desde": desde, "hasta": hasta,
                    "servicio": servicio_raw, "servicios": servicios,
                    "rut": rut, "medico": medico, "estado": estado,
                    "fuente": fuente},
    }


# Cap de workers paralelos para fan-out por servicio. Conservador para no
# martillar el HIS — cada POST de listado suele tomar 2-5s. Con 3 workers la
# latencia agregada ~= max de las 3 requests en lugar de sum, sin tumbar el
# servidor.
_FANOUT_MAX_WORKERS = 3


def _fetch_por_servicios(
    fetcher: FetcherListado,
    desde: str, hasta: str,
    servicios: list[str],
) -> list[AtencionRow]:
    """Fan-out de N requests (una por servicio) y merge.

    Casos:
      - `servicios` vacío: 1 request con serv="" → el HIS devuelve todos.
      - `servicios` con 1: 1 request (comportamiento legacy).
      - `servicios` con N>1: N requests en paralelo, concat + dedup por
        `idCuenta`. El orden final es por fecha+hora desc (el mismo que
        devuelve el HIS para una única especialidad).

    El fan-out usa un ThreadPoolExecutor con cap conservador
    (`_FANOUT_MAX_WORKERS`). Si una request falla, propagamos el HISError
    (una especialidad fallida rompe la búsqueda — es intencional: mejor
    "no encontró X" que "encontró X parcialmente y no te avisó").
    """
    if len(servicios) <= 1:
        # Path legacy: 1 sola request (posiblemente con serv="" = todos).
        sid = servicios[0] if servicios else ""
        return list(fetcher(desde, hasta, sid))

    # N > 1 → paralelo.
    workers = min(_FANOUT_MAX_WORKERS, len(servicios))
    results: list[list[AtencionRow]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(fetcher, desde, hasta, sid) for sid in servicios]
        for f in futs:
            results.append(list(f.result()))

    # Merge con dedup por idCuenta (defensivo — en la práctica una atención
    # pertenece a un único servicio). Preservamos el orden de la primera
    # aparición — así las filas del primer servicio salen primero, del
    # segundo después, etc. La UI puede re-ordenar por fecha/hora si
    # quiere (el sort client-side ya existe).
    seen: set[str] = set()
    merged: list[AtencionRow] = []
    for batch in results:
        for row in batch:
            key = str(row.get("idCuenta") or "")
            # Si no hay idCuenta (raro pero posible con filas parciales),
            # no podemos dedup — la incluimos igual para no perder info.
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(row)
    return merged


def atenciones_por_rut(q: Query) -> ApiResponse:
    """Historial del paciente via `consficha000.php`.

    El HIS exige RUT SIN dígito verificador — acá extraemos la parte antes
    del guión antes de pasar al scraper.

    Tras el listado, abrimos cada ficha individual en paralelo para
    rellenar el campo `medico` (la tabla del HIS no lo trae). El
    enriquecimiento se puede desactivar con `enriquecer=0` para tests o
    para respuestas rápidas cuando el médico no importa.
    """
    rut = _qs(q, "rut")
    err = _first_error(
        valid_rut(rut, required=True),
        valid_iso_date(_qs(q, "desde"), field="desde"),
        valid_iso_date(_qs(q, "hasta"), field="hasta"),
    )
    if err:
        return HTTPStatus.BAD_REQUEST, {"error": err}

    rut_plain = rut.replace(".", "").strip()
    rut_base = rut_plain.split("-")[0]

    rows = scrape.fetch_consficha_por_rut(rut_base, rut)
    desde = _qs(q, "desde")
    hasta = _qs(q, "hasta")
    if desde:
        rows = [a for a in rows if (a.get("fecha") or "") >= desde]
    if hasta:
        rows = [a for a in rows if (a.get("fecha") or "") <= hasta]
    # Enriquecer con médico desde la ficha individual (N+1 HIS calls).
    # `enriquecer=0` desactiva; default ON para que la tabla muestre médico.
    if _qs(q, "enriquecer", "1") != "0":
        scrape.enrich_medico_por_ficha(rows)
    return HTTPStatus.OK, {"atenciones": rows, "rut": rut}


# ----------------- ficha individual -----------------

def atencion(q: Query) -> ApiResponse:
    """Ficha imprimible por id. Acepta `tipo=urgencia|ambulatorio`.

    El tipo es autoritativo: el frontend lo sabe (viene del listado donde
    el usuario clickeó). Sin fallback heurístico — si pedís ambulatorio de
    un id que solo existe en urgencia, da 404 en vez de "probemos el otro
    endpoint a ver qué sale". El fallback viejo enmascaraba ids inválidos
    y hacía 2 requests al HIS por cada "Ver ficha".

    Para compat con clientes que no mandan `tipo`, default = "urgencia"
    (sigue siendo el tipo más común).
    """
    aid = _qs(q, "id")
    tipo = _qs(q, "tipo", "urgencia").lower()
    err = _first_error(
        valid_numeric_id(aid, field="id", max_len=10, required=True),
        valid_fuente(tipo),  # mismo vocabulario que atenciones()
    )
    if err:
        return HTTPStatus.BAD_REQUEST, {"error": err}
    ficha = scrape.fetch_ficha(aid, tipo)
    # `Ficha` es un `TypedDict` (documentación) pero el handler espera un
    # `dict` plano para `json.dumps`. A runtime son la misma cosa; el `dict(…)`
    # satisface la invarianza de tipos de mypy sin costo real.
    return HTTPStatus.OK, dict(ficha)


# ----------------- health / métricas -----------------


def healthz() -> ApiResponse:
    """Estado del proxy + reachability del HIS. Útil para monitoreo local
    y para debuggear "¿por qué no carga?" sin tocar la consola del dev
    tools.

    Status 200 si el HIS responde (aunque sea con login page — eso implica
    que la red va). Status 503 si no hay conectividad (URLError → nuestro
    http_client devuelve 502). No chequea autenticación — para eso está
    `/api/status`.

    La sonda al HIS vive en `probes.py` (cacheada con TTL corto, default
    5s vía `HEALTHZ_CACHE_TTL`) para que un monitor que pollea cada
    segundo no dispare N sondas reales.

    Payload incluye:
      - `his`: dict con base URL, status de reachability y ms de latencia
      - `session`: cookies presentes (no decimos si es válida — eso implica
        una request extra, y es el trabajo de /api/status)
      - `cache`: cual catálogo cacheado, si es que hay
      - `metrics`: contadores por ruta (ver observability.metrics_snapshot)
    """
    his_status, his_latency_ms, his_reachable = probe_his()

    sess = get_session()
    has_cookies = sess.has_his_cookies()
    cache_servicios = sess.servicios_cache.get() is not None

    overall_ok = his_reachable
    status_code = HTTPStatus.OK if overall_ok else HTTPStatus.SERVICE_UNAVAILABLE

    return status_code, {
        "ok": overall_ok,
        "his": {
            "base": HIS_BASE,
            "status": his_status,
            "reachable": his_reachable,
            "latency_ms": his_latency_ms,
        },
        "session": {"has_cookies": has_cookies},
        "cache": {"servicios": cache_servicios},
        "metrics": metrics_snapshot(),
    }


# ----------------- diagnóstico de sincronización HIS -----------------

# Lista ordenada de probes que ejecuta `diag_sync`. Cada entrada describe
# un endpoint HIS que el flujo real toca: status check + warm-ups + POSTs
# de listado. La idea es que con todos juntos podamos ver si el HIS está
# devolviendo respuestas coherentes (todos autenticados o todos pidiendo
# login) o divergentes (algunos OK, otros redirigiendo a login) — la
# divergencia es el síntoma que el chip "Conectado" no detecta.
#
# Cada `_DiagProbe` es un dict simple, NO una clase, porque acá lo único
# que hacemos con cada uno es desempaquetar y pasar a `fetch_his`. Una
# clase agregaría boilerplate sin beneficio.


def _build_diag_probes() -> list[dict[str, Any]]:
    """Construye la lista de probes con un rango de fechas chico.

    Función separada para que los tests puedan pisar el rango sin
    capturar `time.strftime` global. Rango ayer→hoy minimiza carga al
    HIS y casi siempre devuelve resultados (== separa "tabla vacía
    legítima" de "tabla vacía por sesión muerta", aunque no
    perfectamente — el HIS local en fines de semana puede tener pocos
    registros).
    """
    yday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    today = time.strftime("%Y-%m-%d")
    form_amb = urlencode({
        "accion": "buscar_reporte_atenciones",
        "fdes": yday, "fhas": today, "print": "0", "serv": "0",
    }).encode("utf-8")
    form_urg = urlencode({
        "url_link2": "/hishhr/", "url_link": "/hishhr/",
        "fdes": yday, "fhas": today, "cboser": "",
        "dau": "", "app": "", "apm": "", "nom": "",
    }).encode("utf-8")
    form_ct = "application/x-www-form-urlencoded"
    return [
        # 1. status_check: idéntico al GET que usa /api/status. Si esto
        #    da "no login" el chip se pintaría verde.
        {
            "label": "status_check",
            "method": "GET",
            "path": ATENCIONES_FORM,
            "data": None,
            "extra": None,
        },
        # 2. ambulatorio_warmup: GET previo al validador. Si devuelve
        #    login pero (1) no, hay divergencia entre módulos.
        {
            "label": "ambulatorio_warmup",
            "method": "GET",
            "path": REPORTE_FORM,
            "data": None,
            "extra": None,
        },
        # 3. ambulatorio_validador: POST AJAX. Es el que la búsqueda real
        #    ejecuta — el más importante para detectar el bug del usuario.
        {
            "label": "ambulatorio_validador",
            "method": "POST",
            "path": REPORTE_LIST,
            "data": form_amb,
            "extra": {
                "Content-Type": form_ct,
                "Referer": HIS_BASE + "/reporte_atenciones_amb.php",
                "Origin": HIS_ORIGIN,
                "X-Requested-With": "XMLHttpRequest",
            },
        },
        # 4. urgencia_listado: POST clásico al reporte de urgencia.
        {
            "label": "urgencia_listado",
            "method": "POST",
            "path": ATENCIONES_LIST,
            "data": form_urg,
            "extra": {
                "Content-Type": form_ct,
                "Referer": HIS_BASE + "/ateurg022.php",
                "Origin": HIS_ORIGIN,
            },
        },
        # 5. consficha_warmup: GET al landing de búsqueda por RUT. Sin
        #    POST porque el POST necesitaría un RUT real (PHI).
        {
            "label": "consficha_warmup",
            "method": "GET",
            "path": CONSULTA_FICHA,
            "data": None,
            "extra": None,
        },
    ]


def _verdict(captures: list[CaptureMeta]) -> str:
    """Etiqueta global del set de probes.

    - `all_authed`: ningún probe parece login → todo OK (raro ver acá si
      reproducís el bug — significa que `is_login` igual no detecta el
      problema).
    - `all_login`: todos los probes parecen login → sesión muerta global,
      el chip debería estar amarillo (`/api/status` lo detectaría también).
    - `divergent`: algunos parecen login, otros no → **el bug del usuario**.
      Es la razón principal de existir de este endpoint.
    - `all_failed`: todos los fetches fallaron (proxy o red) — no
      podemos decir nada.
    """
    valid = [c for c in captures if c["status"] != 0]
    if not valid:
        return "all_failed"
    login_signals = [c["looks_login"] for c in valid]
    if all(login_signals):
        return "all_login"
    if not any(login_signals):
        return "all_authed"
    return "divergent"


def diag_sync() -> ApiResponse:
    """Sondea los endpoints HIS clave + captura bodies a disco.

    Útil cuando se reproduce el bug "chip Conectado verde + búsquedas
    devuelven vacío". Guarda los bodies redactados en `~/.his_reports/
    captures/` y devuelve un JSON con metadata estructural.

    Status siempre 200 — el endpoint reporta el estado, no falla. Si una
    sonda individual falla, queda como `status: 0` con `error` en su
    entrada.

    Sin caché, sin rate-limit — es solo para diagnóstico manual.
    """
    captures: list[CaptureMeta] = []
    for probe in _build_diag_probes():
        label = probe["label"]
        try:
            s, _, b = fetch_his(
                probe["path"],
                method=probe["method"],
                data=probe["data"],
                extra=probe["extra"],
                allow_origin_referer=True,
            )
        except Exception as exc:  # pragma: no cover — defensive
            # `fetch_his` ya captura URLError y devuelve 502 sintético;
            # este `except` cubre cualquier bug residual sin tumbar el
            # endpoint de diagnóstico.
            log.warning("diag_sync: probe %s falló: %s", label, exc)
            captures.append({
                "label": label,
                "method": probe["method"],
                "his_path": probe["path"],
                "status": 0,
                "bytes": 0,
                "sha256_short": "",
                "looks_login": False,
                "tr_count": 0,
                "table_count": 0,
                "no_data_marker": None,
                "snippet": f"<error: {exc}>"[:200],
                "saved_to": None,
            })
            continue
        captures.append(capture_body(
            label, probe["method"], probe["path"], s, b,
            looks_login=is_login(b),
        ))

    sess = get_session()
    return HTTPStatus.OK, {
        "ok": True,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "captures_dir": str(CAPTURE_DIR),
        "session": {
            "has_cookies": sess.has_his_cookies(),
            "cookie_names": sorted({c.name for c in sess.cookie_jar}),
        },
        "probes": [dict(c) for c in captures],
        "verdict": _verdict(captures),
    }
