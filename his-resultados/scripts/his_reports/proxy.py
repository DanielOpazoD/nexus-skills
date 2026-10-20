"""Helpers para el reverse-proxy `/hishhr/*`.

Extraído de `handler.py`: la mecánica I/O (leer `rfile`, escribir `wfile`)
queda allá, pero las transformaciones puras sobre headers viven acá. Así
se pueden testear sin sockets.

Dos cosas pasan a toda response que el proxy retorna del HIS al cliente:

  1. **Hop-by-hop headers se descartan** (`Connection`, `Keep-Alive`,
     `Transfer-Encoding`, etc. — ver `HOP_HEADERS` en config). Re-enviar
     estos rompe keepalive del cliente.

  2. **`Location` se reescribe** para sacar el origin del HIS. Si el HIS
     redirige a `https://his.hospitalhangaroa.cl/foo`, queremos que el
     browser vea solo `/foo` (relativo a nuestro proxy) — si no, el
     cliente se saltaría el proxy en el siguiente request.

La reescritura es regex simple porque el HIS solo sirve desde un único
hostname (configurado en `HIS_ORIGIN`). Si algún día hubiera múltiples
hosts, esto pasa a ser una tabla — pero hoy es overkill.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from urllib.parse import urlparse

from .config import HIS_ORIGIN, HOP_HEADERS

# Hostname del HIS (ej. `his.hospitalhangaroa.cl`). Se deriva una vez al
# importar — HIS_ORIGIN viene de config y no cambia en runtime.
_HIS_HOST = urlparse(HIS_ORIGIN).hostname or ""

# Matchea `http://<host>` o `https://<host>` al inicio de un valor Location.
# Lo reemplazamos por cadena vacía → lo que queda es path relativo.
_LOCATION_ORIGIN_RE = re.compile(r"https?://" + re.escape(_HIS_HOST))


def rewrite_location(value: str) -> str:
    """Saca el origin del HIS de un `Location: ...` si está presente.

    Ejemplos:
      `https://his.hospitalhangaroa.cl/ambu/form.php` → `/ambu/form.php`
      `http://his.hospitalhangaroa.cl/`               → `/`
      `/ya-es-relativo`                                → `/ya-es-relativo`
      `https://otra.com/x`                             → `https://otra.com/x`
        (otro host — no tocamos; no es nuestro, lo dejamos pasar)
    """
    return _LOCATION_ORIGIN_RE.sub("", value)


def filtered_response_headers(
    headers: Iterable[tuple[str, str]],
) -> Iterator[tuple[str, str]]:
    """Itera sobre headers de response filtrando lo que no debe pasar.

      - Descarta headers hop-by-hop (case-insensitive match contra
        `HOP_HEADERS` de config).
      - Reescribe `Location` con `rewrite_location`.
      - El resto pasa tal cual.

    No yield `Content-Length` — el handler lo recalcula al final porque
    `rewrite(body, ct)` en http_client puede cambiar el tamaño del body.
    """
    for k, v in headers:
        k_lower = k.lower()
        if k_lower in HOP_HEADERS:
            continue
        if k_lower == "content-length":
            # Se recalcula afuera; si lo mandamos ahora + otro después,
            # algunos clientes se rompen por header duplicado.
            continue
        if k_lower == "location":
            v = rewrite_location(v)
        yield k, v
