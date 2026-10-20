"""Extracción del médico tratante de la ficha — estrategias en cascada.

El HIS tiene varias formas de exponer el médico. En orden de canonicidad:

  1. **PURG0005** (urgencia): label directa `<b>MÉDICO:</b> NOMBRE`.
  2. **PAMB0005** (ambulatorio): a veces usa variantes como "MEDICO ATIENDE",
     "MEDICO TRATANTE", o incluso labels no canónicas. El match fuzzy cubre
     eso pero tiene que EXCLUIR "DIAG. MÉDICO COMPLEMENTARIO" y similares.
  3. **PAMB0005 (noprint 2026-04)**: en la vista `noprint=1` no hay
     <b>LABEL:</b> con el valor inline — el médico queda como
     `<input name="medico" value="...">` (o con prefijos HIS como
     `cboMedico`, `nombreMedico`, `medico_atiende`, o usando `id=` en vez
     de `name=`). El orden de atributos no está garantizado, así que
     probamos ambos (name/id antes de value y viceversa).
  4. **PAMB0005 variante select**: algunas versiones renderizan el médico
     como `<select name="medico">…<option selected>NOMBRE</option></select>`.
     Mismas reglas de prefijo/atributo que la estrategia 3.
  5. **Label + sibling element**: layouts tipo
     `<div><b>MÉDICO:</b></div><div>DR. XXX</div>` o
     `<td>MÉDICO:</td><td>DR. XXX</td>` (también sin `<b>`, como tabla
     plana). `extract_pairs` pierde estos casos porque el `</div>` cierra
     antes de que aparezca el valor; acá escaneamos los siguientes ~600
     chars y tomamos el primer texto no-trivial después de descartar tags
     vacíos y labels de otros campos.
  6. **Value cercano**: buscar "MÉDICO" en el texto y capturar el siguiente
     `value="..."` en ventana de 500 chars.
  7. **DR./DRA. cercano**: buscar "MÉDICO" en el texto y capturar el
     primer "DR." / "DRA." + nombre en mayúsculas dentro de ventana
     acotada. Cubre layouts HIS donde el médico aparece como texto plano
     sin input/select ni `<b>LABEL:</b>`. La ventana es corta (~400 chars)
     para evitar capturar el director del hospital del pie de página.
  8. **Bloque de firma**: en PAMB el HIS cierra la ficha con
     `____ FIRMA MÉDICO ____` + nombre en mayúsculas en la línea siguiente
     (sin prefijo "DR./DRA."). Es el ÚNICO lugar donde aparece el médico
     en algunos layouts ambulatorios. El nombre va ANTES del RUT
     (un identificador numérico) — el guard rechaza el RUT y rescata el
     nombre. Esta estrategia es la última porque cuando el HIS expone el
     médico como `<input>` o label inline, las anteriores son más precisas.

Las estrategias se separan para que el régression test pueda ejercitar
cada una con fixtures mínimas (`purg0005_sample`, `pamb_medico_label_fuzzy`,
`pamb0005_sample` con `<input>`, `pamb_medico_cbo_prefix`, etc.).
"""
from __future__ import annotations

import re

# Labels HIS conocidas. El match es case-sensitive (el dict de pairs ya viene
# uppercase), así que con/sin tilde están ambas listadas.
_MEDICO_LABELS = (
    "MÉDICO", "MEDICO",
    "MÉDICO ATIENDE", "MEDICO ATIENDE",
    "MÉDICO TRATANTE", "MEDICO TRATANTE",
    "MÉDICO RESPONSABLE", "MEDICO RESPONSABLE",
    "MÉDICO CITA", "MEDICO CITA",
    "MÉDICO ATENCIÓN", "MEDICO ATENCION",
    "PROFESIONAL", "FACULTATIVO", "DOCTOR",
)
# Cualquier label con MEDIC pero que NO sea sobre diagnósticos/indicaciones.
# El `\b` al inicio es importante: evita matchear "PARAMEDICO",
# "RADIOMEDICO", "PREMEDICO" que contienen "MEDIC" pero no son el rol
# del médico tratante.
_MEDIC_RE = re.compile(r"\bM[ÉE]DIC", re.IGNORECASE)
_MEDIC_EXCLUDE_RE = re.compile(r"DIAG|INDICAC|COMENT", re.IGNORECASE)

