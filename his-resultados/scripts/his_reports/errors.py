"""Excepciones propias de la capa HIS/API.

Motivación: antes los helpers de red escribían el error directamente al
`BaseHTTPRequestHandler` (`self._json(401, ...)`) y devolvían `None`. Eso
acoplaba lógica de negocio al socket y hacía la ruta de error difícil de
seguir. Ahora los helpers lanzan `HISError` y el dispatcher lo traduce a
JSON en un único punto.

`HISError.status` usa `int` en vez de `HTTPStatus` porque `BaseHTTPRequestHandler.
send_response` acepta tanto int como `HTTPStatus.IntEnum` — no necesitamos
forzar el tipo acá.
"""
from __future__ import annotations


class HISError(Exception):
    """Error con status HTTP + mensaje serializable como JSON."""

    __slots__ = ("message", "status")

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HIS {status}: {message}")
        self.status = status
        self.message = message
