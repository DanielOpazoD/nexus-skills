#!/usr/bin/env python3
"""Descargar informes Syslab Hanga Roa. Solo necesita Python 3.9 o posterior."""

import argparse
import calendar
from datetime import date, datetime, timedelta
from getpass import getpass
from html import unescape
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import os
from pathlib import Path
import re
import sys
import unicodedata
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

_COMMON = Path(__file__).resolve().parents[2] / 'laboratorios-descargas' / 'scripts'
if _COMMON.is_dir() and str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))
from clinical_transport import SourceUnavailable, ReliableOpener


BASE = "http://10.4.69.90/syslab/"
PERIODS = {"30d": "Últimos 30 días", "3m": "Últimos 3 meses", "6m": "Últimos 6 meses", "1y": "Último año", "2y": "Últimos 2 años", "5y": "Últimos 5 años", "10y": "Últimos 10 años"}


class SyslabError(Exception):
    pass


class NoValidatedExams(SyslabError):
    """El folio figura en la lista, pero Syslab aún no entrega un PDF validado."""


def no_validated_exams(content, charset):
    for encoding in dict.fromkeys((charset, 'utf-8', 'latin-1')):
        try:
            visible = unescape(content.decode(encoding))
        except (LookupError, UnicodeError):
            continue
        visible = re.sub(r'<[^>]+>', ' ', visible)
        visible = unicodedata.normalize('NFKD', visible).encode('ascii', 'ignore').decode('ascii')
        words = re.sub(r'[^a-z0-9]+', ' ', visible.lower())
        if re.search(r'\bno hay examenes validados\b', words):
            return True
    return False


def normalize_rut(value):
    value = value.strip().replace(".", "").upper()
    if "-" in value:
        body, dv = value.rsplit("-", 1)
        if not re.fullmatch(r"\d{7,8}", body) or not re.fullmatch(r"[0-9K]", dv):
            raise SyslabError("RUT inválido. Usa el número sin dígito, o el RUT completo con guion.")
        total = sum(int(digit) * (2 + i % 6) for i, digit in enumerate(reversed(body)))
        check = 11 - total % 11
        expected = "0" if check == 11 else "K" if check == 10 else str(check)
        if dv != expected:
            raise SyslabError("El dígito verificador del RUT no coincide.")
        value = body
    if not re.fullmatch(r"\d{7,8}", value):
        raise SyslabError("RUT inválido. La búsqueda de Syslab usa 7 u 8 cifras, sin dígito verificador.")
    return value


def subtract_months(day, months):
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def select_exams(exams, period, today):
    ordered = sorted(exams, key=lambda e: (e["datetime"], int(e["id"])), reverse=True)
    ordered = [e for e in ordered if e["datetime"].date() <= today]
    if period == "latest":
        return ordered[:1]
    since = today - timedelta(days=30) if period == "30d" else subtract_months(today, {"3m":3, "6m": 6, "1y": 12, "2y": 24, "5y": 60, "10y":120}[period])
    return [e for e in ordered if e["datetime"].date() >= since]


