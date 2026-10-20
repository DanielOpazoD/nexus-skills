"""Observabilidad del scraping HIS: diagnósticos, warnings, redacción PHI.

Separado de `scrape.py` por tres razones:

1. **Foco**: scrape.py queda con la narrativa "URLs del HIS + fetchers".
   Las funciones de diagnóstico son ~130 líneas que viven en ciclos de
   vida distintos (se escriben una vez y casi no cambian, vs. fetchers
   que cambian cuando el HIS cambia).
2. **Testing**: este módulo tiene su propio `tests/test_diagnostics.py`,
   lo que facilita añadir casos cubriendo solo observabilidad sin tener
   que mezclarlos con tests de fetchers (mocks HTTP, etc.).
3. **PHI safety**: la redacción de datos sensibles en logs vive acá.
   Centralizarla evita que un nuevo diagnóstico se agregue en scrape.py
   y olvide pasar el log por el redactor — un riesgo real y silencioso.

Contratos:
  - Todas las funciones `_log_*` y `_diagnose_*` terminan en un
    `log.info/warning/exception` — ningún efecto secundario más.
  - Todos los snippets que puedan contener PHI (nombres, RUTs, fragmentos
    de ficha) DEBEN pasar por `_redact_phi` antes de loggearse.
  - El logger es `his_reports.scrape` — mantenemos el namespace anterior
    para que filtros de log (ej. `LOGLEVEL=DEBUG` en
    `tests/__init__.py`) sigan funcionando sin cambios.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import AtencionRow, Ficha

# Mantenemos el namespace `his_reports.scrape` para que los filtros de log
# existentes no tengan que actualizarse. `_diagnostics` es un detalle de
# organización interno, no un surface de logs separado.
log = logging.getLogger("his_reports.scrape")

# ---------------- Redacción PHI (Patient Health Information) ----------------
#
# Qué redactamos:
#   - RUT chileno en cualquier formato habitual:
#       12345678-9, 12.345.678-9, 12345678K (sin guión en variantes viejas)
#   - Nombres propios en MAYÚSCULAS (>=2 palabras consecutivas de ≥2
#     letras) — excepción: palabras después de "DR." o "DRA." se
#     preservan, porque el nombre del médico es información operativa
#     (útil para debugging del parser de médico, y no es PHI del paciente).
#
# Qué NO redactamos (intencionalmente):
#   - Labels HTML comunes: "MEDICO:", "PACIENTE:", "RUT:", "FECHA:"...
#     Son útiles en el log para ver estructura; su valor SÍ se redacta si
#     sigue en mayúsculas.
#   - Fechas — no son PHI per se, y ayudan a correlacionar eventos.
#
# Alcance limitado:
#   - La redacción es "best effort", no criptográfica. Un nombre en
#     minúsculas o con formato raro puede escaparse. El objetivo es
#     reducir riesgo, no eliminarlo — los logs deberían ser limitados en
#     tamaño y revisados manualmente si se exportan.
#   - Nunca invocar redacción en paths críticos donde el texto original
#     es necesario para lógica (parsers, validadores). Es solo para logs.

# RUT chileno: 7-8 dígitos opcionales con puntos + guión + dígito/K.
_RUT_RE = re.compile(
    r"\b\d{1,2}\.?\d{3}\.?\d{3}[-.]?[\dkK]\b",
)
# Nombre propio "AAA BBB" (2+ palabras en mayúsculas de ≥2 letras). Acepta
# acentos (ÁÉÍÓÚÑ). El `(?!\.)` final evita matchear títulos abreviados
# como "DR." o "DRA." que están en mayúsculas pero terminan en punto.
# La extensión (?:\s+[A-Z...]{2,})+ permite capturar nombres de 2-5 palabras.
_NOMBRE_MAYUSCULAS_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,4}\b",
)
# Protección del "DR./DRA. NOMBRE": si aparece así, queremos mantener el
# nombre del médico en claro (no es PHI del paciente, y ayudar a
# diagnosticar bugs del parser de médico vale la exposición limitada).
# Marcamos esas secuencias con un placeholder único que luego
# reinsertamos tras la redacción genérica.
_DR_SEQ_RE = re.compile(
    r"\bDR[A]?\.?\s+[A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){0,4}\b",
)


def _redact_phi(text: str) -> str:
    """Devuelve `text` con RUT y nombres de paciente reemplazados.

    Preserva "DR./DRA. NOMBRE" (médico — no es PHI del paciente y ayuda
    a diagnosticar parseo del campo médico).

    Idempotente: llamar 2x sobre el mismo string da el mismo resultado.
    """
    if not text:
        return text
    # Paso 1: proteger "DR./DRA. NOMBRE" sacándolos a placeholders.
    drs: list[str] = []

    def _park(match: re.Match[str]) -> str:
        drs.append(match.group(0))
        return f"\x00DR{len(drs) - 1}\x00"

    parked = _DR_SEQ_RE.sub(_park, text)
    # Paso 2: redactar RUT y nombres genéricos.
    redacted = _RUT_RE.sub("[RUT]", parked)
    redacted = _NOMBRE_MAYUSCULAS_RE.sub("[NOMBRE]", redacted)

    # Paso 3: reinsertar los DR.
    def _unpark(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        return drs[idx]

    return re.sub(r"\x00DR(\d+)\x00", _unpark, redacted)


# ---------------- Diagnóstico de listados ----------------

_NO_DATA_MARKERS = (
    "sin resultados",
    "no existen datos",
    "no se encontraron",
    "no hay registros",
    "no se han encontrado",
)
_TR_RE = re.compile(rb"<tr[^>]*>", re.IGNORECASE)
_TABLE_RE = re.compile(rb"<table[^>]*>", re.IGNORECASE)


def diagnose_empty(fuente: str, filtros: dict[str, str], body: bytes,
                   rows: list[AtencionRow]) -> None:
    """Log de diagnóstico cuando un listado devuelve 0 filas con body no trivial.

    El objetivo es que la próxima vez que el HIS cambie la estructura de la
    tabla (o devuelva un mensaje distinto al esperado), el log tenga la
    info mínima para distinguir "no hay datos reales" de "parser descartó
    todo". Sin acceso al HIS no podemos adivinar el formato — esta función
    hace la parte fácil: registrar lo que vimos.
    """
    if rows:
        return
    body_size = len(body)
    tr_count = len(_TR_RE.findall(body))
    table_count = len(_TABLE_RE.findall(body))
    text_lower = body[:8000].decode("utf-8", errors="ignore").lower()
    no_data = next((m for m in _NO_DATA_MARKERS if m in text_lower), None)
    log.info(
        "scrape %s 0 filas — size=%d tablas=%d filas_tr=%d filtros=%s "
        "no_data_marker=%r",
        fuente, body_size, table_count, tr_count, filtros, no_data,
    )
    # Si hay tablas y varias filas pero 0 filas resultantes, el parser está
    # descartando todo — muestrear la primera fila con datos para ver por
    # qué (ej. número de celdas, contenido de celda 0 / CTACTE).
    if tr_count > 1 and no_data is None:
        _log_row_samples(fuente, body)


_SAMPLE_ROW_RE = re.compile(
    rb"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL,
)
_SAMPLE_CELL_RE = re.compile(
    rb"<t[hd][^>]*>(.*?)</t[hd]>", re.IGNORECASE | re.DOTALL,
)
_SAMPLE_TAG_RE = re.compile(rb"<[^>]+>|&nbsp;")
_SAMPLE_WS_RE = re.compile(rb"\s+")

# Cap corto de chars por celda: el log solo necesita ver *estructura* (¿es
# una fila con RUT + nombre?, ¿cuántas columnas?). Nombres y RUTs
# completos son PHI; los acortamos + redactamos.
_SAMPLE_CELL_MAXLEN = 25


def _log_row_samples(fuente: str, body: bytes, max_rows: int = 3) -> None:
    """Muestra las primeras N filas con su conteo de celdas y celda 0.

    Los valores de cada celda pasan por `_redact_phi` y se truncan a
    `_SAMPLE_CELL_MAXLEN` chars — suficiente para ver qué tipo de dato
    hay en cada columna (fecha vs. id vs. nombre) pero poco para exponer
    datos del paciente.
    """
    rows_iter = _SAMPLE_ROW_RE.finditer(body)
    logged = 0
    for i, m in enumerate(rows_iter):
        if logged >= max_rows:
            break
        cells = _SAMPLE_CELL_RE.findall(m.group(1))
        if not cells:
            continue
        clean = []
        for c in cells[:6]:
            v = _SAMPLE_TAG_RE.sub(b" ", c)
            v = _SAMPLE_WS_RE.sub(b" ", v).strip()
            # Redactar antes de truncar: si el valor es un nombre
            # "JUAN PEREZ SOTO", truncar a 25 chars puede dejar "JUAN PEREZ SOTO"
            # legible. Redactar → "[NOMBRE]" → más corto y sin PHI.
            s = _redact_phi(v.decode("utf-8", errors="ignore"))
            clean.append(s[:_SAMPLE_CELL_MAXLEN])
        log.info("scrape %s fila %d: %d celdas, primeras=%s",
                 fuente, i, len(cells), clean)
        logged += 1


# ---------------- Warning de listados sospechosos ----------------

# Umbral mínimo de filas para disparar warnings: con 1-2 filas cualquier
# patrón "100% sin médico" es ruido (una ficha puede legítimamente no
# tener médico asignado). A partir de 3 filas, 100% vacío ya es señal.
_SUSPICIOUS_MIN_ROWS = 3


def warn_if_suspicious(fuente: str, rows: list[AtencionRow]) -> None:
    """WARN cuando el listado parsea bien (>0 filas) pero tiene patrones
    que sugieren regresión de parser o cambio de layout HIS.

    Señales cubiertas (complementarias a `diagnose_empty`, que solo cubre
    el caso "0 filas"):

    - **idCuenta duplicado total**: todas las filas comparten el mismo
      id. Síntoma típico de una regex que capturó más de lo que debía y
      está copiando el primer valor en todas las filas. Muy útil atrapar
      esto acá — sin este check, la UI muestra N filas aparentemente
      distintas y es casi imposible notar el bug.
    - **Médico 100% vacío en listados AMB**: el listado ambulatorio del
      HIS incluye médico en la columna 8; si un lote completo llega
      vacío, o el HIS cambió la estructura o el parser regresionó. No se
      aplica a urgencia (`ateurg023.php` no trae médico en su tabla por
      diseño) ni a consficha (se enriquece después).
    - **Fecha 100% vacía**: indicador de que la columna de fecha dejó de
      parsearse — la UI se vuelve inútil sin fechas.

    Umbral mínimo (`_SUSPICIOUS_MIN_ROWS`=3): con pocas filas, cualquier
    patrón "100%" es ruido estadístico y no una regresión.

    `fuente` se usa para decidir qué señales aplican (urgencia no tiene
    médico en el listado) y para el mensaje del log.
    """
    if len(rows) < _SUSPICIOUS_MIN_ROWS:
        return
    # Duplicado total de idCuenta: calculado una sola vez, barato.
    ids = {str(r.get("idCuenta") or "") for r in rows}
    if len(ids) == 1 and "" not in ids:
        log.warning(
            "scrape %s: %d filas pero todas con mismo idCuenta=%r — "
            "probable regresión de parser (regex capturó más de lo "
            "esperado)",
            fuente, len(rows), next(iter(ids)),
        )
    # Médico 100% vacío: solo tiene sentido para listados que deberían
    # traer médico. `ateurg023.php` (urgencia) no lo trae por diseño.
    if fuente == "ambulatorio":
        medicos = [(r.get("medico") or "").strip() for r in rows]
        if not any(medicos):
            log.warning(
                "scrape %s: %d filas pero médico vacío en TODAS — "
                "probable cambio de layout HIS (columna 8 movida) o "
                "regresión de parser",
                fuente, len(rows),
            )
    # Fecha 100% vacía: aplica a todos los listados.
    fechas = [(r.get("fecha") or "").strip() for r in rows]
    if not any(fechas):
        log.warning(
            "scrape %s: %d filas pero fecha vacía en TODAS — "
            "parser de columna de fecha no está funcionando",
            fuente, len(rows),
        )


# ---------------- Diagnóstico de ficha sin médico ----------------

# Snippet cercano a cualquier ocurrencia de "medic" (con o sin tilde).
# Trabajamos sobre el body DECODIFICADO a str para que el `é` UTF-8 no
# rompa el character class — en bytes, "MÉDICO" son 7 bytes con la
# secuencia `\xc3\x89`, y un `[\xc3\x89e]` solo consume 1 byte, dejando
# el otro colgado.
_MEDICO_SNIPPET_RE = re.compile(
    r".{0,80}m[ée]dic.{0,200}", re.IGNORECASE | re.DOTALL,
)
# Señal secundaria: ¿hay <input> o <select> con "medic" en sus atributos?
# Si SÍ pero el parser no extrajo el médico, es casi seguro un layout
# nuevo que `find_medico` no cubre — más útil que "no encontré nada".
_MEDICO_CONTROL_HINT_RE = re.compile(
    r"<(?:input|select)[^>]*m[ée]dic[^>]*>", re.IGNORECASE,
)
# Cap de snippet más conservador que antes (eran 300 chars): los
# snippets cercanos al médico pueden contener anamnesis, diagnóstico o
# el nombre del paciente. Con 150 chars y redacción encima, el
# riesgo/beneficio mejora sustancialmente.
_SNIPPET_MAXLEN = 150


def diagnose_medico_missing(aid: str, tipo: str, body: bytes,
                            ficha: Ficha) -> None:
    """Log cuando la ficha viene sin médico — ayuda a debuggear variantes
    nuevas del HIS sin exponer la ficha completa (respeta PII).

    Loguea:
      - Tamaño total del body (para distinguir ficha vacía vs. completa).
      - Total de ocurrencias de "medic" en el body.
      - Si hay `<input>`/`<select>` con "medic" en atributos (señal fuerte
        de que el layout sí tiene el campo pero el parser no lo reconoce).
      - Snippets de las 2 primeras ocurrencias — REDACTADOS (`_redact_phi`)
        y cortos (`_SNIPPET_MAXLEN` chars). El objetivo es ver HTML
        estructural alrededor del campo médico (tags, atributos), no el
        contenido clínico del paciente.
    """
    medico = (ficha.get("atencionMeta") or {}).get("medico") or ""
    if medico:
        return
    # Decode a str para que el regex vea los acentos correctamente. Límite
    # prudente (60K chars) para no generar logs gigantes en caso de ficha
    # rara que pese MB.
    body_str = body[:60000].decode("utf-8", errors="ignore")
    snippets = _MEDICO_SNIPPET_RE.findall(body_str)
    control_hint = _MEDICO_CONTROL_HINT_RE.search(body_str)
    # Cada snippet: redactar PHI → truncar. No al revés: si truncamos
    # antes, un nombre cortado a la mitad puede burlar el regex de
    # redacción (ej. "JUAN PER" no matchea `[A-Z]{2,}\s[A-Z]{2,}`).
    sample = [_redact_phi(s)[:_SNIPPET_MAXLEN] for s in snippets[:2]]
    control_match = (
        control_hint.group(0)[:200] if control_hint else None
    )
    log.info(
        "ficha %s id=%s sin médico — body=%d bytes, ocurrencias de 'medic'=%d,"
        " control_match=%r, snippets=%s",
        tipo, aid, len(body), len(snippets), control_match, sample,
    )


# ---------------- Resumen de enriquecimiento ----------------

def log_enrich_summary(outcomes: list[tuple[str, str]]) -> None:
    """Resumen post-enriquecimiento, agrupado por tipoFicha.

    Salida esperada (happy path): `enrich médico: ambulatorio 5/5 ok`.
    Salida con problema: `enrich médico: ambulatorio 0/5 (empty=5)` —
    señal de que ninguna ficha AMB devolvió médico (probablemente
    `find_medico` no matchea un layout nuevo). Severidad WARNING cuando
    más de la mitad quedan sin médico, INFO en caso normal.
    """
    from collections import Counter

    if not outcomes:
        return
    # Counter[(tipo, status)] = count.
    tally: Counter[tuple[str, str]] = Counter(outcomes)
    tipos = sorted({t for t, _ in outcomes})
    for tipo in tipos:
        ok = tally[(tipo, "ok")]
        empty = tally[(tipo, "empty")]
        err = tally[(tipo, "error")]
        total = ok + empty + err
        # "parseables" = fichas que el HIS nos dio (ok + empty); excluye
        # errores de red/auth. Si 0 de N parseables dieron médico, algo
        # en find_medico no cubre este layout.
        parseables = ok + empty
        bad = parseables > 0 and ok == 0
        msg = (f"enrich médico: {tipo or '?'} {ok}/{total} ok "
               f"(empty={empty}, error={err})")
        if bad:
            log.warning("%s — ninguna ficha %s produjo médico: posible "
                        "variante de layout no cubierta por find_medico",
                        msg, tipo or "?")
        else:
            log.info(msg)
