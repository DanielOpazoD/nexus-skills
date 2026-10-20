"""Lecturas acotadas: reintento transitorio y pausa por fuente, sin secretos en logs."""
import time
import ssl
import socket
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

class SourceUnavailable(Exception):
    pass

class ReliableOpener:
    def __init__(self, opener, sleep=time.sleep, clock=None):
        self.opener = opener
        self.sleep = sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.failures = 0
        self.metrics = {'requests': 0, 'retries': 0, 'transient_failures': 0}

    def delay(self, headers):
        value = headers.get('Retry-After') if headers else None
        if value is None: return 0.5
        try: return max(0, float(value))
        except (ValueError, TypeError):
            try: return max(0, (parsedate_to_datetime(value) - self.clock()).total_seconds())
            except (ValueError, TypeError, OverflowError): return 0.5

    def open(self, request, timeout=None):
        if self.failures >= 2:
            raise SourceUnavailable('Fuente pausada tras fallos de red repetidos; reanudar en una nueva ejecución.')
        retryable = request.get_method() == 'GET' or getattr(request, 'clinical_read_only', False)
        for attempt in range(2 if retryable else 1):
            try:
                self.metrics['requests'] += 1
                response = self.opener.open(request, timeout=timeout)
                self.failures = 0
                return response
            except HTTPError as error:
                if error.code not in (429, 502, 503, 504): raise
                delay = self.delay(error.headers)
                error.close()
            except (URLError, TimeoutError, socket.timeout) as error:
                reason = getattr(error, 'reason', error)
                if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):
                    raise
                delay = 0.5
            self.metrics['transient_failures'] += 1
            # No dormir indefinidamente ni reintentar antes de Retry-After.
            if attempt == 0 and retryable and delay <= 5:
                self.metrics['retries'] += 1
                self.sleep(delay)
                continue
            self.failures += 1
            raise SourceUnavailable('Fuente temporalmente inaccesible; se conservan los documentos verificados.') from None

def tls_context():
    """Usa CA instaladas del Mac, conservando hostname y validación de cadena."""
    from pathlib import Path
    import sys
    context = ssl.create_default_context()
    if sys.platform == 'darwin':
        for bundle in ('/opt/homebrew/etc/openssl@3/cert.pem', '/usr/local/etc/openssl@3/cert.pem', '/etc/ssl/cert.pem'):
            if Path(bundle).is_file(): context.load_verify_locations(bundle)
    return context
