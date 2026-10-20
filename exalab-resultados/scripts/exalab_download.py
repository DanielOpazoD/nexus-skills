#!/usr/bin/env python3
"""Descargar PDF de Exalab SSMO con una sesión autenticada de Chrome."""
import argparse
import calendar
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from http.cookiejar import Cookie, CookieJar
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import sys
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, HTTPSHandler, Request, build_opener
from zoneinfo import ZoneInfo

_COMMON = Path(__file__).resolve().parents[2] / 'laboratorios-descargas' / 'scripts'
if _COMMON.is_dir() and str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))
from clinical_transport import SourceUnavailable, ReliableOpener, tls_context


BASE = 'https://exalab.saludoriente.cl/web_ssmo/'
HOST = 'exalab.saludoriente.cl'
PERIODS = {'30d': 'Últimos 30 días', '3m': 'Últimos 3 meses', '6m': 'Últimos 6 meses', '1y': 'Último año', '2y': 'Últimos 2 años', '5y': 'Últimos 5 años', '10y': 'Últimos 10 años'}


class ExalabError(Exception):
    pass


class SessionExpired(ExalabError):
    pass


def normalize_rut(value):
    value = value.strip().replace('.', '').upper()
    match = re.fullmatch(r'(\d{7,8})-([0-9K])', value)
    if not match:
        raise ExalabError('Exalab necesita el RUT con dígito verificador y guion, por ejemplo 12345678-5.')
    body, dv = match.groups()
    check = 11 - sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(body))) % 11
    if dv != ('0' if check == 11 else 'K' if check == 10 else str(check)):
        raise ExalabError('El dígito verificador no coincide.')
    return value


def select_exams(exams, period, today):
    ordered = sorted((e for e in exams if e['datetime'].date() <= today), key=lambda e: (e['datetime'], int(e['id'])), reverse=True)
    if period == 'latest':
        return ordered[:1]
    if period == '30d':
        cutoff = today - timedelta(days=30)
    else:
        year, month = divmod(today.year * 12 + today.month - 1 - {'3m':3, '6m': 6, '1y': 12, '2y': 24, '5y': 60, '10y':120}[period], 12)
        month += 1
        cutoff = date(year, month, min(today.day, calendar.monthrange(year, month)[1]))
    return [e for e in ordered if e['datetime'].date() >= cutoff]


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr':
            self.stack.append({'onclick': attrs.get('onclick', ''), 'cells': [], 'active': False})
        elif tag in ('td', 'th') and self.stack:
            self.stack[-1]['cells'].append('')
            self.stack[-1]['active'] = True

    def handle_data(self, text):
        for row in self.stack:
            if row['active']:
                row['cells'][-1] += ' ' + text

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.stack:
            self.stack[-1]['active'] = False
        elif tag == 'tr' and self.stack:
            self.rows.append(self.stack.pop())


def parse_exams(html, rut):
    # El portal deja #resultado vacío cuando consulta.php devuelve HTTP 200
    # sin folios; la sesión se verificó antes en index.php.
    if not html.strip():
        return []
    parser = Rows()
    parser.feed(html)
    exams = {}
    for row in parser.rows:
        if not row['onclick']:
            continue
        match = re.fullmatch(r"\s*ver_ficha_param2\(\s*(['\"])([^'\"]+)\1\s*,\s*(\d+)\s*,\s*(\d+)\s*\)\s*;?\s*", row['onclick'])
        cells = [' '.join(c.split()) for c in row['cells']]
        if not match or len(cells) < 6:
            raise ExalabError('Cambió la estructura de los folios; revisa Exalab en Chrome.')
        _, source, folio, body = match.groups()
        if body != rut.split('-')[0] or normalize_rut(cells[4]) != rut or cells[1] != folio:
            raise ExalabError('El RUT o folio del resultado no coincide con la consulta.')
        # Esta URL se devuelve como parámetro al servidor Exalab; nunca se visita directamente.
        parts = urlsplit(source)
        host = (parts.hostname or '').lower()
        path = parts.path.lower()
        # Orígenes observados en Exalab: el servidor recibe esta URL como parámetro;
        # este cliente nunca la visita directamente.
        fixed = {
            ('localhost', '/web_ssmo/proactive/getexamen.php'),
            ('localhost', '/web_ssmo/controlador/detalleexamenesexalab.php'),
            ('syslab.calvomackenna.cl', '/detalleexameneshlcm.php'),
        }
        try:
            internal = ipaddress.ip_address(host) in ipaddress.ip_network('10.0.0.0/8') and path == '/syslab/detalleexamenes.php'
        except ValueError:
            internal = False
        recognized = internal or (host, path) in fixed
        if not recognized:
            raise ExalabError('No se reconoce el laboratorio de origen.')
        if parts.scheme not in ('http', 'https') or set(parse_qs(parts.query)) != {'id'} or parse_qs(parts.query)['id'] != [folio] or parts.username or parts.password or parts.fragment or (not internal and parts.port is not None):
            raise ExalabError('El enlace de origen no tiene el formato esperado.')
        try:
            stamp = datetime.strptime(cells[2] + ' ' + cells[3], '%d-%m-%Y %H:%M:%S')
        except ValueError:
            raise ExalabError('No se pudo verificar la fecha del folio.') from None
        key = (source, folio)
        exams[key] = {'id': folio, 'rut': rut, 'datetime': stamp, 'name': cells[5], 'source': source}
    if not exams and not re.search(r'(sin\s+(?:resultados|registros|folios)|no\s+(?:se\s+)?(?:encontr|exist)|0\s+(?:registros|folios))', html, re.I):
        raise ExalabError('No se reconoció la lista de resultados; comprueba la sesión en Chrome.')
    return list(exams.values())


class PdfTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('object', 'iframe', 'embed'):
            value = attrs.get('data') if tag == 'object' else attrs.get('src')
            if value:
                self.paths.append(value)


def pdf_url(html):
    parser = PdfTags()
    parser.feed(html)
    if len(parser.paths) != 1:
        raise ExalabError('Exalab no generó un enlace PDF único.')
    url = urljoin(BASE, parser.paths[0])
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.netloc != HOST or not re.fullmatch(r'/web_ssmo/pdf/[A-Za-z0-9_\-]+\.pdf', parts.path) or parts.query or parts.fragment:
        raise ExalabError('El PDF apunta fuera de la carpeta esperada de Exalab.')
    return url


class SameSiteRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme != 'https' or parts.netloc != HOST:
            raise SessionExpired('La sesión venció. Vuelve a entrar con ClaveÚnica en Chrome.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Exalab:
    def __init__(self, session, timeout=20):
        cookies = session.get('cookies', [])
        self.user_agent = session.get('user_agent', 'ExalabDownloader/1.0')
        if not isinstance(self.user_agent, str) or '\r' in self.user_agent or '\n' in self.user_agent:
            raise ExalabError('Sesión mal formada.')
        jar = CookieJar()
        for item in cookies:
            if item.get('name') not in ('PHPSESSID', 'cf_clearance'):
                continue
            domain = item.get('domain', HOST).lstrip('.')
            allowed_domains = (HOST, 'saludoriente.cl') if item['name'] == 'cf_clearance' else (HOST,)
            if domain not in allowed_domains:
                raise ExalabError('La cookie no pertenece a Exalab.')
            value = item.get('value', '')
            if not isinstance(value, str) or not value or any(c in value for c in '\r\n;'):
                raise ExalabError('Sesión mal formada.')
            path = item.get('path', '/')
            if not isinstance(path, str) or not path.startswith('/'):
                raise ExalabError('Sesión mal formada.')
            jar.set_cookie(Cookie(0, item['name'], value, None, False, HOST, True, False, path, True, True, None, True, None, None, {}, False))
        if not any(c.name == 'PHPSESSID' for c in jar):
            raise SessionExpired('Falta una sesión Exalab autenticada de Chrome.')
        context = tls_context()
        if sys.platform == 'darwin' and Path('/etc/ssl/cert.pem').is_file():
            context.load_verify_locations('/etc/ssl/cert.pem')
        self.opener = build_opener(SameSiteRedirect(), HTTPCookieProcessor(jar), HTTPSHandler(context=context))
        self.opener = ReliableOpener(self.opener)
        self.timeout = timeout

    def request(self, path, data=None, pdf=False):
        url = urljoin(BASE, path)
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.netloc != HOST or not parts.path.startswith('/web_ssmo/'):
            raise ExalabError('Destino no permitido para el programa Exalab.')
        headers = {'User-Agent': self.user_agent, 'Referer': BASE + 'index.php'}
        if data is not None:
            headers['X-Requested-With'] = 'XMLHttpRequest'
        req = Request(url, data=None if data is None else urlencode(data).encode(), headers=headers)
        req.clinical_read_only = path in ('controlador/consulta.php', 'controlador/ventana.php')
        limit = 32 * 1024 * 1024 if pdf else 8 * 1024 * 1024
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                if not response.url.startswith(BASE):
                    raise SessionExpired('La sesión venció. Vuelve a entrar con ClaveÚnica en Chrome.')
                content = response.read(limit + 1)
                charset = response.headers.get_content_charset() or 'utf-8'
        except (URLError, TimeoutError, OSError):
            raise ExalabError('No se pudo conectar con Exalab por HTTPS. Comprueba conexión y certificados.') from None
        if len(content) > limit:
            raise ExalabError('La respuesta supera el tamaño esperado.')
        if pdf:
            if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
                raise ExalabError('El servidor no devolvió un PDF completo; comprueba la sesión.')
            return content
        try:
            html = content.decode(charset)
        except (UnicodeError, LookupError):
            html = content.decode('latin-1')
        if 'Iniciar sesión con ClaveÚnica' in html or 'accounts.claveunica.gob.cl/accounts/login' in html:
            raise SessionExpired('La sesión venció. Vuelve a entrar con ClaveÚnica en Chrome.')
        return html

    def preflight(self):
        page = self.request('index.php')
        if not re.search(r'\bid=[\'\"]rut[\'\"]', page):
            raise SessionExpired('No hay una sesión de consulta activa. Inicia sesión en Chrome.')
        return True

    def search(self, rut):
        page = self.request('index.php')
        if not re.search(r'\bid=[\'\"]rut[\'\"]', page):
            raise SessionExpired('No hay una sesión de consulta activa. Inicia sesión en Chrome.')
        return parse_exams(self.request('controlador/consulta.php', {'rut': rut}), rut)

    def download(self, exam):
        html = self.request('controlador/ventana.php', {'url': exam['source'], 'id': exam['id'], 'rut': exam['rut'].split('-')[0]})
        return self.request(pdf_url(html), pdf=True)


def save_pdf(folder, exam, content):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    stem = 'Exalab_{}_{}_{}'.format(exam['rut'], exam['datetime'].strftime('%d-%m-%Y'), exam['id'])
    path = folder / (stem + '.pdf')
    suffix = 1
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if path.read_bytes() == content:
                return path.resolve()
            suffix += 1
            path = folder / (stem + '_' + str(suffix) + '.pdf')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return path.resolve()


def choose_period():
    codes = list(PERIODS)
    print('¿De qué período quieres los exámenes?')
    for i, code in enumerate(codes, 1):
        print('  {}. {}'.format(i, PERIODS[code]))
    while True:
        value = input('Opción (1–{}): '.format(len(codes))).strip()
        if value in {str(i) for i in range(1, len(codes) + 1)}:
            return codes[int(value) - 1]


def main(argv=None, session=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rut', help='RUT completo con dígito verificador')
    parser.add_argument('--period', choices=[*PERIODS, 'latest'])
    parser.add_argument('--output', type=Path, default=Path.cwd() / 'outputs' / 'exalab')
    parser.add_argument('--as-of', type=date.fromisoformat, help='Referencia AAAA-MM-DD; por defecto Pacific/Easter')
    parser.add_argument('--list-only', action='store_true')
    parser.add_argument('--session-stdin', action='store_true', help='Recibir JSON de sesión por una tubería privada desde el puente Chrome')
    args = parser.parse_args(argv)
    if not sys.stdin.isatty() and (not args.rut or not args.period):
        raise ExalabError('Indica --rut y --period para la ejecución automatizada.')
    rut = normalize_rut(args.rut or input('RUT completo del paciente: '))
    period = args.period or choose_period()
    if session is None:
        if not args.session_stdin:
            raise SessionExpired('Ejecuta este programa con el puente de sesión Chrome de Codex; no necesita tu contraseña de ClaveÚnica.')
        try:
            session = json.loads(sys.stdin.read(65537))
        except (ValueError, TypeError):
            raise ExalabError('No se recibió un JSON de sesión válido.') from None
    if not isinstance(session, dict) or not isinstance(session.get('cookies'), list):
        raise ExalabError('No se recibió una sesión válida.')
    today = args.as_of or datetime.now(ZoneInfo('Pacific/Easter')).date()
    client = Exalab(session)
    exams = select_exams(client.search(rut), period, today)
    print('{} — referencia {} — {} informe(s)'.format('Último informe' if period == 'latest' else PERIODS[period], today.isoformat(), len(exams)))
    failures = 0
    for exam in exams:
        print('{} | Folio {} | {} | RUT {}'.format(exam['datetime'].strftime('%d/%m/%Y %H:%M:%S'), exam['id'], exam['name'], rut))
        if not args.list_only:
            try:
                print('  PDF: {}'.format(save_pdf(args.output, exam, client.download(exam))))
            except SessionExpired:
                raise
            except ExalabError as error:
                failures += 1
                print('  No descargado: {}'.format(error), file=sys.stderr)
    if not exams:
        print('No hay informes en el período seleccionado.')
    return 1 if failures else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SessionExpired as error:
        print('Sesión: {}'.format(error), file=sys.stderr)
        sys.exit(2)
    except (SourceUnavailable, ExalabError, EOFError, OSError) as error:
        print('Error: {}'.format(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nCancelado.', file=sys.stderr)
        sys.exit(130)
