#!/usr/bin/env python3
"""Cliente local del RIS MMRAD; cookies y credenciales sólo viven en memoria."""
import calendar
from pathlib import Path
from datetime import date, datetime, timedelta
from hashlib import sha256
from html import unescape
from http.cookiejar import CookieJar
from io import BytesIO
import json
import os
import re
import secrets
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler

_COMMON = Path(__file__).resolve().parents[2] / 'laboratorios-descargas' / 'scripts'
if _COMMON.is_dir() and str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))
from clinical_transport import ReliableOpener, tls_context
from mmrad_selection import IMAGE_TYPES, normalize_image_types, is_echocardiography, image_exclusion


BASE = 'https://ris.mmrad.cl'
PANEL = BASE + '/group/hhangaroa'
VIEWER_BASE = 'https://hhangaroavisor.mmrad.cl:4446'
WADO_ROOT = 'http://172.16.20.110:1000/wado/HHANGAROA'
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
REDIRECTS = (301, 302, 303, 307, 308)


class MMRADError(Exception):
    pass


class AuthenticationError(MMRADError):
    pass


class MMRADProtocolError(MMRADError):
    pass


class NoPdfReport(MMRADError):
    pass


class NoStudyImages(MMRADError):
    pass


class ExcludedStudyImages(NoStudyImages):
    """Exclusión deliberada; no equivale a imágenes ausentes o descarga fallida."""


def normalize_url(raw, base=BASE):
    if not raw:
        raise MMRADProtocolError('MMRAD devolvió un enlace vacío.')
    value = unescape(str(raw).strip())
    opened = re.search(r'window\.open\([\'\"]([^\'\"]+)[\'\"]', value, re.I)
    if opened:
        value = opened.group(1)
    url = urljoin(base, value)
    try:
        parts = urlsplit(url)
        allowed = (parts.scheme, parts.hostname, parts.port, parts.username, parts.password) == ('https', 'ris.mmrad.cl', None, None, None)
    except ValueError:
        allowed = False
    if not allowed:
        raise MMRADProtocolError('Destino MMRAD no permitido.')
    return url


def normalize_viewer_url(raw, base=VIEWER_BASE):
    url = urljoin(base, unescape(str(raw or '').strip()))
    try:
        parts = urlsplit(url)
        allowed = (parts.scheme, parts.hostname, parts.port, parts.username, parts.password) == (
            'https', 'hhangaroavisor.mmrad.cl', 4446, None, None)
    except ValueError:
        allowed = False
    if not allowed:
        raise MMRADProtocolError('Destino del visor MMRAD no permitido.')
    return url


def viewer_from_html(markup):
    match = re.search(r'<iframe\b[^>]*\bsrc\s*=\s*[\'\"]([^\'\"]+)', markup, re.I)
    if not match:
        raise NoStudyImages('El enlace DICOM no contiene la dirección del visor.')
    url = normalize_viewer_url(match.group(1))
    parts = urlsplit(url)
    study = re.fullmatch(r'/viewer/(\d+(?:\.\d+)+)/?', parts.path)
    if not study or parts.query or parts.fragment:
        raise MMRADProtocolError('La dirección del visor no identifica un estudio DICOM.')
    return url, study.group(1)


def make_wado_proxy_url(study, series, instance, root=WADO_ROOT):
    """Modelo de la ruta WADO observada; la descarga real usa wadouri del visor."""
    nested = root + '?' + urlencode({'requestType':'WADO', 'studyUID':study, 'seriesUID':series,
                                      'objectUID':instance, 'contentType':'application/dicom'})
    return VIEWER_BASE + '/__wado_proxy?' + urlencode({'serverId':'fictitious', 'url':nested})


