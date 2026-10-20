#!/usr/bin/env python3
"""Cliente de lectura de epicrisis Rayen. Sesión exclusivamente por stdin."""
import argparse
from datetime import date, datetime
import hashlib
import io
import json
from pathlib import Path
import re
import ssl
import sys
import tempfile
import unicodedata
import os
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

_COMMON = Path(__file__).resolve().parents[2] / 'laboratorios-descargas' / 'scripts'
if _COMMON.is_dir() and str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))
from clinical_transport import SourceUnavailable, ReliableOpener, tls_context


BASE = 'https://fichamedicoback.rayensalud.cl/api'
LIST_PATH = '/inpatientReport/getEpicrisisyReport'
PDF_PATH = '/report/Reporte_Epicrisis.pdf'

class ReportError(Exception):
    pass

class SessionExpired(ReportError):
    pass

class NoPdfReport(ReportError):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReportError('Redirección inesperada; revisar sesión sin reenviar credenciales.')

def rut_normalized(value):
    value = str(value).strip().upper().replace('.', '').replace('-', '')
    if not re.fullmatch(r'\d{7,8}[0-9K]', value):
        raise ReportError('RUN inválido: se requiere cuerpo y dígito verificador.')
    body, check = value[:-1], value[-1]
    total = sum(int(n) * (2 + i % 6) for i, n in enumerate(reversed(body)))
    dv = 11 - total % 11
    expected = '0' if dv == 11 else 'K' if dv == 10 else str(dv)
    if check != expected:
        raise ReportError('El dígito verificador del RUN no coincide.')
    return body + check

def valid_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0

def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.estado-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)

