"""HIS Hanga Roa: authenticated RUT history and locally rendered clinical PDFs.

The search/login/parser code is adapted from DanielOpazoD/his-reports at
0ec98caa42676c30599a8ae3990bee7ac1052f83. HIS serves HTML fichas,
not ready-made PDF files; generated PDFs are identified as working copies.
"""
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import socket
import sys
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from his_reports import auth, scrape
from his_reports.errors import HISError
from his_reports.session import reset_default_session


class HisError(Exception):
    pass


class AuthenticationError(HisError):
    pass


class SiteUnavailable(HisError):
    pass


def canonical_rut(value):
    raw = re.sub(r'[^0-9Kk]', '', str(value or '')).upper()
    if not re.fullmatch(r'[0-9]{7,8}[0-9K]', raw):
        raise HisError('HIS devolvió un RUT sin formato verificable.')
    body, digit = raw[:-1], raw[-1]
    total = sum(int(number) * (2 + index % 6) for index, number in enumerate(reversed(body)))
    check = 11 - total % 11
    expected = '0' if check == 11 else 'K' if check == 10 else str(check)
    if digit != expected:
        raise HisError('HIS devolvió un RUT con dígito verificador inválido.')
    return str(int(body)) + '-' + digit


def date_from_his(value):
    text = str(value or '').strip()
    for pattern in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(text[:10], pattern)
        except ValueError:
            pass
    raise HisError('La atención HIS no tiene una fecha clínica válida.')


def checked_ficha(ficha, exam):
    if not isinstance(ficha, dict):
        raise HisError('La ficha HIS no tiene el formato esperado.')
    if str(ficha.get('idCuenta') or '') != str(exam['id']):
        raise HisError('La ficha HIS tiene un ID de atención distinto.')
    if ficha.get('tipoFicha') != exam['type']:
        raise HisError('La ficha HIS tiene un tipo de atención distinto.')
    patient = ficha.get('paciente') or {}
    if not isinstance(patient, dict) or canonical_rut(patient.get('rut')) != exam['rut']:
        raise HisError('La ficha HIS corresponde a otro paciente.')
    meta = ficha.get('atencionMeta') or {}
    if not isinstance(meta, dict):
        raise HisError('La ficha HIS no tiene metadatos válidos.')
    clinical_day = meta.get('fechaAtencion') or meta.get('fechaIngreso')
    if clinical_day and date_from_his(clinical_day).date() != exam['datetime'].date():
        raise HisError('La fecha de la ficha HIS no coincide con la lista.')
    labels = ficha.get('_raw_labels') or {}
    if not isinstance(labels, dict) or len(labels) < 3:
        raise HisError('La ficha HIS está incompleta o no contiene datos clínicos.')
    return ficha