def validate_wado_proxy(raw, study, series, instance):
    url = normalize_viewer_url(raw)
    parts = urlsplit(url)
    if parts.path != '/__wado_proxy' or parts.fragment:
        raise MMRADProtocolError('Ruta WADO del visor inválida.')
    outer = parse_qs(parts.query, strict_parsing=True)
    if set(outer) != {'serverId', 'url'} or any(len(values) != 1 for values in outer.values()):
        raise MMRADProtocolError('Parámetros WADO del visor inválidos.')
    nested = urlsplit(outer['url'][0])
    allowed = (nested.scheme, nested.hostname, nested.port, nested.path,
               nested.username, nested.password, nested.fragment) == (
                   'http', '172.16.20.110', 1000, '/wado/HHANGAROA', None, None, '')
    if not allowed:
        raise MMRADProtocolError('Destino WADO interno no permitido.')
    query = parse_qs(nested.query, strict_parsing=True)
    expected = {'requestType':'WADO', 'studyUID':study, 'seriesUID':series,
                'objectUID':instance, 'contentType':'application/dicom'}
    if set(query) != set(expected) or any(query[key] != [value] for key, value in expected.items()):
        raise MMRADProtocolError('El WADO no corresponde a la instancia del estudio.')
    return url


def ordered_instances(metadata, study):
    if metadata.get('studyInstanceUid') != study or not isinstance(metadata.get('seriesList'), list):
        raise MMRADProtocolError('El visor entregó metadatos de otro estudio.')
    series_list = metadata['seriesList']
    if not series_list:
        raise NoStudyImages('El estudio no tiene series de imágenes disponibles.')
    def number(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 10**9
    ordered, seen = [], set()
    for series in sorted(series_list, key=lambda s: (number(s.get('seriesNumber')), s.get('seriesInstanceUid',''))):
        series_uid = series.get('seriesInstanceUid')
        if not isinstance(series_uid, str) or not re.fullmatch(r'\d+(?:\.\d+)+', series_uid):
            raise MMRADProtocolError('Una serie del visor no tiene UID válido.')
        for instance in sorted(series.get('instances') or [], key=lambda i: (number(i.get('instanceNumber')), i.get('sopInstanceUid',''))):
            sop_uid = instance.get('sopInstanceUid')
            if not isinstance(sop_uid, str) or not re.fullmatch(r'\d+(?:\.\d+)+', sop_uid) or sop_uid in seen:
                raise MMRADProtocolError('Una instancia DICOM falta o está duplicada.')
            seen.add(sop_uid)
            advertised_frames = number(instance.get('numberOfFrames')) if instance.get('numberOfFrames') else None
            ordered.append({'study_uid':study, 'series_uid':series_uid, 'sop_uid':sop_uid,
                            'series_number':series.get('seriesNumber'), 'instance_number':instance.get('instanceNumber'),
                            'expected_frames':advertised_frames if advertised_frames and advertised_frames < 10**9 else None,
                            'url':validate_wado_proxy(instance.get('wadouri'), study, series_uid, sop_uid)})
    if not ordered:
        raise NoStudyImages('El visor no entregó instancias de imagen para este estudio.')
    return ordered


def sockjs_messages(frame):
    try:
        frame = frame.decode('utf-8') if isinstance(frame, bytes) else frame
        if frame in ('o', 'h'):
            return []
        if not frame.startswith('a'):
            raise ValueError()
        return [json.loads(item) for item in json.loads(frame[1:])]
    except (UnicodeError, ValueError, TypeError):
        raise MMRADProtocolError('El visor no respondió con mensajes DDP válidos.') from None


def validate_dicom(content, study, series, instance):
    try:
        import pydicom
        dataset = pydicom.dcmread(BytesIO(content), force=False)
        if (str(dataset.StudyInstanceUID), str(dataset.SeriesInstanceUID), str(dataset.SOPInstanceUID)) != (
                study, series, instance):
            raise MMRADProtocolError('La imagen DICOM pertenece a otro estudio o proyección.')
        if 'PixelData' not in dataset:
            raise MMRADProtocolError('La instancia DICOM no contiene píxeles.')
        return dataset
    except MMRADProtocolError:
        raise
    except Exception:
        raise MMRADProtocolError('La descarga no contiene un DICOM de imagen válido.') from None


def render_dicom_frame(dataset, frame):
    import numpy as np
    from PIL import Image
    from pydicom.pixels import apply_modality_lut, apply_voi_lut
    interpretation = str(dataset.PhotometricInterpretation).upper()
    if interpretation in ('RGB', 'YBR_FULL', 'YBR_FULL_422'):
        pixels = np.asarray(frame)
        if pixels.ndim != 3 or pixels.shape[2] != 3 or int(dataset.SamplesPerPixel) != 3:
            raise MMRADProtocolError('El DICOM en color tiene una disposición de píxeles no soportada.')
        if int(dataset.BitsAllocated) != 8 or int(dataset.BitsStored) != 8:
            raise MMRADProtocolError('Profundidad DICOM en color no soportada.')
        # pydicom.pixel_array convierte YBR_FULL y YBR_FULL_422 a RGB por defecto.
        return Image.fromarray(np.asarray(pixels, dtype=np.uint8), mode='RGB')
    if interpretation not in ('MONOCHROME1', 'MONOCHROME2'):
        raise MMRADProtocolError('La interpretación fotométrica DICOM no está soportada.')
    values = apply_modality_lut(frame, dataset)
    values = apply_voi_lut(values, dataset)
    bits = int(dataset.BitsStored)
    if not 1 <= bits <= 16:
        raise MMRADProtocolError('Profundidad de imagen DICOM no soportada.')
    signed = int(dataset.PixelRepresentation) == 1
    low = -(2 ** (bits - 1)) if signed else 0
    high = 2 ** (bits - 1) - 1 if signed else 2 ** bits - 1
    if getattr(dataset, 'VOILUTSequence', None):
        descriptor = dataset.VOILUTSequence[0].LUTDescriptor
        high = 2 ** int(descriptor[2]) - 1
        low = 0
    scaled = np.rint(np.clip((np.asarray(values, dtype=np.float64) - low) * 255 / (high - low), 0, 255)).astype(np.uint8)
    shape = str(getattr(dataset, 'PresentationLUTShape', '')).upper()
    if shape not in ('', 'IDENTITY', 'INVERSE'):
        raise MMRADProtocolError('Presentación LUT DICOM no soportada.')
    if shape == 'INVERSE' or (not shape and dataset.PhotometricInterpretation == 'MONOCHROME1'):
        scaled = 255 - scaled
    return Image.fromarray(scaled, mode='L')


def render_image_pdf(exam, originals):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader
    if not originals:
        raise NoStudyImages('No hay imágenes descargadas para crear el PDF.')
    frames = []
    for item, content in originals:
        ds = validate_dicom(content, item['study_uid'], item['series_uid'], item['sop_uid'])
        pixels = ds.pixel_array
        count = int(getattr(ds, 'NumberOfFrames', 1))
        if item.get('expected_frames') is not None and count != int(item['expected_frames']):
            raise MMRADProtocolError('El DICOM tiene un número de cuadros distinto al anunciado por el visor.')
        images = pixels if count > 1 else [pixels]
        for image in images:
            frames.append((item, render_dicom_frame(ds, image)))
    stream = BytesIO()
    doc = canvas.Canvas(stream, pagesize=A4, pageCompression=1)
    study_date = exam['datetime'].strftime('%d-%m-%Y')
    title = str(exam.get('exam_name') or 'Estudio de imagenología')
    modality = str(exam.get('modality') or '')
    for index, (item, image) in enumerate(frames, 1):
        width, height = landscape(A4) if image.width > image.height else A4
        doc.setPageSize((width, height))
        doc.setFont('Helvetica-Bold', 13)
        heading = '{} - {} - {}'.format(study_date, title, modality)
        while heading and stringWidth(heading, 'Helvetica-Bold', 13) > width - 56:
            heading = heading[:-1]
        doc.drawString(28, height - 32, heading)
        doc.setFont('Helvetica', 9)
        doc.drawString(28, height - 48, 'RUT {}  |  Imagen {} de {}  |  Serie {}  |  Instancia {}'.format(
            exam['rut'], index, len(frames), item.get('series_number') or '-', item.get('instance_number') or '-'))
        available_width, available_height = width - 56, height - 90
        factor = min(available_width / image.width, available_height / image.height)
        drawn_width, drawn_height = image.width * factor, image.height * factor
        doc.drawImage(ImageReader(image), (width - drawn_width) / 2, 22 + (available_height - drawn_height) / 2,
                      width=drawn_width, height=drawn_height, mask=None)
        doc.showPage()
    doc.setTitle('{} - {} - {}'.format(study_date, title, modality))
    doc.save()
    pdf = stream.getvalue()
    reader = PdfReader(BytesIO(pdf))
    if len(reader.pages) != len(frames) or study_date not in (reader.pages[0].extract_text() or ''):
        raise MMRADProtocolError('El PDF de imágenes quedó incompleto o sin fecha.')
    return pdf


def form_action(markup, marker):
    for match in re.finditer(r'<form\b[^>]*\baction\s*=\s*[\'\"]([^\'\"]+)[\'\"]', markup, re.I | re.S):
        action = unescape(match.group(1))
        if marker.lower() in action.lower():
            return normalize_url(action)
    return None


def subtract_months(day, months):
    year, index = divmod(day.year * 12 + day.month - 1 - months, 12)
    month = index + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def date_filters(period, today):
    if period not in ('30d', '3m', '6m', '1y', '2y', '5y', '10y', 'latest'):
        raise MMRADProtocolError('Período MMRAD inválido.')
    if period == 'latest':
        # La primera ventana de una búsqueda escalonada del último registro.
        period = '30d'
    since = today - timedelta(days=30) if period == '30d' else subtract_months(today, {'3m':3, '6m':6, '1y':12, '2y':24, '5y':60, '10y':120}[period])
    return since.strftime('%d/%m/%Y'), today.strftime('%d/%m/%Y')


def _action_links(row):
    for anchor in re.finditer(r'<a\b([^>]*)>(.*?)</a>', row, re.I | re.S):
        attrs, label = anchor.groups()
        href = re.search(r'\bhref\s*=\s*([\'\"])(.*?)\1', attrs, re.I | re.S)
        if href:
            yield unescape(href.group(2)), re.sub(r'<[^>]+>', ' ', unescape(label)).strip()


def _exam_id(*urls):
    for url in urls:
        if not url:
            continue
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        for key in ('idexamen', 'id'):
            value = query.get(key, [''])[0]
            if value.isdigit():
                return value
        match = re.search(r'/informePDF/(\d+)(?:/|$)', parts.path, re.I)
        if match:
            return match.group(1)
    source = next((url for url in urls if url), None)
    if not source:
        raise MMRADProtocolError('No se encontró identificador ni enlace de informe.')
    return str(int.from_bytes(sha256(source.encode()).digest()[:8], 'big'))


def parse_exams(markup, rut):
    decoded = unescape(markup)
    exams = []
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', decoded, re.I | re.S):
        if 'Acciones' not in row:
            continue
        cells = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', cell)).strip()
                 for cell in re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.I | re.S)]
        if len(cells) < 14:
            raise MMRADProtocolError('Cambió la tabla de estudios MMRAD; no se pudo interpretar una fila.')
        stamp = re.search(r'\b(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}))?', cells[7])
        if not stamp:
            raise MMRADProtocolError('Un estudio MMRAD no tiene fecha reconocible.')
        try:
            when = datetime.strptime(stamp.group(1) + ' ' + (stamp.group(2) or '00:00'), '%d/%m/%Y %H:%M')
        except ValueError:
            raise MMRADProtocolError('Un estudio MMRAD tiene fecha inválida.') from None
        links = {'pdf_url':None, 'html_url':None, 'receipt_url':None, 'dicom_url':None}
        for raw, label in _action_links(row):
            lowered = raw.lower()
            kind = ('pdf_url' if 'informepdf' in lowered else
                    'receipt_url' if 'comprobante portal web paciente' in label.lower() else
                    'dicom_url' if re.search(r'utilservlet\?a=3(?:&|$)', lowered) else
                    'html_url' if 'informehtml' in lowered or re.search(r'utilservlet\?a=1(?:&|$)', lowered) else None)
            if kind:
                links[kind] = normalize_url(raw)
        report_type = ('pdf' if links['pdf_url'] else 'html' if links['html_url'] else
                       'receipt' if links['receipt_url'] else 'dicom' if links['dicom_url'] else 'none')
        source = links['pdf_url'] or links['html_url'] or links['receipt_url'] or links['dicom_url']
        ident = _exam_id(*links.values()) if source else str(int.from_bytes(sha256(row.encode()).digest()[:8], 'big'))
        exams.append({'id':ident, 'rut':rut, 'datetime':when, 'name':cells[9],
                      'exam_name':cells[10], 'modality':cells[11], 'status':cells[13],
                      'report_type':report_type, 'source':source,
                      'fingerprint':sha256((source or row).encode()).hexdigest(), **links})
    if not exams and not (re.search(r'(?:sin resultados|no se encontraron|0\s+registros)', decoded, re.I)
                          or '<table' in decoded.lower()):
        raise MMRADProtocolError('No se reconoció la lista de estudios MMRAD.')
    return exams


