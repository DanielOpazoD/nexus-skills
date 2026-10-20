"""Capa de scraping: sabe de URLs del HIS, warm-ups, forms y parsing.

Propósito:
  - Aislar el conocimiento *mecánico* del HIS (qué endpoint hace qué, qué
    form se debe poblar, qué warm-up hace falta antes del POST) del
    *orquestador* (`api.py`), que se limita a validar inputs y componer la
    respuesta JSON.
  - Que agregar un nuevo listado del HIS sea una función nueva aquí, no
    una modificación de `api.py`.
  - Que `api.py` deje de referenciar URLs, content-types ni pair-counting.

Cada función toma parámetros ya validados (strings simples) y devuelve la
estructura parseada. Lanza `HISError` si el HIS responde mal (sesión
expirada, permisos, 5xx tras retries).

Invariante: aquí NO se valida input del usuario — eso corre en `api.py`
antes de llamar. Esta capa confía en su caller.
"""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TypedDict
from urllib.parse import quote, urlencode

from . import _diagnostics  # noqa: F401 — expuesto a tests via `scrape._diagnostics`
from ._diagnostics import (
    diagnose_empty,
    diagnose_medico_missing,
    log_enrich_summary,
    warn_if_suspicious,
)
from .config import (
    ATENCIONES_FORM,
    ATENCIONES_LIST,
    CONSULTA_FICHA,
    FICHA_AMB,
    FICHA_URG,
    HIS_BASE,
    HIS_ORIGIN,
    REPORTE_FORM,
    REPORTE_LIST,
)
from .errors import HISError
from .http_client import fetch_his, is_login
from .parsers import (
    count_pairs,
    parse_atenciones_023,
    parse_consficha_resultados,
    parse_ficha_purg,
    parse_reporte_atenciones_amb,
    parse_servicios,
)
from .types import AtencionRow, Ficha, Servicio

# Re-exports para compat con tests que accedían a los helpers como
# `scrape._warn_if_suspicious` etc. La lógica vive en `_diagnostics`; acá
# exponemos alias bajo el nombre "privado" antiguo para evitar churn de
# tests. Nuevos tests deberían usar `_diagnostics.*` directamente.
_diagnose_empty = diagnose_empty
_diagnose_medico_missing = diagnose_medico_missing
_warn_if_suspicious = warn_if_suspicious
_log_enrich_summary = log_enrich_summary
# Acceso explícito al módulo para tests que quieran la redacción o las
# constantes internas (ej. `scrape._diagnostics._redact_phi`).
__all__ = [  # noqa: RUF022 — orden narrativo, no alfabético
    "fetch_servicios",
    "fetch_atenciones_ambulatorio",
    "fetch_atenciones_urgencia",
    "fetch_consficha_por_rut",
    "fetch_ficha",
    "enrich_medico_por_ficha",
]

log = logging.getLogger(__name__)

# Content-Type común a todos los POST-form del HIS.
_FORM_CT = "application/x-www-form-urlencoded"


def _check(status: int, body: bytes) -> None:
    """Traduce respuesta HIS a `HISError` si algo anda mal.

    - Body que se ve como login page → 401 AUTH_REQUIRED.
    - Status distinto de 200 → ese status + mensaje genérico.
    Si todo OK, no hace nada.
    """
    if is_login(body):
        raise HISError(HTTPStatus.UNAUTHORIZED, "AUTH_REQUIRED")
    if status != HTTPStatus.OK:
        raise HISError(status, f"HIS {status}")