# Patrón del identificador del campo médico (en `name=` o `id=`). Acepta:
#   - Prefijo HIS opcional (`cbo`, `txt`, `sel`, `nombre`, `nom`, `dr`, etc.)
#     de hasta 10 letras, con un `_` opcional después.
#   - Stem `medic` (con o sin tilde en é).
#   - Sufijo opcional (`_atiende`, `_tratante`, `o`, etc.).
#
# Esto cubre los nombres observados en HIS chilenos: `medico`,
# `medico_atiende`, `medicoTratante`, `nomMedico`, `nombreMedico`,
# `cboMedico`, `txtMedico`, `drMedico`, etc. Sigue rechazando fields que
# no contienen "medic" en el nombre.
#
# Rechazos explícitos vía negative lookahead: `paramedico`,
# `radiomedico`, `premedico`. Estos comparten el stem "medic" pero NO son
# el médico tratante — paramédico es el técnico, radiomedico/premédico no
# son roles clínicos habituales. Sin el lookahead, un HIS con
# `<input name="paramedico_atiende">` sería capturado como si fuera el
# médico, con consecuencias serias (confusión de roles en el reporte). El
# lookahead evalúa en la posición inicial del match (justo después del
# `"=\s*["']?` del atributo), así que no afecta identificadores que sólo
# coincidan parcialmente (ej. `nombreMedico`, `cboMedico`, `medico`).
_NAME_MEDICO_PATTERN = (
    r'(?!(?:para|radio|pre)m)'  # rechaza paramedico/radiomedico/premedico
    r'[a-z]{0,10}_?m[ée]dic[oa]?[_a-z]*'
)
# Fallback input: <input name|id="medico..." value="NOMBRE">. El atributo
# identificador puede ser `name` o `id` (algunos layouts sólo usan `id`).
# Dos regex por el orden de atributos — HTML no garantiza un orden
# particular.
_MEDICO_ATTR = r'(?:name|id)\s*=\s*["\']?' + _NAME_MEDICO_PATTERN
_INPUT_NAME_THEN_VALUE_RE = re.compile(
    r'<input[^>]*\b' + _MEDICO_ATTR +
    r'[^"\'>\s]*["\']?'
    r'[^>]*\bvalue\s*=\s*["\']([^"\']{3,200})["\']',
    re.IGNORECASE,
)
_INPUT_VALUE_THEN_NAME_RE = re.compile(
    r'<input[^>]*\bvalue\s*=\s*["\']([^"\']{3,200})["\']'
    r'[^>]*\b' + _MEDICO_ATTR,
    re.IGNORECASE,
)
# <select name|id="medico...">…<option selected>…NOMBRE…</option></select>.
# Capturamos solo el bloque <select> con identificador médico y dentro la
# option marcada como selected (el atributo puede ser `selected`,
# `selected=""` o `selected="selected"`).
_SELECT_MEDICO_RE = re.compile(
    r'<select[^>]*\b' + _MEDICO_ATTR +
    r'[^"\'>\s]*["\']?[^>]*>(.*?)</select>',
    re.IGNORECASE | re.DOTALL,
)
_OPTION_SELECTED_RE = re.compile(
    r'<option[^>]*\bselected\b[^>]*>([^<]{3,200})</option>',
    re.IGNORECASE,
)
# Label "MEDICO:" en cualquier tag inline común — no sólo `<b>`. Algunas
# fichas PAMB llegan como tabla plana con `<td>Médico:</td>` o usan
# `<label>` / `<strong>` / `<span>` indistintamente. La backreference `\1`
# asegura que el cierre matchee el tag de apertura.
# El `\b` antes de `m[ée]dic` rechaza "paramedico:" / "radiomedico:" como
# labels: esas palabras contienen el stem pero no son el rol del médico
# tratante.
_INLINE_TAG = r"(b|strong|th|td|label|span|p)"
_MEDICO_LABEL_RE = re.compile(
    r"<" + _INLINE_TAG + r"[^>]*>\s*[^<]*\bm[ée]dic[^<:]*:\s*</\1>",
    re.IGNORECASE,
)
# Chunk de un tag de apertura/cierre. Los descartamos para leer texto plano.
_TAG_CHUNK_RE = re.compile(r"<[^>]+>")
# Si en el sibling aparece otra label `<tag>LABEL:</tag>` (mismo conjunto
# de tags inline), acortamos la ventana hasta justo antes de ella: no
# queremos confundirnos con el valor del campo siguiente.
_NEXT_INLINE_LABEL_RE = re.compile(
    r"<" + _INLINE_TAG + r"[^>]*>\s*[^<:]{2,80}:\s*</\1>",
    re.IGNORECASE,
)
# Fallback general: buscar "MÉDICO" (o "MEDICO") como texto y tomar el
# próximo value/texto no trivial dentro de los siguientes ~500 chars.
# `\b` a ambos lados rechaza "paramedico" / "radiomedico" / cualquier
# palabra compuesta que termine en -medico pero no sea el rol clínico. Sin
# el `\b` inicial, la estrategia 6 (value cercano) se dispararía para
# `<input name="paramedico" value="TECNICO...">` aunque la estrategia 3
# ya lo haya rechazado — defense in depth.
_MEDICO_WORD_RE = re.compile(r"\bm[ée]dic[oa]\b", re.IGNORECASE)
_NEXT_VALUE_RE = re.compile(
    r'value\s*=\s*["\']([^"\']{3,200})["\']', re.IGNORECASE,
)
# Estrategia 7: nombre que empieza con DR./DRA. en mayúsculas. Debe
# aparecer cerca del texto "médico" para no capturar al director del
# hospital del pie de página. El patrón requiere DR/DRA + espacio + al
# menos una palabra en mayúsculas (con acentos) + apellido en mayúsculas
# — esto filtra falsos positivos como "DR. sábado" (texto cualquiera) y
# captura nombres reales.
_DR_NAME_RE = re.compile(
    r"\bDR[A]?\.?\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\.]*"
    r"(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\.]*){1,4}",
)
# Mínimo parecer nombre propio: al menos dos runs de letras separados por
# espacio, o una sola palabra de ≥3 letras (ej. "DR. SOTO"). Evita basura
# tipo "NaN", "-", "0".
_LOOKS_LIKE_NAME_RE = re.compile(
    r"[A-Za-zÁÉÍÓÚÑáéíóúñ][A-Za-zÁÉÍÓÚÑáéíóúñ\.\s]{2,}", re.UNICODE,
)
# Estrategia 8: label "FIRMA MÉDICO" (y variantes "FIRMA DEL MÉDICO",
# "FIRMA Y TIMBRE MÉDICO"). En PAMB el HIS suele cerrar la ficha con
# este bloque seguido del nombre del médico tratante en mayúsculas y, una
# línea más abajo, su RUT — patrón clásico de pie de firma.
#
# El sufijo `:?` cubre layouts con/sin colon. El sufijo `[oa]?` cubre
# "FIRMA MÉDICA" (femenino) cuando el HIS lo concuerda con DRA.
_FIRMA_MEDICO_RE = re.compile(
    r"firma(?:\s+(?:del|y\s+timbre(?:\s+del)?))?\s+m[ée]dic[oa]\s*:?",
    re.IGNORECASE,
)
# Nombre en MAYÚSCULAS (mínimo 2 palabras de ≥3 letras): el HIS escribe el
# firmante siempre en upper. Tildes y eñes aceptadas; rechaza líneas con
# dígitos (RUT, fechas) gracias al guard posterior `_looks_like_medico`.
# El `{2,}` en la primera palabra evita falsos positivos como "AA BB".
_UPPER_NAME_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÑ]{3,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,4}\b",
)