class Rows(HTMLParser):
    """Preserva las columnas de cada fila, incluidas las tablas anidadas."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.stack.append({"cells": [], "active": False, "links": []})
        elif tag in ("td", "th") and self.stack:
            self.stack[-1]["cells"].append("")
            self.stack[-1]["active"] = True
        elif tag == "a" and self.stack:
            self.stack[-1]["links"].append(attrs.get("href", "").strip())

    def handle_data(self, data):
        for row in self.stack:
            if row["active"]:
                row["cells"][-1] += " " + data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.stack:
            self.stack[-1]["active"] = False
        elif tag == "tr" and self.stack:
            self.rows.append(self.stack.pop())


def parse_exams(html, rut):
    parser = Rows()
    parser.feed(html)
    exams = {}
    for row in parser.rows:
        cells = [" ".join(c.split()) for c in row["cells"]]
        for href in row["links"]:
            url = urljoin(BASE, href)
            parts = urlsplit(url)
            if parts.path != "/syslab/detalleexamenes.php":
                continue
            if (parts.scheme, parts.netloc) != ("http", "10.4.69.90"):
                raise SyslabError("El enlace del informe apunta fuera de Syslab.")
            ids = parse_qs(parts.query).get("id", [])
            if len(cells) < 5 or len(ids) != 1 or not ids[0].isdigit():
                raise SyslabError("Cambió la estructura de resultados; revisa Syslab en Chrome.")
            match = re.fullmatch(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})", cells[1])
            patient = re.match(r"^(\d{7,8})\s*[- ]\s*([0-9Kk])$", cells[2].replace(".", ""))
            if not match or not patient or patient.group(1) != rut:
                raise SyslabError("No se pudo verificar la fecha y el RUT de un resultado.")
            try:
                stamp = datetime.strptime(" ".join(match.groups()), "%d/%m/%Y %H:%M:%S")
            except ValueError:
                raise SyslabError("Un resultado contiene una fecha inválida.") from None
            exams[ids[0]] = {"id": ids[0], "datetime": stamp, "rut": rut, "name": cells[3], "url": url}
    if not exams and not re.search(r"(?:0\s+registros|sin\s+(?:resultados|registros)|no\s+(?:se\s+)?(?:encontr|exist))", html, re.I):
        raise SyslabError("No se reconoció la lista de resultados. Revisa el acceso en Chrome.")
    return list(exams.values())


class SameSiteRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if (parts.scheme, parts.netloc) != ("http", "10.4.69.90") or not parts.path.startswith("/syslab/"):
            raise SyslabError("Syslab redirigió fuera del sitio esperado; se detuvo la solicitud.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Syslab:
    def __init__(self, timeout=20):
        self.opener = build_opener(SameSiteRedirect(), HTTPCookieProcessor(CookieJar()))
        self.opener = ReliableOpener(self.opener)
        self.timeout = timeout

    def request(self, path, data=None, pdf=False):
        url = urljoin(BASE, path)
        parts = urlsplit(url)
        if (parts.scheme, parts.netloc) != ("http", "10.4.69.90") or not parts.path.startswith("/syslab/"):
            raise SyslabError("Destino no permitido para esta sesión Syslab.")
        request = Request(url, data=None if data is None else urlencode(data).encode("utf-8"), headers={"User-Agent": "SyslabDownloader/1.0"})
        request.clinical_read_only = path == 'resultadoseleccion.php'
        limit = 32 * 1024 * 1024 if pdf else 8 * 1024 * 1024
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                content = response.read(limit + 1)
                charset = response.headers.get_content_charset() or "utf-8"
        except (URLError, TimeoutError, OSError):
            raise SyslabError("No se pudo conectar con Syslab. Comprueba la red del hospital y vuelve a intentarlo.") from None
        if len(content) > limit:
            raise SyslabError("La respuesta supera el tamaño esperado; no se guardó.")
        if pdf:
            if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
                if no_validated_exams(content, charset):
                    raise NoValidatedExams("El folio todavía no tiene exámenes validados en Syslab.")
                raise SyslabError("El servidor no devolvió un PDF completo. La sesión puede haber vencido.")
            return content
        try:
            return content.decode(charset)
        except (UnicodeError, LookupError):
            return content.decode("latin-1")

    def login(self, username, password):
        self.request("")
        html = self.request("autenticacion.php", {"usuario": username, "contrasena": password, "boton": "Ingresar"})
        if "parbusqueRut.php" not in html:
            raise SyslabError("No se pudo iniciar sesión. Comprueba el usuario y la contraseña.")

    def search(self, rut):
        self.request("parbusqueRut.php")
        html = self.request("resultadoseleccion.php", {"rut": rut, "BotonAccion": "Aceptar"})
        return parse_exams(html, rut)


def save_pdf(folder, exam, content):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = "Syslab_{}_{}_{}.pdf".format(exam["rut"], exam["datetime"].strftime("%d-%m-%Y"), exam["id"])
    path = folder / name
    suffix = 1
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if path.read_bytes() == content:
                return path.resolve()
            suffix += 1
            path = folder / (Path(name).stem + "_" + str(suffix) + ".pdf")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return path.resolve()


def choose_period():
    print("¿De qué período quieres los exámenes?")
    codes = list(PERIODS)
    for i, code in enumerate(codes, 1):
        print("  {}. {}".format(i, PERIODS[code]))
    while True:
        choice = input("Opción (1–{}): ".format(len(codes))).strip()
        if choice in {str(i) for i in range(1, len(codes) + 1)}:
            return codes[int(choice) - 1]
        print("Elige una opción de 1 a {}.".format(len(codes)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rut", help="RUT sin dígito, o completo con guion; se normaliza para Syslab")
    parser.add_argument("--period", choices=[*PERIODS, "latest"], help="Si se omite, pregunta entre los períodos disponibles")
    parser.add_argument("--username", help="Usuario Syslab; también SYSLAB_USERNAME")
    parser.add_argument("--output", type=Path, default=Path.cwd() / "outputs" / "syslab", help="Carpeta de los PDF")
    parser.add_argument("--list-only", action="store_true", help="Consultar y filtrar sin descargar")
    parser.add_argument("--as-of", type=date.fromisoformat, help="Fecha de referencia AAAA-MM-DD; por defecto hoy en Isla de Pascua")
    args = parser.parse_args(argv)
    rut = normalize_rut(args.rut or input("RUT del paciente: "))
    period = args.period or choose_period()
    today = args.as_of or datetime.now(ZoneInfo("Pacific/Easter")).date()
    username = args.username or os.environ.get("SYSLAB_USERNAME") or input("Usuario Syslab: ").strip()
    password = os.environ.get("SYSLAB_PASSWORD")
    if password is None:
        if not sys.stdin.isatty():
            raise SyslabError("Falta SYSLAB_PASSWORD. Ejecuta el programa en un terminal para introducirla de forma oculta.")
        password = getpass("Contraseña Syslab (no se guarda): ")
    if not username or not password:
        raise SyslabError("Se necesitan usuario y contraseña.")
    client = Syslab()
    client.login(username, password)
    del password
    exams = select_exams(client.search(rut), period, today)
    label = "Último informe" if period == "latest" else PERIODS[period]
    print("{} — referencia {} — {} informe(s)".format(label, today.isoformat(), len(exams)))
    if not exams:
        print("No hay informes en el período seleccionado.")
        return 0
    failures = 0
    for exam in exams:
        print("{} | Folio {} | {} | RUT {}".format(exam["datetime"].strftime("%d/%m/%Y %H:%M:%S"), exam["id"], exam["name"], exam["rut"]))
        if not args.list_only:
            try:
                path = save_pdf(args.output, exam, client.request(exam["url"], pdf=True))
                print("  PDF: {}".format(path))
            except SyslabError as error:
                failures += 1
                print("  No descargado: {}".format(error), file=sys.stderr)
    if failures:
        print("{} informe(s) pendiente(s).".format(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SourceUnavailable, SyslabError, EOFError, OSError) as error:
        print("Error: {}".format(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        sys.exit(130)