class Client:
    def __init__(self, session, transport=None):
        self.token = session.get('token')
        self.facility = session.get('facilityId')
        if not isinstance(self.token, str) or not self.token or '\n' in self.token or '\r' in self.token or not valid_id(self.facility):
            raise SessionExpired('Falta una sesión válida del Registro Hospitalario.')
        self.transport = transport
        context = tls_context()
        if Path('/etc/ssl/cert.pem').exists():
            context.load_verify_locations('/etc/ssl/cert.pem')
        self.opener = ReliableOpener(urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context)))

    def get(self, path, params, pdf=False, conditional=None):
        if path not in (LIST_PATH, PDF_PATH, '/inpatientReport/getEncounterHistoryReport'):
            raise ReportError('Ruta fuera del alcance del cliente.')
        url = BASE + path + '?' + urllib.parse.urlencode(params)
        # Authorization se conserva como lo entrega la sesión: no agregar Bearer por suposición.
        request = urllib.request.Request(url, headers={'Authorization': self.token, 'Accept': 'application/pdf' if pdf else 'application/json'}, method='GET')
        self.response_headers = {}
        for key, value in (conditional or {}).items():
            if key in ('If-None-Match', 'If-Modified-Since'):
                request.add_header(key, value)
        if self.transport:
            return self.transport(request)
        try:
            with self.opener.open(request, timeout=60) as response:
                limit = 64 * 1024 * 1024 if pdf else 8 * 1024 * 1024
                content = response.read(limit + 1)
                if len(content) > limit: raise ReportError('Respuesta excede el tamaño admitido.')
                if pdf and getattr(response, 'status', None) == 204:
                    raise NoPdfReport('Epicrisis sin PDF disponible: respuesta HTTP 204 del servidor.')
                self.response_headers = dict(response.headers)
                return content
        except urllib.error.HTTPError as error:
            if error.code == 304 and conditional:
                error.close()
                return None
            if error.code in (401, 403):
                raise SessionExpired('Acceso rechazado: renovar sesión o comprobar permisos.') from None
            raise ReportError('El servidor devolvió HTTP {}.'.format(error.code)) from None
        except (urllib.error.URLError, TimeoutError):
            raise ReportError('No se pudo contactar al servidor.') from None

    def episodes(self, rut, start, end, history=False):
        rut = rut_normalized(rut)
        # La UI RUN no envía fechas. Filtrar localmente por egreso evita asumir semántica backend.
        raw = self.get('/inpatientReport/getEncounterHistoryReport' if history else LIST_PATH, {'prefferedPeridentId': 2, 'prefferedIdentifierCode': rut,
                                  'facilityId': self.facility, 'dateFrom': '', 'dateTo': ''})
        try: payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError): raise ReportError('Respuesta de búsqueda no reconocida.') from None
        if isinstance(payload, dict):
            if payload.get('ok') is False or payload.get('success') is False or payload.get('error'):
                raise ReportError('La API informó un error; no equivale a cero epicrisis.')
            rows = payload.get('data')
        else: rows = payload
        if not isinstance(rows, list): raise ReportError('Estructura de búsqueda no reconocida.')
        selected, pending, seen = [], [], set()
        for row in rows:
            if not isinstance(row, dict): raise ReportError('Registro de búsqueda no reconocido.')
            enc = row.get('encounterId')
            if not valid_id(enc) or not valid_id(row.get('patientId')): raise ReportError('Episodio sin identificador verificable.')
            if row.get('facilityId') != self.facility or row.get('patientIdentifierTypeId') != 2 or rut_normalized(row.get('patientIdentifier', '')) != rut:
                raise ReportError('La identidad o establecimiento de la respuesta no coincide.')
            if not isinstance(row.get('patientName'), str) or not row['patientName'].strip(): raise ReportError('Paciente sin nombre verificable.')
            if row.get('deleted') is True: continue
            if history:
                try:
                    admitted = date.fromisoformat(str(row.get('startPeriod',''))[:10])
                    discharged = date.fromisoformat(str(row['endPeriod'])[:10]) if row.get('endPeriod') else end
                    if discharged < admitted: raise ValueError()
                except ValueError:
                    pending.append({'episode':enc,'reason':'Fechas de hospitalización no verificables; ficha completa pendiente.'})
                    continue
                if admitted > end or discharged < start: continue
            else:
                try: discharged = date.fromisoformat(str(row.get('endPeriod', ''))[:10])
                except ValueError:
                    pending.append({'episode': enc, 'reason': 'Fecha de egreso no disponible; período no verificable.'})
                    continue
                if not start <= discharged <= end: continue
            # La UI ofrece imprimir aunque generatedReport sea false: consultar PDF y comprobar respuesta.
            if enc not in seen:
                selected.append(row); seen.add(enc)
        selected.sort(key=lambda row: str(row.get('endPeriod') or end.isoformat()), reverse=True)
        return selected, pending

    def pdf(self, row):
        cache = getattr(self, 'pdf_cache', None)
        old, conditional, content = None, {}, None
        key = hashlib.sha256(json.dumps([self.facility, row['patientIdentifier'], row['encounterId']]).encode()).hexdigest()
        if cache:
            cache = Path(cache)
            try:
                old = json.loads((cache / (key + '.json')).read_text())
                content = (cache / (key + '.pdf')).read_bytes()
                if hashlib.sha256(content).hexdigest() != old['sha256']: raise ValueError()
                validate_pdf(content, row)
                for name, header in [('etag','If-None-Match'),('modified','If-Modified-Since')]:
                    value = old.get(name)
                    if isinstance(value, str) and 0 < len(value) < 1024 and not any(c in value for c in '\r\n'):
                        conditional[header] = value
            except (OSError, ValueError, KeyError, ReportError):
                old, content, conditional = None, None, {}
        received = self.get(PDF_PATH, {'enc_id': row['encounterId']}, pdf=True, conditional=conditional)
        if received is None:
            if content is None or not conditional: raise ReportError('304 sin copia verificable.')
            self.last_pdf_revalidated = True
            return content
        validate_pdf(received, row)
        self.last_pdf_revalidated = False
        if cache:
            cache.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Solo se guardan documentos ya verificados; no URLs, tokens ni cookies.
            fd, temporary = tempfile.mkstemp(prefix='.pdf-', dir=cache)
            try:
                with os.fdopen(fd, 'wb') as stream: stream.write(received)
                os.replace(temporary, cache / (key + '.pdf'))
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            headers = {k.lower():v for k,v in self.response_headers.items()}
            atomic_json(cache / (key + '.json'), {'sha256':hashlib.sha256(received).hexdigest(),
                        'etag':headers.get('etag'), 'modified':headers.get('last-modified')})
        return received