# Cap de longitud para un nombre de médico legítimo. Nombres reales del HIS
# observados van de "DR. SOTO" (8) a "DRA. ESTEFANÍA CONTRERAS VALDÉS" (~32).
# Damos margen hasta 80 — más allá es casi seguro contaminación (campo
# médico vacío en HIS que se pega con el siguiente valor, típicamente
# resultados de laboratorio o indicaciones).
_MEDICO_MAX_LEN = 80
# Caracteres que NO deberían aparecer en un nombre — su presencia es señal
# de contaminación con otros campos (resultados de lab tienen "/", "%",
# "<>"; valores numéricos tienen dígitos; URLs tienen "@").
_MEDICO_REJECT_CHARS = set("0123456789/%$@<>+={}[]")


# Títulos médicos aceptables como primera palabra del nombre. Cualquier
# otra "palabra" de exactamente 2 letras sin punto al inicio es sospechosa
# de ser una sigla de examen ("HG", "TP", "VHS", "PCR", etc.) — y la
# capa 5 del finder recorta esas siglas del texto crudo cuando hay
# contaminación tipo "HG GLICOSILADA 11.8 …" (el regex `_LOOKS_LIKE_NAME_RE`
# para en el primer dígito y deja "HG GLICOSILADA" como falso positivo).
_MEDICO_TITLE_TOKENS = {"DR", "DR.", "DRA", "DRA.", "DOC", "DOC."}


