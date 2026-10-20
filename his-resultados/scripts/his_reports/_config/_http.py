"""Config del cliente HTTP y caches: timeouts, retries, TTLs, headers."""
from __future__ import annotations

import os

# Headers "hop-by-hop" que no deben reenviarse upstream→downstream, más
# algunos que rompen la UI si pasan intactos (frame-options / CSP).
HOP_HEADERS = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "x-frame-options", "content-security-policy",
    "content-security-policy-report-only", "frame-options",
    "content-length", "content-encoding",
})

# Headers de seguridad que se mandan en cada respuesta servida por la app
# (estáticos + API JSON). Defensa en profundidad: si un escape falla o una
# dependencia se compromete, estos headers reducen el daño.
#
# - CSP: limita qué orígenes pueden cargar recursos. `rsms.me` está en la
#   allowlist porque servimos la tipografía Inter desde ahí; si mañana se
#   cambia a self-host, se puede borrar de `style-src` y `font-src`. `data:`
#   en `font-src` tolera que algunos @font-face de Inter embeban fallback.
#   `frame-ancestors 'none'` previene embebidos (clickjacking); el HIS
#   original tampoco se embebe en la app.
# - X-Content-Type-Options: evita que el browser "adivine" el MIME y ejecute
#   un .json como HTML si el server manda el ctype equivocado.
# - Referrer-Policy no-referrer: nunca filtrar el path (ej. `?rut=…`) a
#   recursos externos. En esta app no hay recursos externos después de boot,
#   pero es un default correcto para cualquier link que aparezca.
#
# NO se aplican al reverse-proxy `/hishhr/*` — ese path debe preservar la
# semántica del HIS original para no romper debugging.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "style-src 'self' https://rsms.me; "
        "font-src 'self' https://rsms.me data:; "
        "img-src 'self' data:; "
        "script-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

# User-Agent fijo para el HIS. Cualquier valor de Chrome reciente funciona —
# el HIS no discrimina por UA, pero enviar uno realista evita filtros
# anti-bot genéricos de proxies corporativos.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

# Timeout por request al HIS (segundos). El HIS de Hanga Roa a veces demora
# 10-15s cuando el rango de fechas es grande; 30s es el compromiso.
HIS_TIMEOUT = float(os.environ.get("HIS_TIMEOUT", "30"))

# Reintentos ante fallos transitorios (URLError + HTTP 502/503/504). El
# Total de lecturas: HIS_MAX_RETRIES + 1. Default 1 → hasta 2 intentos.
HIS_MAX_RETRIES = int(os.environ.get("HIS_MAX_RETRIES", "1"))

# Backoff base en segundos: delay_n = HIS_BACKOFF_BASE * 2**n (0.5, 1, 2…).
HIS_BACKOFF_BASE = float(os.environ.get("HIS_BACKOFF_BASE", "0.5"))

# TTL del cache del catálogo de servicios (segundos). Cambios reales en el
# catálogo son raros (meses); 10 min es un compromiso que absorbe el tráfico
# dentro de una sesión de trabajo sin retener datos obsoletos por días.
SERVICIOS_CACHE_TTL = float(os.environ.get("SERVICIOS_CACHE_TTL", "600"))

# TTL del cache de la sonda healthz al HIS (segundos). Evita martillar al
# HIS si algún monitor/script pollea `/api/healthz` cada segundo — cada
# sonda cuesta una request al HIS que puede demorar hasta HIS_TIMEOUT
# cuando la red está caída. 5s detecta recuperación rápido, dedupea
# polling, y en peor caso hace ~12 sondas por minuto en vez de 60.
HEALTHZ_CACHE_TTL = float(os.environ.get("HEALTHZ_CACHE_TTL", "5"))

# Cap de tamaño de body en respuestas del HIS. El HIS sirve HTML que
# raramente excede ~500 KB (listados grandes); 10 MB es un techo holgado
# para no romper casos legítimos. Sirve para 3 cosas:
#
#   1. **Defensa en profundidad** si el HIS misbehaving devuelve un PDF
#      o un dump por accidente — no queremos cargar 100 MB en memoria
#      del proxy.
#   2. **DoS defense parcial** si alguien logra que el HIS responda con
#      payload enorme, no se cae el proxy entero.
#   3. **Detección temprana** de cambios upstream (un endpoint que pasa
#      de 200 KB a 50 MB es señal de algo raro).
#
# Si se excede, `fetch_his` corta la lectura y tira `HISError(502)`. No
# es estrictamente streaming (el body completo va a memoria), pero
# limita el techo.
HIS_MAX_BODY_BYTES = int(os.environ.get("HIS_MAX_BODY_BYTES",
                                          str(10 * 1024 * 1024)))

# Tamaño del chunk para la lectura iterativa. 64 KB es el sweet spot
# clásico — suficientemente grande para no hacer N syscalls en cada
# response, suficientemente chico para detectar el cap rápido si el
# body es enorme.
HIS_READ_CHUNK_BYTES = 64 * 1024

# ---------- Circuit breaker ----------
#
# Si el HIS se cae, los retries multiplican la carga sobre un upstream
# ya degradado: cada request del frontend se vuelve N (con N=
# HIS_MAX_RETRIES+1) intentos. Con 50 búsquedas en cola y el HIS muerto,
# son 150 calls que NO van a ningún lado. El breaker absorbe esto:
# después de M fallos consecutivos, responde 503 sin pegar al HIS por
# T segundos.
#
# Estados:
#   - closed:    flujo normal, cada call va al HIS.
#   - open:      M fallos seguidos disparan apertura por T segundos.
#                Toda call recibe 503 sin tocar al HIS.
#   - half_open: al expirar T, la próxima call SÍ va al HIS (sonda).
#                Si responde OK → vuelve a closed. Si falla → cierra
#                de nuevo por otros T.

# Dos fallos consecutivos disparan la apertura en este cliente clínico local.
# El descargador pausa además esa fuente para el resto del lote.
HIS_CIRCUIT_FAILURE_THRESHOLD = int(
    os.environ.get("HIS_CIRCUIT_FAILURE_THRESHOLD", "2")
)

# Cuántos segundos el circuito queda abierto antes de probar de nuevo.
# 60s da al HIS tiempo razonable para recuperarse sin dejar la app
# inservible por minutos.
HIS_CIRCUIT_OPEN_SECONDS = float(
    os.environ.get("HIS_CIRCUIT_OPEN_SECONDS", "60")
)