def validate_pdf(content, row):
    if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
        raise ReportError('Respuesta no es un PDF completo.')
    try:
        from pypdf import PdfReader
        doc = PdfReader(io.BytesIO(content), strict=True)
        if doc.is_encrypted or not doc.pages: raise ValueError()
        text = '\n'.join(page.extract_text() or '' for page in doc.pages)
    except ImportError:
        raise ReportError('Falta pypdf en el Python elegido.') from None
    except Exception:
        raise ReportError('No se pudo validar la estructura del PDF.') from None
    # La identidad pertenece al bloque del paciente, nunca a una mención libre
    # en anamnesis, firma, profesional o familiar. La extracción puede colocar
    # valores antes de sus rótulos, por eso se delimita el bloque completo.
    expected = rut_normalized(row['patientIdentifier'])
    header_identities = []
    for page in doc.pages:
        page_text = page.extract_text() or ''
        folded = ''.join(ch for ch in unicodedata.normalize('NFD', page_text)
                         if unicodedata.category(ch) != 'Mn')
        start = re.search(r'(?:DATOS|IDENTIFICACION)\s+DEL\s+PACIENTE\b', folded, re.I)
        if start:
            block = folded[start.end():]
            stop = re.search(r'\b(?:DATOS\s+(?:DE\s+LA|DEL?)\s+(?:HOSPITALIZACION|INGRESO)|'
                             r'DIAGNOSTICOS?|ANAMNESIS|EVOLUCION|PROFESIONAL|MEDICO|FAMILIAR|ACOMPANANTE)\b', block, re.I)
            block = block[:stop.start()] if stop else block[:1600]
            # Un bloque sin rótulo RUN/RUT no acredita cuál número identifica al paciente.
            if not re.search(r'\b(?:RUN|RUT)\s*:', block, re.I):
                raise ReportError('Encabezado del paciente sin RUN rotulado; requiere revisión visible.')
            candidates = [block]
        else:
            # Formatos simples: nombre/rol y RUN deben estar en la misma línea,
            # o el rótulo debe decir expresamente «RUN del paciente».
            candidates = re.findall(r'^\s*(?:Paciente\b[^\n]*\b(?:RUN|RUT)|(?:RUN|RUT)\s+(?:del\s+)?paciente)'
                                    r'\s*:[^\n]*(?:\n[ \t]*[\d.]+[ \t]*-[ \t]*[\dKk])?', folded, re.I | re.M)
        for block in candidates:
            found = []
            for value in re.findall(r'(?<!\d)(?:\d{1,2}\.\d{3}\.\d{3}|\d{7,8})[ \t]*-?[ \t]*[0-9Kk](?!\d)', block):
                try: found.append(rut_normalized(re.sub(r'\s+', '', value)))
                except ReportError: pass
            if not found or set(found) != {expected}:
                raise ReportError('El RUN del encabezado del paciente no coincide o es ambiguo.')
            header_identities.extend(found)
    if not header_identities:
        raise ReportError('No se pudo vincular el RUN al encabezado del paciente; requiere revisión visible.')
    # Solo comparar identificadores explícitos de episodio/hospitalización/encuentro.
    episodes = re.findall(r'(?:\bID\s+(?:de\s+)?|\bN[°º]\s*|\bNumero\s+(?:de\s+)?)?'
                          r'\b(?:Episodio|Hospitalizaci[oó]n|Encuentro)\s*[:#]\s*(\d+)\b', text, re.I)
    if episodes and (not valid_id(row.get('encounterId')) or set(episodes) != {str(row['encounterId'])}):
        raise ReportError('El identificador de episodio del PDF no coincide con el solicitado.')
    discharge = date.fromisoformat(str(row['endPeriod'])[:10])
    egreso = re.search(r'Fecha\s+Egreso\s*:\s*(\d{4}-\d{2}-\d{2}|\d{2}[/-]\d{2}[/-]\d{4})', text, re.I)
    if not egreso or egreso.group(1) not in (discharge.isoformat(), discharge.strftime('%d/%m/%Y'), discharge.strftime('%d-%m-%Y')):
        raise ReportError('No se pudo verificar la fecha de egreso en el PDF; requiere revisión visible.')