def _looks_like_medico(s: str) -> bool:
    """Validador final del candidato a médico.

    Aplicado al borde de TODAS las estrategias de `find_medico` antes de
    retornar — defensa en profundidad para que un cambio de layout HIS o
    una ficha con campo médico vacío contaminado por otro valor no se
    cuele a la UI. Sin esta validación, valores como
    "HG GLICOSILADA 11.8 BLANCOS 8000 HTO 44 PLAQUETAS …" (resultados de
    lab pegados al campo médico cuando éste está en blanco) terminaban
    en la columna "Médico" del listado por RUT.

    Reglas (ANY de éstas falla → no es un médico):
      - Longitud fuera de [3, 80]: nombres reales viven entre "DR. X"
        (5) y "DRA. NOMBRE COMPUESTO APELLIDO APELLIDO" (~40).
      - Contiene dígitos o caracteres especiales (`/`, `%`, `<`, `>`…):
        casi exclusivos de resultados de lab o IDs.
      - Menos de 2 palabras alfabéticas: descarta "C" sola (observado
        en producción 2026-04-29).
      - Primera palabra de ≤3 letras sin punto y NO un título médico
        conocido (`DR`, `DRA`, `DOC`): descarta siglas de examen
        ("HG GLICOSILADA", "TP CONTROL", "VHS NORMAL"). Es una pérdida
        aceptable: nombres reales cuya primera palabra es de 2-3 letras
        son rarísimos, y si aparece un caso legítimo el HIS suele
        servirlo con prefijo "DR." que evita esta regla.

    Acepta:
      - "DR. SOTO" → "DR." es título conocido
      - "DANIEL OPAZO" → primera palabra 6 letras
      - "DRA. ESTEFANÍA CONTRERAS VALDÉS" → "DRA." es título

    Rechaza:
      - "" / "C" / "—"
      - "HG GLICOSILADA 11.8 BLANCOS 8000 …" (dígitos + length)
      - "HG GLICOSILADA" (primera palabra "HG" — 2 letras sin punto, no
        es título médico)
      - "ALBUMINA 3.5 OC NORMAL" (dígitos)
      - "ANALISIS / LABORATORIO" (carácter `/`)
    """
    s = s.strip()
    if not (3 <= len(s) <= _MEDICO_MAX_LEN):
        return False
    if any(c in _MEDICO_REJECT_CHARS for c in s):
        return False
    # Tokenización con conteo de letras para rechazar palabras puramente
    # de puntuación (ej. "—") aunque "tengan length".
    words = [w for w in s.split()
             if sum(1 for c in w if c.isalpha()) >= 2]
    if len(words) < 2:
        return False
    # Primera palabra: ≥4 letras alfabéticas, o un título médico conocido.
    first = words[0]
    first_letters = sum(1 for c in first if c.isalpha())
    return not (first_letters < 4 and first.upper() not in _MEDICO_TITLE_TOKENS)