def parse_report_sections(markup):
    cleaned = re.sub(r'<br\s*/?>|</p>|</div>|</h[1-6]>', '\n', markup, flags=re.I)
    cleaned = unescape(re.sub(r'<[^>]+>', ' ', cleaned))
    lines = [re.sub(r'\s+', ' ', line).strip() for line in cleaned.splitlines()]
    labels = {'TECNICA':'technique', 'ANTECEDENTES CLINICOS':'antecedentes_clinicos',
              'HALLAZGOS':'findings', 'IMPRESION':'impression'}
    result = {'title':None, **{value:None for value in labels.values()}}
    first = next((line for line in lines if line), '')
    if re.search(r'TOMOGRAF|ESCANER', first, re.I):
        result['title'] = first
    current, values = None, {}
    for line in lines:
        key = line.rstrip(':').upper()
        if key in labels:
            current = labels[key]
            values.setdefault(current, [])
        elif current and re.search(r'^(?:SALUDA ATENTAMENTE|IMPRIMIR|SAVE PDF|VAR\s+|FUNCTION\s+|HTML2CANVAS|WINDOW\.OPEN|DOC\.)', line, re.I):
            current = None
        elif current and line:
            values[current].append(line)
    result.update({key:'\n'.join(value) or None for key, value in values.items()})
    return result if any(result.values()) else None