def save_version(folder, row, content):
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    stem = 'Epicrisis Rayen - {} - episodio {}'.format(date.fromisoformat(str(row['endPeriod'])[:10]).strftime('%d-%m-%Y'), row['encounterId'])
    candidate = folder / (stem + '.pdf')
    suffix = 1
    fd, temp = tempfile.mkstemp(prefix='.epicrisis-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
        while True:
            try:
                os.link(temp, candidate)
                break
            except FileExistsError:
                if hashlib.sha256(candidate.read_bytes()).hexdigest() == digest: break
                suffix += 1; candidate = folder / (stem + ' - v{}.pdf'.format(suffix))
    finally:
        os.unlink(temp)
    return {'path': str(candidate), 'sha256': digest, 'bytes': len(content), 'episode': row['encounterId']}

def run(client, rut, start, end, output, download=False):
    rut = rut_normalized(rut)
    if end < start: raise ReportError('Período inválido.')
    output = Path(output)
    if not output.is_absolute(): raise ReportError('La salida debe ser una ruta absoluta.')
    rows, pending = client.episodes(rut, start, end)
    state = {'source':'rayen-epicrisis', 'rut':rut, 'from':str(start), 'to':str(end), 'date_basis':'egreso',
             'mode':'download' if download else 'list', 'status':'running', 'episodes':rows, 'files':[], 'pending':pending}
    stamp = datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y_%H-%M-%S-%f')
    folder = output / rut
    state_path = folder / ('estado-rayen-' + stamp + '.json')
    atomic_json(state_path, state)
    expired = False
    unavailable = False
    if download:
        for row in rows:
            if expired or unavailable:
                state['pending'].append({'episode':row['encounterId'], 'reason':'No intentado: sesión o conectividad pendiente.'})
            else:
                try: state['files'].append(save_version(folder, row, client.pdf(row)))
                except SessionExpired as e:
                    expired = True
                    state['pending'].append({'episode':row['encounterId'], 'reason':str(e)})
                except SourceUnavailable as e:
                    unavailable = True
                    state['pending'].append({'episode':row['encounterId'], 'reason':str(e)})
                except ReportError as e:
                    state['pending'].append({'episode':row['encounterId'], 'reason':str(e)})
                except OSError:
                    state['pending'].append({'episode':row['encounterId'], 'reason':'No se pudo guardar el documento; conservar los anteriores.'})
            atomic_json(state_path, state)
    state['status'] = 'partial' if state['pending'] else 'complete' if rows else 'no_records'
    state['auth_required'] = expired
    atomic_json(state_path, state)
    return state_path, state

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rut', required=True)
    parser.add_argument('--from', dest='start', type=date.fromisoformat, required=True)
    parser.add_argument('--to', dest='end', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--download', action='store_true', help='Descargar; por defecto solo listar')
    args = parser.parse_args()
    try:
        payload = sys.stdin.read(65537)
        if len(payload)>65536: raise ReportError('Sesión demasiado grande.')
        session = json.loads(payload)
        if not isinstance(session, dict): raise ValueError()
        state_path, state = run(Client(session), args.rut, args.start, args.end, args.output, args.download)
        print(json.dumps({'state':str(state_path),'status':state['status'],'downloaded':len(state['files']),'pending':len(state['pending'])}, ensure_ascii=False))
        return 2 if state['auth_required'] else 1 if state['status']=='partial' else 0
    except SessionExpired as e:
        print(str(e), file=sys.stderr); return 2
    except (SourceUnavailable, ReportError, ValueError, OSError):
        print('Consulta no completada: revisar sesión, parámetros, conectividad o formato; no interpretar como ausencia de registros.', file=sys.stderr); return 1

if __name__ == '__main__': sys.exit(main())