def find_medico(pairs: dict[str, str], html_str: str) -> str:
    """Busca el médico tratante con estrategias en orden de confianza:

    1. Labels `<b>…:</b>` explícitas conocidas.
    2. Cualquier key del dict que contenga "MEDIC" (excluye diagnósticos
       para no capturar "DIAG. MÉDICO COMPLEMENTARIO" ni similares).
    3. Un `<input name|id="medico…" value="…">` en el HTML crudo.
    4. Un `<select name|id="medico">` con `<option selected>…</option>`.
    5. Label "MEDICO:" en cualquier tag inline común (`<b>`, `<td>`,
       `<label>`, etc.) seguida de texto en un elemento sibling — layout
       de tabla o de divs separados.
    6. Fallback por value: "MÉDICO" como texto seguido de un `value="…"`
       cercano.
    7. Fallback por prefijo de nombre: "MÉDICO" en texto y luego
       "DR./DRA." + nombre en mayúsculas dentro de ventana de 400 chars
       (más corta para no capturar firma/pie de página).

    Devuelve string vacío si ninguna estrategia encuentra el médico —
    nunca `None`, para que el frontend no tenga que hacer `?? ""`.

    **Guard final**: cada candidato pasa por `_looks_like_medico` antes de
    retornar. Si una estrategia produce algo que no parece un nombre
    (longitud excesiva, dígitos, una sola palabra), seguimos a la
    siguiente estrategia. Sin esta validación, una ficha HIS con el
    campo médico vacío contaminado por el valor del campo siguiente
    (típicamente resultados de lab) ponía "HG GLICOSILADA 11.8 BLANCOS
    …" en la columna "Médico" del listado por RUT — bug observado
    2026-04-29.
    """
    # 1) Labels explícitas.
    for label in _MEDICO_LABELS:
        v = pairs.get(label)
        if v and _looks_like_medico(v):
            return v.strip()
    # 2) Fuzzy: label que contiene MEDIC.
    for k, v in pairs.items():
        if not v:
            continue
        if (_MEDIC_RE.search(k)
                and not _MEDIC_EXCLUDE_RE.search(k)
                and _looks_like_medico(v)):
            return v.strip()
    # 3) <input name|id="medico..." value="...">
    for regex in (_INPUT_NAME_THEN_VALUE_RE, _INPUT_VALUE_THEN_NAME_RE):
        m = regex.search(html_str)
        if m:
            cand = m.group(1).strip()
            if _looks_like_medico(cand):
                return cand
    # 4) <select name|id="medico">…<option selected>NOMBRE</option></select>
    sel = _SELECT_MEDICO_RE.search(html_str)
    if sel:
        # group(1) = contenido del <select> (único grupo capturador;
        # `_MEDICO_ATTR` usa `(?:name|id)` non-capturing).
        opt = _OPTION_SELECTED_RE.search(sel.group(1))
        if opt:
            nombre = opt.group(1).strip()
            # Descarta placeholders comunes del HIS.
            if (nombre
                    and not re.match(r"^(seleccione|--|\.\.\.|sin|n/a)",
                                       nombre, re.IGNORECASE)
                    and _looks_like_medico(nombre)):
                return nombre
    # 5) <b|td|label|...>MEDICO:</…> + texto en el próximo elemento (div
    #    vecino, próximo <td>, ...). Útil cuando el HIS separa label y
    #    valor en elementos distintos y `extract_pairs` pierde el valor
    #    porque `</div>` lo trunca.
    nombre = _find_medico_sibling_text(html_str)
    if nombre and _looks_like_medico(nombre):
        return nombre
    # 6) Fallback por value: palabra "MÉDICO" como texto y un value cercano.
    for m in _MEDICO_WORD_RE.finditer(html_str):
        start = m.end()
        window = html_str[start:start + 500]
        val_m = _NEXT_VALUE_RE.search(window)
        if val_m:
            nombre = val_m.group(1).strip()
            if _looks_like_medico(nombre):
                return nombre
    # 7) Fallback por prefijo "DR./DRA.": buscar un nombre de doctor en
    #    ventana acotada después del texto "médico". Cubre layouts que no
    #    usan input/select/label reconocible. Ventana corta (400 chars)
    #    para no capturar el director del hospital que suele aparecer en
    #    el footer de TODAS las fichas — ése está a muchos miles de
    #    chars del contexto "médico tratante".
    for m in _MEDICO_WORD_RE.finditer(html_str):
        start = m.end()
        window = html_str[start:start + 400]
        dr_m = _DR_NAME_RE.search(window)
        if dr_m:
            nombre = dr_m.group(0).strip()
            if _looks_like_medico(nombre):
                return nombre
    # 8) Bloque de firma "FIRMA MÉDICO" + nombre en mayúsculas en la línea
    #    siguiente (sin prefijo DR./DRA.). Es el cierre canónico de la
    #    ficha PAMB en algunos layouts del HIS y, cuando el médico no
    #    aparece como `<input>` ni label inline, es el ÚNICO lugar donde se
    #    expone el firmante. Después del nombre suele venir el RUT, que el
    #    guard `_looks_like_medico` rechaza por contener dígitos.
    nombre = _find_medico_firma(html_str)
    if nombre and _looks_like_medico(nombre):
        return nombre
    return ""


