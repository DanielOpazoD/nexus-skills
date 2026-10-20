"""Atenciones de Rayen/Eloísa: consulta por RUN y PDF local por atención.

La ruta y los campos siguen el flujo público de rayen-extension. No conserva token
ni respuestas clínicas fuera de los PDF solicitados y el avance del unificado.
"""
from datetime import datetime, date
from hashlib import sha256
from io import BytesIO
import copy
import json
import re
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph

_COMMON = Path(__file__).resolve().parents[2] / 'laboratorios-descargas' / 'scripts'
if _COMMON.is_dir() and str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))
from clinical_transport import ReliableOpener, tls_context
sys.path.insert(0,str(Path(__file__).resolve().parent))
from eloisa_attachments import enumerate_attachments, download as download_attachment, validate as validate_attachment


ORIGIN = 'https://clinicohangaroa.eloisa.cl'
NODE_ID = 5576
FLAGS = ('Actividades Diagnosticos Prescripciones ExamenesSolicitados EspecialidadesDerivadas '
         'ExamenesFisicos ItemsExamenesSegmentarios Indicaciones PrescripcionesExtraConsultorio '
         'OrdenesAtencionInterna Anamnesis FuncionariosPrestadores Recetas '
         'OrdenAtencionPruebaDiagnostica EpisodioAtencion Enmendaciones '
         'LicenciasMedicasElectronicasOtorgadas').split()
SECTIONS = {
    'Prescripciones': 'Prescripciones', 'Recetas': 'Recetas',
    'PrescripcionesExtraConsultorio': 'Prescripciones extra-consultorio',
    'ExamenesSolicitados': 'Exámenes solicitados', 'OrdenesExamenes': 'Exámenes solicitados',
    'OrdenAtencionPruebaDiagnostica': 'Pruebas diagnósticas',
    'Indicaciones': 'Indicaciones', 'OrdenAtencionInterna': 'Próximo control',
    'OrdenesAtencionInterna': 'Próximo control', 'EspecialidadesDerivadas': 'Derivaciones',
    'SolicitudesInterconsulta': 'Interconsultas', 'OrdenesAtencion': 'Órdenes de atención',
    'LicenciasMedicasElectronicasOtorgadas': 'Licencias médicas', 'LicenciasMedicas': 'Licencias médicas',
    'ExamenesFisicos': 'Examen físico', 'ItemsExamenesSegmentarios': 'Examen físico',
    'Alergias': 'Alergias', 'Habitos': 'Hábitos', 'FactoresRiesgos': 'Factores de riesgo',
    'MorbidosPersonalesMedicos': 'Antecedentes mórbidos',
    'MorbidosPersonalesQuirurgicos': 'Antecedentes quirúrgicos',
    'MorbidosFamiliares': 'Antecedentes familiares', 'Enmendaciones': 'Enmendaciones',
}
MEDICAL = re.compile(r'm[eé]dic|morbilidad|urgencia|cirug|anestes|traumat|ginec|obstet|pediatr|internist|psiquiatr|control\s+(?:cr[oó]nico|salud)', re.I)
NON_MEDICAL = re.compile(r'kinesi|nutric|odont|dental|matron|enfermer|psic[oó]log|taller|fonoaud|terapeuta|trabaj|social|param[eé]dic|podolog', re.I)


class EloisaError(Exception):
    pass


class SessionExpired(EloisaError):
    pass


def canonical_rut(value):
    raw = re.sub(r'[^0-9Kk]', '', str(value or '')).upper()
    if len(raw) < 2 or not raw[:-1].isdigit():
        raise EloisaError('Eloísa devolvió un RUT inválido.')
    return str(int(raw[:-1])) + '-' + raw[-1]


def clinical_date(row):
    cita = str(row.get('FechaCita') or '')
    raw = cita if re.match(r'^\d{8} \d{4,6}$', cita) and not cita.startswith('00010101') else str(row.get('Fecha') or '')
    try:
        return datetime.strptime(raw[:15], '%Y%m%d %H%M%S')
    except ValueError:
        try:
            return datetime.strptime(raw[:8], '%Y%m%d')
        except ValueError:
            raise EloisaError('Una atención no trae una fecha clínica válida.') from None


def is_medical(row):
    people = row.get('FuncionariosPrestadores') or []
    if people:
        return any(MEDICAL.search(str(p.get('NombreInstrumento') or '')) and
                   not NON_MEDICAL.search(str(p.get('NombreInstrumento') or '')) for p in people)
    kind = str(row.get('TipoDeAtencion') or '')
    return not NON_MEDICAL.search(kind) and bool(MEDICAL.search(kind))