def _fetch_his_form_post(
    post_url: str,
    *,
    warmup: str,
    form: dict[str, str],
    referer: str,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    """Warm-up GET + POST urlencoded al HIS. Helper común de los listados.

    Pattern que los 3 fetchers de listado comparten:
      1. GET `warmup` para que la sesión esté "calentita" (establece cookies
         intermedias / referer coherente). Status NO se chequea — si el
         warm-up falla, el POST suele devolver el error real y `_check` lo
         captura ahí.
      2. POST `post_url` con `form` urlencoded + headers estándar
         (`Content-Type` form, `Referer` indicado, `Origin` del HIS). El
         caller puede pasar `extra_headers` para agregar cosas específicas
         (ej. `X-Requested-With` para endpoints que esperan AJAX).
      3. `_check(status, body)` traduce 401/login a AUTH_REQUIRED y !=200 al
         status HIS correspondiente.

    Devuelve el body del POST. Parser + diagnósticos quedan del lado del
    caller (cada listado tiene un parser distinto).

    Extraer este helper elimina ~15 líneas duplicadas por fetcher y hace
    que agregar un 4.º listado sea una función de ~10 líneas (form + parser
    + diagnose) en vez de ~25.
    """
    fetch_his(warmup)  # warm-up sin chequeo de status (ver docstring)
    headers: dict[str, str | None] = {
        "Content-Type": _FORM_CT,
        "Referer": HIS_BASE + referer,
        "Origin": HIS_ORIGIN,
    }
    if extra_headers:
        headers.update(extra_headers)
    s, _, b = fetch_his(
        post_url, method="POST",
        data=urlencode(form).encode("utf-8"),
        extra=headers,
        allow_origin_referer=True,
        read_only=True,
    )
    _check(s, b)
    return b


# ----------------- catálogo de servicios -----------------

def fetch_servicios() -> list[Servicio]:
    """Catálogo de especialidades (ambulatorio). Viene del `<select>` del
    form de `reporte_atenciones_amb.php`."""
    s, _, b = fetch_his(REPORTE_FORM)
    _check(s, b)
    return parse_servicios(b)


# ----------------- listados -----------------

def fetch_atenciones_ambulatorio(desde: str, hasta: str,
                                  servicio: str) -> list[AtencionRow]:
    """POST al validador AJAX de INFORME ATENCIONES AMBULATORIAS.

    Flujo real 2026-04 (cambió vs. versiones previas):
      1. GET a `reporte_atenciones_amb.php` — warm-up de sesión y referer.
         También sirve para el catálogo de servicios (`parse_servicios`).
      2. POST a `app/View/informesAmbulatorio/reportesAmb/php/validador.php`
         con `accion=buscar_reporte_atenciones`. El form ya NO hace POST a
         sí mismo; lo dispara jQuery `.load` desde el JS del módulo.

    Campos requeridos: `accion`, `fdes`, `fhas`, `print` (0 = inline HTML),
    `serv` (0 = todos). Sin `serv` el endpoint responde con la tabla vacía.

    Devuelve la tabla parseada (10 columnas, incluye `medico`). Warm-up +
    POST + `_check` están centralizados en `_fetch_his_form_post`.
    """
    # Normalización crítica: el validador del HIS devuelve tabla vacía (600
    # bytes, solo header) si `serv` viene vacío. Para "todos" necesita
    # literalmente `serv=0`. El frontend manda `servicio=""` cuando el
    # usuario elige "Todos" (`<option value="">`) — acá lo mapeamos para
    # que el contrato "sin filtro = todos" funcione sin depender del
    # frontend.
    serv = servicio or "0"
    body = _fetch_his_form_post(
        REPORTE_LIST,
        warmup=REPORTE_FORM,
        # El JS del form mapea el <select name="cboser"> al parámetro `serv`
        # del POST. `servicio` viene ya validado por api.py (numérico).
        form={"accion": "buscar_reporte_atenciones",
              "fdes": desde, "fhas": hasta,
              "print": "0", "serv": serv},
        referer="/reporte_atenciones_amb.php",
        # El endpoint exige (o al menos espera) AJAX — jQuery lo agrega por
        # defecto. Sin esto, algunas versiones devuelven redirect.
        extra_headers={"X-Requested-With": "XMLHttpRequest"},
    )
    rows = parse_reporte_atenciones_amb(body)
    _diagnose_empty("ambulatorio",
                    {"desde": desde, "hasta": hasta, "servicio": servicio},
                    body, rows)
    _warn_if_suspicious("ambulatorio", rows)
    return rows


def fetch_atenciones_urgencia(desde: str, hasta: str,
                               servicio: str) -> list[AtencionRow]:
    """POST al legacy `ateurg023.php` (DAU/urgencia, 11 columnas, sin
    médico). Mismo patrón warm-up + form-POST que el ambulatorio."""
    body = _fetch_his_form_post(
        ATENCIONES_LIST,
        warmup=ATENCIONES_FORM,
        form={"url_link2": "/hishhr/", "url_link": "/hishhr/",
              "fdes": desde, "fhas": hasta, "cboser": servicio,
              "dau": "", "app": "", "apm": "", "nom": ""},
        referer="/ateurg022.php",
    )
    rows = parse_atenciones_023(body)
    _diagnose_empty("urgencia",
                    {"desde": desde, "hasta": hasta, "servicio": servicio},
                    body, rows)
    _warn_if_suspicious("urgencia", rows)
    return rows


def fetch_consficha_por_rut(rut_base: str, rut_full: str) -> list[AtencionRow]:
    """Historial del paciente vía `consficha000.php`.

    El HIS exige `op=""` (vacío) y RUT SIN dígito verificador (rut_base).
    `rut_full` se usa solo para el parser (que cruza la columna RUT de la
    tabla resultado contra el input del usuario).

    Caso particular de este endpoint: el warm-up y el POST apuntan al MISMO
    path (`consficha000.php` se sirve a sí mismo el form en GET y procesa
    el form en POST). No es distinto de los otros dos, solo que pasa a ser
    el mismo URL.
    """
    body = _fetch_his_form_post(
        CONSULTA_FICHA,
        warmup=CONSULTA_FICHA,
        form={"url_link2": "/hishhr/", "op": "", "ficha": "",
              "rut": rut_base, "pasaporte": ""},
        referer="/consficha000.php",
    )
    rows = parse_consficha_resultados(body, rut=rut_full)
    # `consficha` no trae médico en la tabla — se enriquece después via
    # `enrich_medico_por_ficha`. Por eso `_warn_if_suspicious` tiene el
    # chequeo de médico gated a `fuente == "ambulatorio"`: acá aplican
    # solo idCuenta-duplicado y fecha-vacía.
    _warn_if_suspicious("consficha", rows)
    return rows


# ----------------- enriquecimiento de listados -----------------

# Cap del enriquecimiento: listados con más de N filas no abrimos todas las
# fichas — sería muchísima latencia (N+1 HIS roundtrips). El usuario casi
# siempre mira las últimas atenciones; las más viejas quedan sin médico.
_ENRICH_MEDICO_CAP = 60
_ENRICH_PARALLEL = 6


def enrich_medico_por_ficha(rows: list[AtencionRow],
                             cap: int = _ENRICH_MEDICO_CAP) -> list[AtencionRow]:
    """Rellena `medico` en filas que no lo traen, abriendo la ficha individual.

    El listado `consficha000.php` (búsqueda por RUT) no incluye médico en
    su tabla — solo Fecha / Tipo / Servicio / link. Para mostrarlo en la
    UI, abrimos cada ficha con N roundtrips paralelos.

    - Filas con `medico` no vacío se respetan (no re-abrimos ficha).
    - Errores al abrir una ficha individual se ignoran (medico queda "").
    - Se enriquecen hasta `cap` filas — las demás mantienen `medico` vacío
      (son las más antiguas si la lista viene ordenada por fecha descendente).
    - Paralelismo limitado para no saturar al HIS.

    Al terminar, loguea resumen (ok / fallo-parseo / error-HIS) agrupado por
    `tipoFicha`. Esto hace visible cuando una variante (típicamente
    `ambulatorio`/PAMB0005) se parsea peor que la otra — síntoma común de
    un layout HIS nuevo que `find_medico` no cubre todavía.

    Muta las filas in place y también devuelve la lista por conveniencia.
    """
    # Import local: ThreadPoolExecutor solo lo usamos acá y no vale la pena
    # cargarlo en el top-level para tests que no lo ejercitan.
    from concurrent.futures import ThreadPoolExecutor

    targets = [r for r in rows[:cap]
               if not (r.get("medico") or "").strip()
               and r.get("idCuenta") and r.get("tipoFicha")]
    if not targets:
        return rows

    # Outcome por fila: "ok" (médico extraído), "empty" (ficha OK pero sin
    # médico parseable), "error" (fetch falló). El resumen final ayuda a
    # detectar el caso "ambulatorio nunca matchea" sin spam por-fila en
    # producción.
    outcomes: list[tuple[str, str]] = []  # [(tipoFicha, outcome), ...]

    def _one(row: AtencionRow) -> tuple[AtencionRow, str, str]:
        tipo = str(row.get("tipoFicha") or "")
        try:
            ficha = fetch_ficha(str(row["idCuenta"]), tipo)
            m = (ficha.get("atencionMeta") or {}).get("medico") or ""
            return row, m, "ok" if m else "empty"
        except HISError as e:
            log.info("enrich médico falló id=%s tipo=%s: %s",
                     row.get("idCuenta"), tipo, e)
            return row, "", "error"
        except Exception:
            log.exception("enrich médico error inesperado id=%s",
                          row.get("idCuenta"))
            return row, "", "error"

    with ThreadPoolExecutor(max_workers=_ENRICH_PARALLEL) as ex:
        for row, medico, status in ex.map(_one, targets):
            if medico:
                row["medico"] = medico
            outcomes.append((str(row.get("tipoFicha") or ""), status))

    _log_enrich_summary(outcomes)
    return rows


# ----------------- ficha individual -----------------

# Umbral heurístico: una ficha HIS real tiene decenas de pares
# `<b>LABEL:</b>`. Menos de 5 ⇒ o es una página semivacía (permisos, id
# inexistente) o un HTML desconocido. En ese caso tratamos el 200 como 404.
_MIN_PAIRS_FICHA = 5


class _FichaConfig(TypedDict):
    """Parámetros dependientes del tipo de ficha (AMB / URG).

    Consolida en un solo lugar las 3 decisiones por-tipo que antes vivían
    dispersas como ternarios: qué path del HIS usar, qué flag de print y
    qué Referer. Agregar un tipo nuevo = una entrada más en `_FICHA_CONFIG`.
    """
    path: str
    # `print=1` vs `noprint=1` — NO es cosmético, define si el HIS incluye
    # el campo médico. Ver `_FICHA_CONFIG` abajo.
    print_mode: str
    referer: str


# Config per-tipo de ficha. Hallazgo 2026-04 importante:
#
#   - URG (PURG0005): `print=1` sirve un layout plano `<b>LABEL:</b> VALOR`
#     con SV incluidos — ideal para parsear.
#   - AMB (PAMB0005): `print=1` sirve una vista recortada SIN médico
#     (pensada para impresión, que por diseño omite el campo editable). La
#     vista completa — que es la que el propio HIS linkea desde
#     consficha000 y reporte_atenciones_amb — vive en `noprint=1`, e
#     incluye el médico como `<input readonly>` o `<select>` (las variantes
#     que `find_medico` ya sabe extraer).
#     Bug reportado: "en búsqueda por RUT no se reconoce el médico de
#     atenciones ambulatorias". Causa: pedíamos `print=1` y el HIS
#     respondía sin médico; ahora alineamos con el param que usa el propio
#     HIS y el parser encuentra el campo.
#
# Referer alineado al tipo: PAMB viene del form ambulatorio y PURG del form
# urgencia. Antes usábamos siempre `ateurg022.php` — el HIS parece tolerarlo
# para PURG, pero en PAMB algunas versiones responden con layout recortado
# (sin médico) cuando el Referer no coincide. Defensivo.
_FICHA_CONFIG: dict[str, _FichaConfig] = {
    "ambulatorio": {
        "path": FICHA_AMB,
        "print_mode": "noprint=1",
        "referer": "/reporte_atenciones_amb.php",
    },
    "urgencia": {
        "path": FICHA_URG,
        "print_mode": "print=1",
        "referer": "/ateurg022.php",
    },
}


def fetch_ficha(aid: str, tipo: str) -> Ficha:
    """Fetch + parse de una ficha imprimible.

    `tipo` es autoritativo: el caller (listado previo) sabe si la atención
    es ambulatoria o de urgencia, y el endpoint no adivina más. Si el HIS
    devuelve una ficha con < 5 pares (caso típico: id inexistente para ese
    tipo), lanzamos 404.

    Devuelve la estructura tipada + campos `idCuenta` y `tipoFicha`.
    """
    cfg = _FICHA_CONFIG.get(tipo)
    if cfg is None:
        valid = ", ".join(sorted(_FICHA_CONFIG.keys()))
        raise HISError(HTTPStatus.BAD_REQUEST,
                       f"tipo debe ser uno de: {valid}")
    url = f"{cfg['path']}?id={quote(aid)}&{cfg['print_mode']}"
    s, _, b = fetch_his(url,
                        extra={"Referer": HIS_BASE + cfg["referer"]},
                        allow_origin_referer=True)
    if is_login(b):
        raise HISError(HTTPStatus.UNAUTHORIZED, "AUTH_REQUIRED")
    if b"No tiene permisos" in b:
        raise HISError(HTTPStatus.FORBIDDEN, "NO_PERMISOS")
    if s != HTTPStatus.OK:
        raise HISError(s, f"HIS {s}")
    if count_pairs(b) < _MIN_PAIRS_FICHA:
        raise HISError(HTTPStatus.NOT_FOUND, "FICHA_NO_ENCONTRADA")

    ficha = parse_ficha_purg(b)
    ficha["idCuenta"] = aid
    ficha["tipoFicha"] = tipo
    _diagnose_medico_missing(aid, tipo, b, ficha)
    return ficha