class NoRedirect(HTTPRedirectHandler):
    def http_error_301(self, req, fp, code, msg, headers):
        return fp
    http_error_302 = http_error_303 = http_error_307 = http_error_308 = http_error_301


class MMRAD:
    def __init__(self, opener=None, timeout=20):
        self.opener = ReliableOpener(opener or build_opener(NoRedirect(), HTTPSHandler(context=tls_context())))
        self.cookies = CookieJar()
        self.timeout = timeout
        self.search_action = None

    def request(self, raw_url, data=None, referer=None, pdf=False):
        url = normalize_url(raw_url)
        method = 'POST' if data is not None else 'GET'
        payload = urlencode(data).encode() if data is not None else None
        for redirects in range(6):
            headers = {'User-Agent':USER_AGENT}
            if method == 'POST':
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
            if referer:
                headers['Referer'] = referer
            request = Request(url, data=payload, headers=headers, method=method)
            request.nexo_pdf=pdf
            request.clinical_read_only = bool(data is not None and url == self.search_action)
            self.cookies.add_cookie_header(request)
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except HTTPError as error:
                if error.code not in REDIRECTS:
                    raise MMRADError('MMRAD respondió HTTP {}.'.format(error.code)) from None
                response = error
            except (URLError, OSError, TimeoutError):
                raise MMRADError('No se pudo conectar con MMRAD; revisa la red RIS.') from None
            with response:
                self.cookies.extract_cookies(response, request)
                normalize_url(response.geturl())
                status = getattr(response, 'status', None) or response.getcode()
                if status in REDIRECTS:
                    location = response.headers.get('Location')
                    if not location or redirects >= 5:
                        raise MMRADProtocolError('Redirección MMRAD no válida o excesiva.')
                    url = normalize_url(location, url)
                    if status == 303 or (status in (301, 302) and method == 'POST'):
                        method, payload = 'GET', None
                    continue
                if not 200 <= status < 300:
                    raise MMRADError('MMRAD respondió HTTP {}.'.format(status))
                limit = 32 * 1024 * 1024 if pdf else 8 * 1024 * 1024
                content = response.read(limit + 1)
                if len(content) > limit:
                    raise MMRADError('La respuesta de MMRAD supera el límite permitido.')
                if pdf:
                    if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
                        raise MMRADError('El enlace informePDF no devolvió un PDF completo.')
                    return content
                charset = response.headers.get_content_charset() or 'utf-8'
                try:
                    return content.decode(charset)
                except (UnicodeError, LookupError):
                    return content.decode('latin-1')
        raise MMRADProtocolError('Demasiadas redirecciones MMRAD.')

    def viewer_request(self, raw_url, data=None, referer=None, limit=128 * 1024 * 1024):
        """Same CookieJar as RIS, but confined to the observed viewer origin."""
        url = normalize_viewer_url(raw_url)
        method = 'POST' if data is not None else 'GET'
        for redirects in range(6):
            headers = {'User-Agent':USER_AGENT}
            if referer:
                headers['Referer'] = normalize_viewer_url(referer)
            if data is not None:
                headers['Content-Type'] = 'text/plain;charset=UTF-8'
            request = Request(url, data=data, headers=headers, method=method)
            self.cookies.add_cookie_header(request)
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except HTTPError as error:
                if error.code not in REDIRECTS:
                    raise MMRADError('El visor MMRAD respondió HTTP {}.'.format(error.code)) from None
                response = error
            except (URLError, OSError, TimeoutError):
                raise MMRADError('No se pudo conectar con el visor MMRAD.') from None
            with response:
                self.cookies.extract_cookies(response, request)
                normalize_viewer_url(response.geturl())
                status = getattr(response, 'status', None) or response.getcode()
                if status in REDIRECTS:
                    location = response.headers.get('Location')
                    if not location or redirects >= 5:
                        raise MMRADProtocolError('Redirección del visor inválida o excesiva.')
                    url = normalize_viewer_url(location, url)
                    if status == 303 or (status in (301, 302) and method == 'POST'):
                        method, data = 'GET', None
                    continue
                if not 200 <= status < 300:
                    raise MMRADError('El visor MMRAD respondió HTTP {}.'.format(status))
                content = response.read(limit + 1)
                if len(content) > limit:
                    raise MMRADError('La imagen del visor supera el límite permitido.')
                return content
        raise MMRADProtocolError('Demasiadas redirecciones del visor.')

    def viewer_metadata(self, viewer_url, study):
        self.viewer_request(VIEWER_BASE + '/sockjs/info', referer=viewer_url, limit=1024 * 1024)
        server = '{:03d}'.format(secrets.randbelow(1000))
        session = secrets.token_hex(8)
        transport = VIEWER_BASE + '/sockjs/' + server + '/' + session
        self.viewer_request(transport + '/xhr', b'', referer=viewer_url, limit=8 * 1024 * 1024)
        def send(message):
            payload = json.dumps([json.dumps(message, separators=(',', ':'))], separators=(',', ':')).encode()
            self.viewer_request(transport + '/xhr_send', payload, referer=viewer_url, limit=1024 * 1024)
        send({'msg':'connect', 'version':'1', 'support':['1','pre2','pre1']})
        deadline = time.monotonic() + 60
        connected = False
        while time.monotonic() < deadline:
            messages = sockjs_messages(self.viewer_request(transport + '/xhr', b'', referer=viewer_url, limit=8 * 1024 * 1024))
            if any(message.get('msg') == 'connected' for message in messages):
                connected = True
                break
        if not connected:
            raise MMRADError('El visor no confirmó la sesión DDP.')
        send({'msg':'method', 'method':'GetStudyMetadata', 'params':[study], 'id':'1'})
        while time.monotonic() < deadline:
            messages = sockjs_messages(self.viewer_request(transport + '/xhr', b'', referer=viewer_url, limit=8 * 1024 * 1024))
            for message in messages:
                if message.get('msg') == 'result' and message.get('id') == '1':
                    if message.get('error'):
                        raise MMRADError('El visor no autorizó los metadatos del estudio.')
                    if not isinstance(message.get('result'), dict):
                        raise MMRADProtocolError('Metadatos DICOM vacíos o inválidos.')
                    return message['result']
        raise MMRADError('El visor agotó el tiempo al obtener las series DICOM.')

    def image_instances(self, exam):
        reason = image_exclusion(exam, getattr(self, 'image_types', None))
        if reason:
            raise ExcludedStudyImages(reason)
        if not exam.get('dicom_url'):
            raise NoStudyImages('Este estudio no ofrece visor DICOM.')
        markup = self.request(exam['dicom_url'], referer=PANEL)
        viewer_url, study = viewer_from_html(markup)
        metadata = self.viewer_metadata(viewer_url, study)
        if is_echocardiography(metadata):
            raise ExcludedStudyImages('Ecocardiografía identificada en el visor: imágenes excluidas.')
        return viewer_url, ordered_instances(metadata, study)

    def download_dicom_isolated(self, viewer_url, item):
        import copy
        worker = MMRAD(timeout=self.timeout)
        for cookie in self.cookies:
            worker.cookies.set_cookie(copy.copy(cookie))
        return worker.download_dicom(viewer_url, item)

    def download_dicom(self, viewer_url, item):
        content = self.viewer_request(item['url'], referer=viewer_url)
        validate_dicom(content, item['study_uid'], item['series_uid'], item['sop_uid'])
        return content

    def login(self, username, password):
        if not username or not password:
            raise AuthenticationError('Faltan credenciales propias de MMRAD.')
        home = self.request(BASE + '/web/guest/home')
        action = form_action(home, 'login%2Flogin')
        if not action:
            raise AuthenticationError('No se encontró el formulario de ingreso MMRAD.')
        dashboard = self.request(action, {'_58_login':username, '_58_password':password,
                                          '_58_redirect':'/web/guest/home', '_58_rememberMe':'false'})
        self.search_action = form_action(dashboard, 'examenportlet')
        if not self.search_action:
            raise AuthenticationError('Falló el ingreso a MMRAD: no apareció el panel de búsqueda.')

    def search(self, rut, period, today, reports_only=False, images_only=False):
        if not self.search_action:
            raise AuthenticationError('No hay sesión MMRAD autenticada.')
        windows = [date_filters(period, today)] if period != 'latest' else [
            date_filters(name, today) for name in ('30d', '6m', '1y', '2y', '5y')
        ] + [('01/01/1900', today.strftime('%d/%m/%Y'))]
        first_found = []
        for since, until in windows:
            data = {'idpaciente':rut, 'fechaexamendesde':since, 'fechaexamenhasta':until}
            markup = self.request(self.search_action, data, referer=PANEL)
            if '_58_login' in markup and 'examenportlet' not in markup:
                raise AuthenticationError('La sesión MMRAD venció durante la búsqueda.')
            exams = parse_exams(markup, rut)
            if reports_only and 'ct_reports' in (getattr(self,'content',None) or []):
                exams=[exam for exam in exams if str(exam.get('modality') or '').upper()=='CT']
            if exams:
                if not first_found:
                    first_found = exams
                if not (period == 'latest' and (reports_only or images_only)) or any(
                        (image_exclusion(exam, getattr(self, 'image_types', None)) is None if images_only else
                         exam.get('pdf_url') or str(exam.get('modality') or '').upper() == 'CT')
                        for exam in exams):
                    return exams
        return first_found

    def download(self, exam):
        if not exam.get('pdf_url'):
            kind = exam.get('report_type')
            label = {'html':'solo informe HTML', 'receipt':'solo comprobante',
                     'dicom':'solo visor DICOM', 'none':'sin informe PDF'}.get(kind, 'sin informe PDF')
            raise NoPdfReport('El estudio tiene {}, no un informe PDF.'.format(label))
        url = normalize_url(exam['pdf_url'])
        if 'informepdf' not in urlsplit(url).path.lower():
            raise MMRADProtocolError('El enlace no corresponde a informePDF de MMRAD.')
        return self.request(url, referer=PANEL, pdf=True)

    def report_sections(self, exam):
        """Lee secciones estructuradas de un informe HTML, sin convertirlo en PDF."""
        if not exam.get('html_url'):
            return None
        markup = self.request(normalize_url(exam['html_url']), referer=PANEL)
        return parse_report_sections(markup)


def local_credentials():
    username, password = os.environ.get('MMRAD_USERNAME'), os.environ.get('MMRAD_PASSWORD')
    if username and password:
        return username, password
    if sys.platform == 'darwin':
        def keychain(service):
            try:
                result = subprocess.run(['security', 'find-generic-password', '-s', service, '-w'],
                                        capture_output=True, text=True, timeout=5)
                return result.stdout.strip() if result.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                return None
        username = username or keychain('MMRAD_USERNAME')
        password = password or keychain('MMRAD_PASSWORD')
    if not username or not password:
        raise AuthenticationError('Faltan MMRAD_USERNAME/MMRAD_PASSWORD o entradas equivalentes en el llavero local.')
    return username, password