def render_pdf(exam, ficha):
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='HisField', parent=styles['Normal'], fontSize=9, leading=13, spaceAfter=7))
    styles.add(ParagraphStyle(name='HisSection', parent=styles['Heading2'], fontSize=11, leading=15, spaceBefore=10, spaceAfter=5))
    story = []

    def paragraph(value, style='HisField'):
        value = escape(str(value or '').strip()).replace('\n', '<br/>')
        if value:
            story.append(Paragraph(value, styles[style]))

    paragraph('Atención HIS · Hospital Hanga Roa', 'Title')
    paragraph('Paciente: {}'.format(ficha['paciente'].get('nombre') or 'Nombre no disponible'))
    paragraph('RUN: {}    ID de atención: {}'.format(exam['rut'], exam['id']))
    paragraph('Fecha clínica: {}    Tipo: {}'.format(exam['datetime'].strftime('%d-%m-%Y'),
                                                   exam['type'].title()))
    doctor = (ficha.get('atencionMeta') or {}).get('medico')
    if doctor:
        paragraph('Profesional: {}'.format(doctor))
    story.append(Spacer(1, 8))
    for label, value in ficha['_raw_labels'].items():
        if not isinstance(value, str) or not value.strip():
            continue
        story.append(Paragraph(escape(str(label).title()), styles['HisSection']))
        paragraph(value)
    vitals = ficha.get('signosVitales') or {}
    if isinstance(vitals, dict) and any(vitals.values()):
        story.append(Paragraph('Signos vitales', styles['HisSection']))
        for key, value in vitals.items():
            if value:
                paragraph('{}: {}'.format(key, value))
    paragraph('Copia de trabajo generada desde HIS. Verificar en la ficha clínica.')

    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=44, rightMargin=44,
                            topMargin=58, bottomMargin=50)

    def header(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(44, A4[1] - 35, 'RUN: {}    ID de atención: {}'.format(exam['rut'], exam['id']))
        canvas.drawRightString(A4[0] - 44, 31, 'Página {}'.format(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=header, onLaterPages=header)
    return buffer.getvalue()


class HIS:
    def login(self, username, password):
        if not username or not password:
            raise AuthenticationError('Faltan las credenciales propias del HIS.')
        try:
            with socket.create_connection(('his.hospitalhangaroa.cl', 443), timeout=2):
                pass
        except OSError:
            raise SiteUnavailable('HIS no es accesible desde esta red; prueba de nuevo desde una red habilitada.') from None
        reset_default_session()
        try:
            ok, message = auth.try_login(username, password)
        except HISError as error:
            if error.status in (429, 502, 503, 504):
                raise SiteUnavailable('HIS temporalmente inaccesible durante el acceso.') from None
            raise AuthenticationError('No se pudo iniciar sesión en HIS: {}.'.format(error.message)) from None
        if not ok:
            raise AuthenticationError('No se pudo iniciar sesión en HIS: {}.'.format(message))

    def search(self, rut):
        expected = canonical_rut(rut)
        try:
            rows = scrape.fetch_consficha_por_rut(expected.split('-')[0], expected)
        except HISError as error:
            if error.status in (401, 403):
                raise AuthenticationError('La sesión HIS venció o no tiene permiso.') from None
            if error.status in (429, 502, 503, 504):
                raise SiteUnavailable('HIS temporalmente inaccesible; reanudar posteriormente.') from None
            raise HisError('HIS no pudo buscar el RUT (HTTP {}).'.format(error.status)) from None
        if not isinstance(rows, list):
            raise HisError('HIS no devolvió un historial reconocible.')
        exams, seen = [], {}
        for row in rows:
            if not isinstance(row, dict):
                raise HisError('HIS devolvió una fila no reconocible.')
            identifier = str(row.get('idCuenta') or '')
            kind = row.get('tipoFicha')
            if not re.fullmatch(r'[0-9]{1,10}', identifier) or kind not in ('urgencia','ambulatorio'):
                raise HisError('HIS devolvió una atención sin ID o tipo verificable.')
            if canonical_rut(row.get('rut')) != expected:
                raise HisError('El historial HIS corresponde a otro paciente.')
            stamp = date_from_his(row.get('fecha'))
            if identifier in seen and seen[identifier] != kind:
                raise HisError('HIS devolvió el mismo ID para dos tipos de atención.')
            if identifier in seen:
                continue
            seen[identifier] = kind
            exams.append({'id':identifier, 'datetime':stamp, 'rut':expected,
                          'type':kind, 'name':str(row.get('nombre') or ''),
                          'fingerprint':sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()})
        return exams

    def download(self, exam):
        try:
            ficha = scrape.fetch_ficha(exam['id'], exam['type'])
        except HISError as error:
            if error.status in (401, 403):
                raise AuthenticationError('La sesión HIS venció o no tiene permiso.') from None
            if error.status in (429, 502, 503, 504):
                raise SiteUnavailable('HIS temporalmente inaccesible; reanudar posteriormente.') from None
            raise HisError('No se pudo leer la atención HIS {} (HTTP {}).'.format(exam['id'], error.status)) from None
        checked_ficha(ficha, exam)
        exam['name'] = str(ficha['paciente'].get('nombre') or '')
        return render_pdf(exam, ficha)
