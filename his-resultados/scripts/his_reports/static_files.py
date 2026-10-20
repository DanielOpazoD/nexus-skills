"""Sirve archivos estáticos desde `WEB_ROOT`.

Extraído de `handler.py` como función pura — el resultado de resolver un
path es `(status, body, content_type)`, sin tocar `wfile`. Así:

  1. La lógica path → archivo es testeable sin montar un server (el test de
     path-traversal es un unittest directo, no requiere sockets).

  2. `handler.py` queda con solo la mecánica HTTP (escribir headers + body).
     Separación clara: "qué servir" vs "cómo mandarlo".

El chequeo de seguridad clave es `os.path.normpath` + `startswith(root)`:
si el path resuelto no queda adentro de `WEB_ROOT`, devolvemos 403. Esto
previene `GET /../../../etc/passwd` — clásico de servers ingenuos.

MIME types: lista curada. No usamos `mimetypes.guess_type` porque el mapa
que quiero para esta app es chico y no quiero que el .svg dependa de la
configuración del sistema (en algunas máquinas minimal, `guess_type`
devuelve None para varios tipos comunes).
"""
from __future__ import annotations

import os
from http import HTTPStatus

# Sin `application/*` genérico acá — para lo que no está mapeado, el handler
# cae a `application/octet-stream` afuera. Eso es deliberado: si aparece un
# tipo nuevo que debería servirse como texto, quiero que falle visiblemente
# (descarga en vez de render) y obligue a agregarlo acá.
_STATIC_CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

_DEFAULT_CTYPE = "application/octet-stream"


# Resultado del resolve: `(status, body, content_type)`. Si status != 200,
# body es b"" y content_type es "" — el handler no manda body en esos casos.
ResolvedStatic = tuple[int, bytes, str]


def resolve_static(path: str, root: str) -> ResolvedStatic:
    """Resuelve un request path a un archivo dentro de `root`.

    Devuelve:
      - `(200, body, content_type)` si el archivo existe y es legible.
      - `(403, b"", "")` si el path intenta salirse de `root` (traversal).
      - `(404, b"", "")` si el archivo no existe.

    `path` puede empezar con `/` o no (lo normalizamos con `lstrip`). Si
    apunta a un directorio, intentamos servir `index.html` adentro.
    """
    # `os.path.normpath` colapsa `..` y `.` — después chequeamos que el
    # resultado siga bajo `root`. Normalizamos `root` también para que la
    # comparación sea estable (ej. `/app/` vs `/app`).
    root_norm = os.path.normpath(root)
    fs = os.path.normpath(os.path.join(root_norm, path.lstrip("/")))
    # Sufijo del separator asegura que `/appfoo` no matchee como prefix de
    # `/app` — sin esto, `/../appfoo/secret` pasaría el check si `/app` es
    # prefix literal. Agregamos sep solo si no estaba ya.
    prefix = root_norm if root_norm.endswith(os.sep) else root_norm + os.sep
    if not (fs == root_norm or fs.startswith(prefix)):
        return HTTPStatus.FORBIDDEN, b"", ""
    if os.path.isdir(fs):
        fs = os.path.join(fs, "index.html")
    if not os.path.isfile(fs):
        return HTTPStatus.NOT_FOUND, b"", ""
    ctype = _STATIC_CTYPES.get(os.path.splitext(fs)[1].lower(), _DEFAULT_CTYPE)
    with open(fs, "rb") as f:
        body = f.read()
    return HTTPStatus.OK, body, ctype
