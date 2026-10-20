"""Sesión del proceso: cookies del HIS + caches derivadas, en una sola clase.

Antes estaba todo como state módulo-level repartido:

    - `http_client.COOKIE_JAR`      (http.cookiejar.CookieJar)
    - `cache.SERVICIOS_CACHE`       (TTLCache)
    - `cache.invalidate_all()`      (coordina las dos cosas de arriba)

El acoplamiento era implícito — `logout()` limpiaba cookies Y cache porque
el autor lo recordaba, no porque la estructura lo exigiera. Una regresión
"si me olvido de invalidar el cache en logout, el próximo usuario ve los
servicios del anterior" esperaba a la próxima refactorización.

La clase `Session` hace explícito que cookies + caches forman una unidad:
`reset()` limpia ambos. El handler HTTP y cualquier código del dominio HIS
acceden vía `get_session()`, un singleton lazy (el server es single-tenant,
no justifica pasar sesión explícita por argumento en todos lados).

Para tests que necesitan aislamiento, `reset_default_session()` recrea la
instancia. Como los consumidores llaman `get_session()` en cada request,
la recreación se propaga transparentemente sin referencias stale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from http.cookiejar import CookieJar

from .cache import TTLCache
from .config import SERVICIOS_CACHE_TTL
from .types import Servicio

# Dominio de cookies HIS. Chequeamos por sufijo para tolerar subdominios
# (his.hospitalhangaroa.cl, www.hospitalhangaroa.cl, etc.).
_HIS_DOMAIN_SUFFIX = "hospitalhangaroa.cl"


@dataclass
class Session:
    """Estado mutable por proceso: cookies HIS + cache de servicios.

    Un Session por proceso (el server es single-user). La clase existe para
    que el acoplamiento cookies↔caches sea explícito: al invalidar sesión
    (logout, test setup) hay que tocar ambos, y antes eso estaba implícito.
    """
    cookie_jar: CookieJar = field(default_factory=CookieJar)
    servicios_cache: TTLCache[list[Servicio]] = field(
        default_factory=lambda: TTLCache[list[Servicio]](SERVICIOS_CACHE_TTL)
    )

    def has_his_cookies(self) -> bool:
        """¿Hay cookies del HIS (dominio *.hospitalhangaroa.cl)?

        Útil para `/api/status` y `/api/healthz` — dice si hay cookies sin
        hacer una request extra al HIS para validarlas.
        """
        return any(c.domain.endswith(_HIS_DOMAIN_SUFFIX)
                   for c in self.cookie_jar)

    def reset(self) -> None:
        """Limpia cookies + caches. Llamado por `/api/logout`.

        Aunque el catálogo de servicios no varía por usuario en la práctica,
        invalidarlo mantiene la semántica "al salir, todo se olvida" y evita
        bugs sutiles si mañana agregamos un cache que sí sea user-dependent.
        """
        self.cookie_jar.clear()
        self.servicios_cache.invalidate()


_default: Session | None = None


def get_session() -> Session:
    """Singleton lazy por proceso. La lazy-construction evita efectos de
    import (nada se toca hasta el primer acceso)."""
    global _default
    if _default is None:
        _default = Session()
    return _default


def reset_default_session() -> None:
    """Recrea el singleton. Para tests que necesitan aislamiento — llamar en
    `setUp` y los consumidores que hagan `get_session()` después verán la
    nueva instancia. Los cachés de referencias obtenidas antes de la
    recreación quedan stale (deseado: simula un proceso nuevo)."""
    global _default
    _default = Session()