RX_KEYS = {'Prescripciones', 'Recetas', 'PrescripcionesExtraConsultorio'}
REFERRAL_KEYS = {'EspecialidadesDerivadas', 'SolicitudesInterconsulta'}
META_KEYS = {'Id', 'RutPaciente', 'NombreCompleto', 'Fecha', 'FechaCita', 'TipoDeAtencion', 'FuncionariosPrestadores'}

def note_kind(row):
    people = row.get('FuncionariosPrestadores') or []
    labels = [str(p.get('NombreInstrumento') or '') for p in people] if people else [str(row.get('TipoDeAtencion') or '')]
    kinds = {'other' if NON_MEDICAL.search(label) else 'medical' if MEDICAL.search(label) else None for label in labels}
    return next(iter(kinds)) if len(kinds) == 1 else None

def project_content(row, content):
    """Filter structured categories, not words inside the selected clinical prose."""
    kind = note_kind(row)
    notes = kind in content if kind else False
    selected = copy.deepcopy(row if notes else {k:v for k,v in row.items() if k in META_KEYS})
    for option, keys in [('prescriptions',RX_KEYS),('referrals',REFERRAL_KEYS)]:
        for key in keys:
            if option in content and row.get(key): selected[key] = copy.deepcopy(row[key])
            else: selected.pop(key,None)
    selected.pop('ArchivosAdjunto',None)
    has_data = any(v not in (None,'',[],{}) for k,v in selected.items() if k not in META_KEYS)
    return selected if has_data else None

class SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme + '://' + urlsplit(newurl).netloc != ORIGIN:
            raise EloisaError('Eloísa redirigió a otro sitio; se detuvo la consulta.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Eloisa:
    def __init__(self, session, scope='medicos', node_id=NODE_ID, content=None):
        if not isinstance(session, dict) or not isinstance(session.get('access_token'), str) or not session['access_token']:
            raise SessionExpired('Falta la sesión de Eloísa en Chrome.')
        if scope not in ('medicos', 'todos'):
            raise EloisaError('Alcance de atenciones no reconocido.')
        self.token = session['access_token']
        from clinical_content import normalize_source_content
        self.content = normalize_source_content({"eloisa":content},["eloisa"])["eloisa"] if content is not None else None
        self.pending_records = []
        self.scope = scope
        self.node_id = int(node_id)
        context = tls_context()
        if sys.platform == 'darwin':
            for bundle in ('/opt/homebrew/etc/openssl@3/cert.pem',
                           '/usr/local/etc/openssl@3/cert.pem', '/etc/ssl/cert.pem'):
                if Path(bundle).is_file():
                    context.load_verify_locations(bundle)
        self.opener = ReliableOpener(build_opener(HTTPSHandler(context=context), SameOriginRedirect()))

    def request(self, path, body=None):
        if not path.startswith('/API/api/rayen/') or urlsplit(path).scheme or urlsplit(path).netloc:
            raise EloisaError('Ruta de Eloísa no permitida.')
        data = json.dumps(body).encode() if body is not None else None
        req = Request(ORIGIN + path, data=data, headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json',
            'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'},
            method='POST' if data is not None else 'GET')
        req.clinical_read_only = path == '/API/api/rayen/FichaClinica/HistorialAtencion'
        try:
            with self.opener.open(req, timeout=90 if data is not None else 25) as response:
                final = urlsplit(response.url)
                if final.scheme + '://' + final.netloc != ORIGIN:
                    raise EloisaError('Respuesta de un origen inesperado.')
                if '/login' in final.path.lower() or 'text/html' in response.headers.get('Content-Type', '').lower():
                    raise SessionExpired('La sesión de Eloísa venció. Vuelve a entrar en Chrome.')
                raw = response.read(64 * 1024 * 1024 + 1)
                if len(raw) > 64 * 1024 * 1024:
                    raise EloisaError('La respuesta clínica excede el límite permitido.')
                if raw.lstrip().startswith(b'<'):
                    raise SessionExpired('La sesión de Eloísa venció. Vuelve a entrar en Chrome.')
                return json.loads(raw)
        except HTTPError as error:
            if error.code in (401, 403):
                raise SessionExpired('La sesión de Eloísa venció. Vuelve a entrar en Chrome.') from None
            raise EloisaError('Eloísa respondió con HTTP {}.'.format(error.code)) from None
        except (URLError, TimeoutError, ValueError) as error:
            raise EloisaError('No se pudo consultar Eloísa: {}.'.format(type(error).__name__)) from None

    def search(self, rut, today=None, since=None):
        self.pending_records = []
        expected = canonical_rut(rut)
        master = self.request('/API/api/rayen/Inscripcion/UsuarioApsRut/{}/{}'.format(expected.replace('-', '').lower(), self.node_id))
        if isinstance(master, list):
            master = next((row for row in master if isinstance(row, dict) and canonical_rut(row.get('Rut')) == expected), None)
        if not master:
            return []
        if canonical_rut(master.get('Rut')) != expected:
            raise EloisaError('La ficha encontrada corresponde a otro paciente.')
        patient_id = master.get('Id') or master.get('IdUsp')
        if not re.fullmatch(r'[0-9]{1,12}', str(patient_id or '')) or int(patient_id) <= 0:
            raise EloisaError('La ficha de Eloísa no tiene IdUsuario válido.')
        patient_id = int(patient_id)
        today = today or date.today()
        start = since or today.replace(year=today.year - 10, day=min(today.day, 28) if today.month == 2 else today.day)
        if start > today:
            raise EloisaError('Período de consulta inválido.')
        payload = {'IdUsuario': patient_id, 'IdFuncionarioPrestador': None,
                   'FechaInicio': start.strftime('%Y%m%d 000000'),
                   'FechaTermino': today.strftime('%Y%m%d 235900')}
        payload.update({'Traer' + key: True for key in FLAGS})
        history = self.request('/API/api/rayen/FichaClinica/HistorialAtencion', payload)
        if not isinstance(history, list):
            raise EloisaError('El historial de Eloísa no tiene el formato esperado.')
        result = []
        for row in history:
            if not isinstance(row, dict) or canonical_rut(row.get('RutPaciente')) != expected:
                raise EloisaError('El historial contiene una atención de otro paciente.')
            if self.content is None and self.scope == 'medicos' and not is_medical(row):
                continue
            identifier = row.get('Id')
            if not re.fullmatch(r'[0-9]{1,12}', str(identifier or '')) or int(identifier) <= 0:
                raise EloisaError('Una atención no tiene identificador válido.')
            when = clinical_date(row)
            if not start <= when.date() <= today: continue
            name = str(master.get('NombreFormateado') or row.get('NombreCompleto') or '')
            if self.content is not None and 'attachments' in self.content:
                try:
                    attached,pending=enumerate_attachments(row,patient_id,self.node_id,expected,name,when)
                    result.extend(attached);self.pending_records.extend(pending)
                except Exception as error:
                    self.pending_records.append({'episode':identifier,'report_type':'attachment','reason':str(error)})
            if self.content is not None:
                if note_kind(row) is None and any(x in self.content for x in ('medical','other')):
                    self.pending_records.append({'episode':identifier,'reason':'Profesión no identificable; evolución pendiente de clasificación.'})
                row = project_content(row,self.content)
                if row is None: continue
            name = str(master.get('NombreFormateado') or row.get('NombreCompleto') or '')
            fingerprint = sha256(json.dumps({'visit': row, 'name': name}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            result.append({'id': str(identifier), 'datetime': when, 'rut': expected,
                           'name': name, 'raw': row, 'fingerprint': fingerprint, 'content': self.content})
        return sorted(result,key=lambda e:e.get('validation',{}).get('kind')=='attachment')

    def download(self, exam):
        if exam.get('validation',{}).get('kind')=='attachment':return download_attachment(self,exam)
        return render_pdf(exam)


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def details(value, depth=0):
    if depth > 2:
        return []
    if isinstance(value, dict):
        result = []
        for key, child in value.items():
            if re.search(r'^(Rut|Token|Url|Guid|IdUsuario|IdFuncionario|IdNodo)', key, re.I) or child in (None, '', [], {}):
                continue
            if isinstance(child, (dict, list)):
                result.extend(details(child, depth + 1))
            elif isinstance(child, (str, int, float)):
                result.append('{}: {}'.format(re.sub(r'([a-z])([A-Z])', r'\1 \2', key), clean(child)))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(details(item, depth + 1))
        return result
    return [clean(value)] if value not in (None, '') else []


def render_pdf(exam):
    row = exam['raw']
    rut, identifier = exam['rut'], exam['id']
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Clinical', parent=styles['Normal'], fontSize=9, leading=13, spaceAfter=5, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name='ClinicalHeading', parent=styles['Heading2'], fontSize=11, leading=15, spaceBefore=11, spaceAfter=5))
    story = []
    def para(value, style='Clinical'):
        story.append(Paragraph(escape(clean(value)).replace('\n', '<br/>'), styles[style]))
    para('Atención clínica · Rayen / Eloísa', 'Title')
    para('Paciente: {}'.format(exam.get('name') or row.get('NombreCompleto') or 'Sin nombre'))
    para('RUN: {}    ID de atención: {}'.format(rut, identifier))
    para('Fecha clínica: {}    Tipo: {}'.format(exam['datetime'].strftime('%d-%m-%Y %H:%M'), clean(row.get('TipoDeAtencion'))))
    if row.get('Fecha') and str(row['Fecha'])[:8] != exam['datetime'].strftime('%Y%m%d'):
        try:
            registered = datetime.strptime(str(row['Fecha'])[:8], '%Y%m%d').strftime('%d-%m-%Y')
        except ValueError:
            registered = str(row['Fecha'])[:8]  # Valor de origen no interpretable.
        para('Fecha de registro: {}'.format(registered))
    people = row.get('FuncionariosPrestadores') or []
    if people:
        para('Prestadores: ' + '; '.join(clean(p.get('NombreCompleto')) + ' (' + clean(p.get('NombreInstrumento')) + ')' for p in people))
    if row.get('Diagnosticos'):
        para('Diagnósticos', 'ClinicalHeading')
        for item in row['Diagnosticos']:
            para('• ' + ' · '.join(filter(None, (clean(item.get('DescripcionDiagnostico')), clean(item.get('CodigoCIE10')), clean(item.get('DescripcionClasificacion'))))))
    for anam in row.get('Anamnesis') or []:
        for key, label in (('MotivoConsulta', 'Motivo de consulta'), ('HistoriaEnfermedadActual', 'Historia / evolución')):
            if anam.get(key):
                para(label, 'ClinicalHeading')
                para(anam[key])
    for key, label in SECTIONS.items():
        items = row.get(key)
        if not isinstance(items, list) or not items:
            continue
        para(label, 'ClinicalHeading')
        for item in items:
            fields = details(item)
            if fields:
                para('• ' + ' · '.join(fields))
    extras = []
    skip = set(SECTIONS) | {'Diagnosticos', 'Anamnesis', 'FuncionariosPrestadores', 'Actividades'}
    episode = row.get('EpisodioAtencion') or []
    episodes = episode if isinstance(episode, list) else [episode]
    for container in [row, *(row.get('Anamnesis') or []), *episodes]:
        if not isinstance(container, dict):
            continue
        for key, value in container.items():
            if key in skip or key in ('MotivoConsulta', 'HistoriaEnfermedadActual') or re.search(r'Id|Codigo|Rut|Fecha|Hora|Nombre|Apellido|Token', key, re.I):
                continue
            if isinstance(value, str) and len(value.strip()) >= 20 and ' ' in value.strip():
                entry = (key, clean(value))
                if entry not in extras:
                    extras.append(entry)
    for key, value in extras:
        para(re.sub(r'([a-z])([A-Z])', r'\1 \2', key), 'ClinicalHeading')
        para(value)
    if row.get('Actividades'):
        para('Actividades', 'ClinicalHeading')
        for item in row['Actividades']:
            para('• ' + clean(item.get('Descripcion') or item.get('CodigoActividad')))
    if exam.get('content'):
        para('Contenido seleccionado: '+', '.join({'medical':'evoluciones médicas','other':'otros profesionales','prescriptions':'recetas','referrals':'interconsultas','attachments':'adjuntos originales entregados por separado'}[x] for x in exam['content']))
    para('Copia de trabajo generada desde Rayen/Eloísa. Verificar en la ficha clínica.')
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=44, rightMargin=44, topMargin=58, bottomMargin=50)
    def page_header(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(44, A4[1] - 35, 'RUN: {}    ID de atención: {}'.format(rut, identifier))
        canvas.drawRightString(A4[0] - 44, 31, 'Página {}'.format(document.page))
        canvas.restoreState()
    doc.build(story, onFirstPage=page_header, onLaterPages=page_header)
    return buffer.getvalue()