def _find_medico_sibling_text(html_str: str) -> str:
    """Estrategia 5: label "MEDICO:" + texto en el próximo elemento.

    Acepta la label dentro de cualquier tag inline común (`<b>`, `<td>`,
    `<th>`, `<label>`, `<strong>`, `<span>`, `<p>`) — no sólo `<b>`. Esto
    cubre fichas-tabla donde la label es un `<td>Médico:</td>` sin `<b>`.

    Escanea ~600 chars después de cada label que haga match con MEDIC (y
    no con DIAG/INDICAC). Recorta la ventana antes del próximo
    `<tag>LABEL:</tag>` para no invadir otro campo. Descarta tags y
    whitespace, se queda con la primera secuencia que parece nombre propio.
    """
    for m in _MEDICO_LABEL_RE.finditer(html_str):
        label = m.group(0)
        # No nos interesan DIAG./INDICAC./COMENT. que también contienen MEDIC.
        if _MEDIC_EXCLUDE_RE.search(label):
            continue
        start = m.end()
        window = html_str[start:start + 600]
        # Truncar antes del próximo `<tag>LABEL:</tag>` (mismo conjunto de
        # tags inline) para no pegar el valor del campo siguiente.
        nb = _NEXT_INLINE_LABEL_RE.search(window)
        if nb:
            window = window[:nb.start()]
        # Quitar tags, normalizar whitespace.
        text = _TAG_CHUNK_RE.sub(" ", window)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        cand = _LOOKS_LIKE_NAME_RE.search(text)
        if not cand:
            continue
        nombre = cand.group(0).strip().strip(".").strip()
        # Descarta falsos positivos típicos.
        low = nombre.lower()
        if not nombre or len(nombre) < 3:
            continue
        if low.startswith(("seleccione", "--", "sin medico",
                             "sin médico", "n/a")):
            continue
        return nombre
    return ""


def _find_medico_firma(html_str: str) -> str:
    """Estrategia 8: nombre del firmante tras la label "FIRMA MÉDICO".

    Layout PAMB observado en el HIS:

        ____________________________
        FIRMA MÉDICO
        NOMBRE DEL PROFESIONAL
        RUT DEL PROFESIONAL

    El HTML puede envolver esto en `<center>`, `<div>`, `<p><b>...</b></p>`
    o `<table>`, separando label y nombre con `<br>` o `</p><p>`. La
    estrategia escanea hasta 400 chars después de cada match de
    `_FIRMA_MEDICO_RE`, descarta tags y normaliza whitespace, y devuelve la
    primera secuencia en MAYÚSCULAS con ≥2 palabras.

    No exige prefijo "DR./DRA." — el HIS NO lo agrega en el bloque de firma
    (acompaña el nombre con el RUT en la línea siguiente, y la sigla queda
    fuera). El guard `_looks_like_medico` filtra el RUT por sus dígitos.
    """
    for m in _FIRMA_MEDICO_RE.finditer(html_str):
        start = m.end()
        window = html_str[start:start + 400]
        # Cortar antes de la próxima label inline para no invadir otros
        # campos (defensa por si "FIRMA MÉDICO" aparece dentro de otra
        # sección, ej. un comentario).
        nb = _NEXT_INLINE_LABEL_RE.search(window)
        if nb:
            window = window[:nb.start()]
        text = _TAG_CHUNK_RE.sub(" ", window)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        # Buscar el primer nombre en mayúsculas (sin requerir DR./DRA.).
        cand = _UPPER_NAME_RE.search(text)
        if not cand:
            continue
        return cand.group(0).strip()
    return ""
