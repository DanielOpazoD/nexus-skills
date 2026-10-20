"""Flujo de login contra el HIS Hanga Roa.

El HIS Hanga Roa usa `POST /hishhr/acceso1.php` con `login=<rut-sin-dv>` y
`password=<clave>`. La respuesta NO es un 302 — es HTML con
`window.location='menu.php'`. Después hay que hacer un GET a `menu.php` para
estabilizar la sesión antes de poder consultar cualquier otra página.

Sobre el parsing HTML: usamos regex, como el resto del paquete. El HTML del
HIS es PHP classic consistente — action, method, e inputs siempre siguen el
mismo patrón. Antes usábamos `html.parser.HTMLParser` aquí (única excepción
en el paquete), pero era inconsistente con el resto y no aportaba seguridad
real: las páginas de login son generadas server-side con un template
simple. Los tests de auth ejercen la extracción con fixtures reales.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlencode, urlparse

from .config import (
    ATENCIONES_FORM,
    HIS_BASE,
    HIS_BASE_PATH,
    HIS_ORIGIN,
    HIS_PASS_ENV,
    HIS_USER_ENV,
    LOGIN_ROOT,
    MENU,
)
from .http_client import fetch_his, is_login
from .errors import HISError
from .session import get_session

log = logging.getLogger(__name__)


# ----------------- extracción del form (regex) -----------------

# Encuentra cada `<form ...>...</form>` con su atributo action. El cuerpo
# (entre `<form>` y `</form>`) se captura para poder scan-ear sus inputs.
# `re.IGNORECASE | re.DOTALL` porque HIS mezcla mayúsc/minúsc y los forms
# pueden tener newlines.
_FORM_RE = re.compile(
    r"<form\b([^>]*)>(.*?)</form>",
    re.IGNORECASE | re.DOTALL,
)

# Attr extractor ligero — tolera comillas simples, dobles o sin comillas.
def _attr(tag_attrs: str, name: str) -> str:
    m = re.search(
        rf"\b{re.escape(name)}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+))",
        tag_attrs, re.IGNORECASE,
    )
    if not m:
        return ""
    return m.group(1) or m.group(2) or m.group(3) or ""


# `<input ...>` — cada tag se busca individual dentro del body del form.
_INPUT_RE = re.compile(r"<input\b([^>]*)>", re.IGNORECASE)


def _parse_form(body: str, action_hint: str = "") -> dict[str, Any]:
    """Elige el form de login dentro del HTML y devuelve:

        {"action": str, "hidden": {name: value}, "inputs": set[str]}

    Prioridad, como el parser original:
      1. form con password + login
      2. form con password
      3. form con login
      4. form cuyo `action` contiene 'acceso1'
      5. primer form encontrado

    Si no hay forms, devuelve un shape vacío.
    """
    forms: list[dict[str, Any]] = []
    for m in _FORM_RE.finditer(body):
        tag_attrs, form_body = m.group(1), m.group(2)
        action = _attr(tag_attrs, "action")
        inputs: set[str] = set()
        hidden: dict[str, str] = {}
        for im in _INPUT_RE.finditer(form_body):
            a = im.group(1)
            name = _attr(a, "name")
            if not name:
                continue
            inputs.add(name)
            typ = (_attr(a, "type") or "text").lower()
            if typ == "hidden":
                hidden[name] = _attr(a, "value")
        forms.append({"action": action, "hidden": hidden, "inputs": inputs})

    if not forms:
        return {"action": "", "hidden": {}, "inputs": set()}

    # Prioridad
    for f in forms:
        if "password" in f["inputs"] and "login" in f["inputs"]:
            return f
    for f in forms:
        if "password" in f["inputs"]:
            return f
    for f in forms:
        if "login" in f["inputs"]:
            return f
    if action_hint:
        for f in forms:
            if action_hint.lower() in (f["action"] or "").lower():
                return f
    return forms[0]


def _resolve_action(raw: str) -> str:
    """Convierte un action relativo/absoluto en un path absoluto bajo
    `/hishhr/`, listo para pasar a `fetch_his`."""
    if not raw:
        return "/hishhr/acceso1.php"
    if raw.startswith("http"):
        u = urlparse(raw)
        return u.path + (("?" + u.query) if u.query else "")
    if raw.startswith("/"):
        return raw
    return HIS_BASE_PATH + "/" + raw.lstrip("./")


# ----------------- flow de login -----------------

def try_login(user: str, password: str) -> tuple[bool, str]:
    """Intenta loguearse al HIS. Devuelve `(ok, mensaje)`.

    Si `ok==False`, el mensaje es seguro de mostrar al usuario (no incluye
    la contraseña).
    """
    if not user or not password:
        return False, "faltan credenciales"
    # 1) Pedir la página de login (puebla cookies y obtiene el form).
    s, _, body = fetch_his(LOGIN_ROOT)
    if s in (429, 502, 503, 504): raise HISError(s, "Login temporalmente inaccesible")
    if s != 200:
        return False, f"no pude cargar el login (HTTP {s})"
    form = _parse_form(body.decode("utf-8", errors="ignore"),
                       action_hint="acceso1")
    action = _resolve_action(form["action"])

    # 2) Armar body — HIS Hanga Roa usa `login` y `password`, más los
    # hidden fields que traiga el form.
    data = dict(form["hidden"])
    data["login"] = user
    data["password"] = password
    body_bytes = urlencode(data).encode("utf-8")
    log.info("login: POST %s con campos: %s", action, sorted(data.keys()))
    s2, _, body2 = fetch_his(
        action,
        method="POST",
        data=body_bytes,
        extra={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": HIS_ORIGIN,
            "Referer": HIS_BASE + "/",
            "X-Requested-With": None,  # explicit: no AJAX
        },
        allow_origin_referer=True,
    )
    if s2 in (429, 502, 503, 504): raise HISError(s2, "Login temporalmente inaccesible")
    ck_names = sorted({c.name for c in get_session().cookie_jar
                       if c.domain.endswith("hospitalhangaroa.cl")})
    log.info("login: POST→HTTP %s, cookies=%s", s2, ck_names or "(ninguna)")

    # Fallo duro: HIS devuelve login con alert o sin window.location.
    body2_txt = body2.decode("utf-8", errors="ignore")
    if "window.location" not in body2_txt and "usuarioLogeado" not in body2_txt:
        m = re.search(r"alert\(['\"]([^'\"]{3,200})", body2_txt)
        if m:
            return False, f"HIS dice: {m.group(1)}"
        return False, "credenciales rechazadas (sin redirección post-login)"

    # 3) Warm-up: el flujo normal del navegador tras acceso1.php es abrir
    # menu.php, que termina de establecer la sesión.
    s3, _, _ = fetch_his(
        MENU, extra={"Referer": HIS_BASE + "/acceso1.php"},
        allow_origin_referer=True,
    )
    log.info("login: menu warm-up→HTTP %s", s3)

    # 4) Verificar contra una página que el usuario sí puede ver.
    s4, _, body4 = fetch_his(
        ATENCIONES_FORM,
        extra={"Referer": HIS_BASE + "/menu.php"},
        allow_origin_referer=True,
    )
    if s4 in (429, 502, 503, 504): raise HISError(s4, "Verificación temporalmente inaccesible")
    on_login = is_login(body4)
    no_perm = b"No tiene permisos" in body4
    log.info("login: verificar ateurg022→HTTP %s, on_login=%s, no_perm=%s",
             s4, on_login, no_perm)
    if s4 == 200 and not on_login:
        return True, "ok"
    return False, f"sesión no persistió (POST {s2}, verify {s4})"


def auto_login_if_env() -> None:
    """Si `HIS_USER` y `HIS_PASS` están en env, intenta login al arrancar."""
    if HIS_USER_ENV and HIS_PASS_ENV:
        ok, msg = try_login(HIS_USER_ENV, HIS_PASS_ENV)
        if ok:
            log.info("auto-login: sesión establecida desde HIS_USER/HIS_PASS")
        else:
            log.warning("auto-login FALLÓ: %s", msg)
