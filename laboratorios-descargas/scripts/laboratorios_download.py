#!/usr/bin/env python3
"""Descarga exámenes, atenciones e informes de siete fuentes por RUT y período."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
from datetime import date, datetime, timedelta
from getpass import getpass
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
import uuid
import time
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
from mmrad_selection import normalize_image_types
from clinical_content import normalize_source_content

LABELS = {'syslab': 'Syslab HHR', 'exalab': 'Exalab SSMO', 'eloisa': 'Eloísa Ambulatorio', 'mmrad': 'MMRAD RIS', 'mmrad_images': 'MMRAD imágenes', 'his': 'HIS Hanga Roa', 'rayen': 'Eloísa Hospitalizados', 'email': 'Correo institucional'}
FILE_LABELS = {'syslab': 'Laboratorio HHR', 'exalab': 'Laboratorio HDS', 'eloisa': 'Atenciones HHR', 'mmrad': 'Imagenología HHR', 'mmrad_images': 'Imágenes HHR', 'his': 'Atenciones HIS HHR', 'rayen': 'Epicrisis Rayen'}
READING_LABELS = {'syslab': 'LAB HHR', 'exalab': 'LAB HDS', 'eloisa': 'Eloisa ambulatorio',
                  'mmrad': 'MMRAD', 'rayen': 'Eloisa Hospitalizados'}
SPANISH_MONTHS = ('Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Sept','Octubre','Noviembre','Diciembre')
# Reexportados para conservar CLI, clientes y pruebas anteriores.
from clinical_domain import (
    LabsError, PERIODS, SOURCE_ORDER, selected_sources, normalize_ruts,
    normalize_source_periods, build_request,
)


def load_backend(name):
    folder = Path(__file__).resolve().parent
    path = folder / (name + '_download.py')
    if not path.is_file():
        path = folder.parent.parent / (name + '-resultados') / 'scripts' / (name + '_download.py')
    if not path.is_file():
        raise LabsError('Falta el módulo {}_download.py; usa el paquete completo.'.format(name))
    spec = importlib.util.spec_from_file_location('labs_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pdf_library():
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        raise LabsError('Falta pypdf. Usa el Python del runtime de Codex o instala pypdf en el entorno elegido.') from None
    return PdfReader, PdfWriter



def validate_pdf(content, rut, folio, source='syslab', exam_date=None, validation=None):
    if source=='eloisa' and validation is not None:
        try:return load_backend('eloisa').validate_attachment(content,rut,validation)
        except Exception as error:raise LabsError(str(error)) from None
    PdfReader, _ = pdf_library()
    if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
        raise LabsError('El archivo recibido no es un PDF completo.')
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted or not reader.pages:
            raise LabsError('El PDF está cifrado o no contiene páginas.')
        texts = [page.extract_text() or '' for page in reader.pages]
    except LabsError:
        raise
    except Exception:
        raise LabsError('No se pudo leer el PDF para verificar el paciente.') from None
    if source == 'rayen':
        load_backend('rayen').module.validate_pdf(content, {'patientIdentifier':rut, 'endPeriod':exam_date.date().isoformat(), 'encounterId':int(folio)})
        return reader
    if source == 'mmrad_images':
        first = texts[0]
        if 'RUT ' + rut not in first or not any(exam_date.strftime(fmt) in first for fmt in ('%d-%m-%Y', '%d/%m/%Y')):
            raise LabsError('El PDF de imágenes no identifica al paciente y fecha del estudio.')
        return reader
    if source == 'mmrad':
        # Algunos informes no imprimen RUT en texto; cuando lo hacen, se verifica.
        pattern = r'\b(?:RUT|RUN)\s*:?\s*([\d.]{7,10})\s*-\s*([0-9Kk])\b'
        for body, digit in re.findall(pattern, '\n'.join(texts), re.I):
            if body.replace('.', '') + '-' + digit.upper() != rut:
                raise LabsError('El PDF MMRAD contiene un RUT distinto del solicitado.')
        return reader
    # Algunos laboratorios de Exalab imprimen un número de orden interno distinto
    # del folio de la lista. En ese formato se exige RUT y fecha/hora de ingreso,
    # además del enlace PDF obtenido por el folio autenticado en el cliente.
    if source == 'exalab' and not re.search(r'Rut\s*/\s*Fic\s*:', texts[0], re.I):
        if exam_date is None:
            raise LabsError('Falta la fecha del folio para verificar el PDF de Exalab.')
        rut_pattern = r'(?<!\d)(\d{7,8}|\d{1,2}\.\d{3}\.\d{3})\s*-\s*([0-9Kk])(?!\d)'
        seen = re.findall(rut_pattern, texts[0], re.I)
        if not seen:
            raise LabsError('No se pudo verificar el RUT en la primera página de Exalab.')
        for page in texts:
            for body, digit in re.findall(rut_pattern, page, re.I):
                if body.replace('.', '') + '-' + digit.upper() != rut:
                    raise LabsError('El PDF de Exalab contiene un RUT distinto del solicitado.')
        first = ' '.join(texts[0].split())
        if not re.search(r'N[°ºo]\s*ORDEN\s*:', first, re.I):
            raise LabsError('No se reconoce la identificación de orden del PDF de Exalab.')
        if exam_date.strftime('%d/%m/%Y %H:%M') not in first:
            raise LabsError('La fecha y hora del PDF de Exalab no coinciden con el folio.')
        return reader
    pattern = (r'RUN\s*:\s*([\d.]+)\s*-\s*([\dKk])' if source in ('eloisa', 'his')
               else r'Rut\s*/\s*Fic\s*:\s*([\d.]+)\s*-\s*([\dKk])')
    first = re.search(pattern, texts[0], re.I)
    if not first:
        raise LabsError('No se pudo verificar el RUT en la primera página del PDF.')
    for text in texts:
        for body, digit in re.findall(pattern, text, re.I):
            if body.replace('.', '') + '-' + digit.upper() != rut:
                raise LabsError('El PDF contiene un RUT distinto del paciente solicitado.')
    numbers = re.findall(r'ID de atenci[oó]n\s*:\s*(\d+)' if source in ('eloisa', 'his') else r'N[úu]mero\s*:\s*(\d+)', texts[0], re.I)
    if str(folio) not in numbers:
        raise LabsError('El número de folio del PDF no coincide con el resultado solicitado.')
    return reader


def save_content(folder, stem, content, extension='.pdf'):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + stem + '-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        path = folder / (stem + extension)
        version = 1
        while True:
            try:
                # Publica el archivo completo sin sobrescribir otra versión.
                os.link(temporary, path)
                return path.resolve()
            except FileExistsError:
                if path.read_bytes() == content:
                    return path.resolve()
                version += 1
                path = folder / (stem + '_' + str(version) + extension)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_write(path, content):
    """Un archivo visible siempre es completo, incluso si el proceso se interrumpe."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_progress(path):
    try:
        state = json.loads(Path(path).read_text())
        if type(state['version']) is not int or state['version'] != 1 or not isinstance(state['request'], dict) or not isinstance(state['reports'], dict) or not isinstance(state['results'], list):
            raise ValueError()
        return state
    except (OSError, ValueError, KeyError, TypeError):
        raise LabsError('No se pudo leer el avance. Conserva la carpeta y usa --fresh para iniciar otra ejecución.') from None


class Progress:
    def __init__(self, output, request, resume=None, fresh=False):
        if resume and fresh:
            raise LabsError('--resume y --fresh no pueden usarse juntos.')
        identity = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:20]
        if fresh:
            identity += '-' + uuid.uuid4().hex[:8]
        self.path = Path(resume).resolve() if resume else output.resolve() / '.avance' / identity / 'avance.json'
        self.state = {'version': 1, 'request': request, 'reports': {}, 'results': []}
        self.explicit_resume = bool(resume)
        self.previous = {}

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, 'wb') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise LabsError('Esta solicitud ya se está procesando. Espera a que termine antes de reanudarla.') from None
            if self.path.exists():
                saved = read_progress(self.path)
                if saved['request'] != self.state['request']:
                    raise LabsError('El avance pertenece a otra solicitud (RUT, sitio, período, fecha, salida u opción de unión).')
                self.state = saved
            elif self.explicit_resume:
                raise LabsError('No existe el archivo de avance indicado.')
            try:
                yield self
            except BaseException as error:
                # Incluso SIGINT conserva un cierre con el último avance publicado.
                try:
                    from clinical_receipt import write
                    snapshot=dict(self.state['request'],results=self.state['results'],order_status='cancelled' if isinstance(error,KeyboardInterrupt) else 'interrupted')
                    for receipt in write(snapshot,Path(self.state['request']['output'])):
                        print(receipt['text']+'TXT: '+receipt['path'],flush=True)
                except (OSError,ValueError):pass  # No ocultar la causa original de interrupción.
                raise
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def save(self):
        atomic_write(self.path, json.dumps(self.state, ensure_ascii=False, indent=2).encode())

    def verified_previous(self, result):
        """Conservar solo bytes que aún coinciden con evidencia verificada previa."""
        entries = []
        rut, source = result['rut'], result['source']
        output = Path(self.state['request']['output']).resolve()
        for item in result.get('file_manifest', []):
            try:
                path = Path(item['path']).resolve()
                if not path.is_relative_to(output / rut): continue
                if source == 'rayen' and item.get('validation_version') != 2: continue
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != item['sha256']: continue
                if source == 'email':
                    from clinical_email import ALLOWED_EXTENSIONS
                    if path.suffix.lower() not in ALLOWED_EXTENSIONS or item.get('identity_review') != 'Codex': continue
                if source != 'email' or path.suffix.lower() == '.pdf':
                    reader = pdf_library()[0](BytesIO(content))
                    if reader.is_encrypted or not reader.pages: continue
                entries.append(dict(item, path=str(path)))
            except Exception: continue  # Un PDF ilegible no debe bloquear otras fuentes.
        # Los avances antiguos no tenían manifiesto de publicados. Recuperar
        # originales por hash + identidad; no confiar solo en el nombre/ruta.
        for key, record in self.records(rut, source).items():
            try:
                if 'sha256' not in record: continue
                path = (self.path.parent / 'originales' / rut / source / (key + '.pdf')).resolve()
                if not path.is_relative_to(output): continue
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != record['sha256']: continue
                reader = validate_pdf(content, rut, key.split('-')[0], source, datetime.fromisoformat(record['date']),record.get('validation'))
                if not entries or record['sha256'] not in {x['sha256'] for x in entries}:
                    entries.append({'path':str(path), 'sha256':record['sha256'], 'pages':len(reader.pages), 'validation_version':2})
            except Exception: continue
        return entries

    def update(self, result):
        result = dict(result)
        key = (result['rut'], result['source'])
        old = self.previous.get(key)
        if old and result['status'] not in ('complete', 'empty', 'listed', 'no_reports', 'no_images'):
            retained = old.get('retained_verified', [])
            if retained:
                result['retained_files'] = retained
                result['files'] = list(dict.fromkeys(result.get('files', []) + [x['path'] for x in retained]))
                result['freshness'] = 'update_pending'
                result['notice'] = 'Documento obtenido previamente; actualización pendiente.'
                if not result.get('patient_name') or result['patient_name'] == 'Nombre no disponible':
                    result['patient_name'] = old.get('patient_name', 'Nombre no disponible')
                if result['status'] == 'error': result['status'] = 'partial'
            # Los originales DICOM tienen evidencia separada de los PDF.
            retained_originals = []
            for item in old.get('original_manifest', []):
                try:
                    path = Path(item['path']).resolve()
                    if path.is_relative_to(Path(self.state['request']['output']).resolve()) and hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']:
                        retained_originals.append(item)
                except (OSError, KeyError, TypeError): pass
            if retained_originals:
                if not result.get('patient_name') or result['patient_name'] == 'Nombre no disponible':
                    result['patient_name'] = old.get('patient_name', 'Nombre no disponible')
                current = {x['path']:x for x in retained_originals + result.get('original_manifest', [])}
                result['original_manifest'] = list(current.values())
                result['originals'] = list(current)
                result['notice'] = 'Documento obtenido previamente; actualización pendiente.'
                result['freshness'] = 'update_pending'
                if result['status'] == 'error': result['status'] = 'partial'
        manifests = []
        previous_row = next((r for r in self.state['results'] if (r['rut'],r['source'])==key), {})
        expected = {item['path']:item['sha256'] for item in result.get('file_manifest',[]) + result.get('retained_files',[]) + previous_row.get('file_manifest',[])}
        for filename in result.get('files', []):
            if result['source']=='email':continue
            try:
                path = Path(filename).resolve()
                if not path.is_relative_to(Path(self.state['request']['output']).resolve()): continue
                if Path(filename).is_symlink(): continue
                content = path.read_bytes()
                if filename in expected and hashlib.sha256(content).hexdigest() != expected[filename]: continue
                reader = pdf_library()[0](BytesIO(content))
                if reader.is_encrypted or not reader.pages: continue
                manifests.append({'path':str(path), 'sha256':hashlib.sha256(content).hexdigest(), 'pages':len(reader.pages), 'validation_version':2})
            except Exception: continue
        if result['source'] == 'email':
            candidates = result.get('file_manifest',[]) + result.get('retained_files',[])
            manifests = []
            for item in candidates:
                try:
                    path=Path(item['path'])
                    if path.is_symlink() or not path.resolve().is_relative_to(Path(self.state['request']['output']).resolve()/result['rut']):continue
                    if item.get('identity_review')=='Codex' and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']:
                        manifests.append(item)
                except (OSError,KeyError,TypeError):continue
            manifests=list({item['path']:item for item in manifests}.values())
            if manifests and result['status']=='pending':result['status']='partial'
        allowed = {item['path'] for item in manifests}
        if any(filename not in allowed for filename in result.get('files', [])):
            from clinical_integrity import INTEGRITY_ERROR
            result['errors']=list(dict.fromkeys([*result.get('errors',[]),INTEGRITY_ERROR]))
            result.update(status='partial',freshness='update_pending')
        result['files']=[item['path'] for item in manifests]
        result['file_manifest'] = manifests
        result['pages'] = sum(item.get('pages',0) for item in manifests)
        for i, previous in enumerate(self.state['results']):
            if (previous['rut'], previous['source']) == key:
                self.state['results'][i] = result
                break
        else:
            self.state['results'].append(result)
        self.save()
        return result

    def report_key(self, exam):
        folio = str(exam['id'])
        if not re.fullmatch(r'[0-9]+', folio):
            raise LabsError('El folio no tiene un identificador válido.')
        # Exalab agrupa laboratorios internos que podrían repetir un número de folio.
        origin = exam.get('source')
        return folio + '-' + hashlib.sha256(origin.encode()).hexdigest()[:16] if origin else folio

    def report_path(self, rut, source, exam):
        return self.path.parent / 'originales' / rut / source / (self.report_key(exam) + '.pdf')

    def records(self, rut, source):
        return self.state['reports'].setdefault(rut, {}).setdefault(source, {})

    def unavailable(self, rut, source, exam):
        record = self.records(rut, source).get(self.report_key(exam))
        if (record and record.get('status') == 'unavailable' and record.get('date') == exam['datetime'].isoformat()
                and (source not in ('mmrad', 'rayen') or record.get('fingerprint') == exam.get('fingerprint'))):
            return record.get('reason') or 'Este registro aún no tiene un informe PDF disponible.'
        return None

    def mark_unavailable(self, rut, source, exam, reason):
        self.records(rut, source)[self.report_key(exam)] = {
            'date': exam['datetime'].isoformat(), 'status': 'unavailable', 'reason': reason,
            'fingerprint': exam.get('fingerprint')}
        self.save()

    def get(self, rut, source, exam):
        if source == 'rayen': return None
        path = self.report_path(rut, source, exam)
        record = self.records(rut, source).get(self.report_key(exam))
        if not record or record.get('date') != exam['datetime'].isoformat():
            return None
        try:
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != record['sha256']:
                return None
            if source in ('eloisa', 'mmrad', 'mmrad_images', 'his') and record.get('fingerprint') != exam.get('fingerprint'):
                return None
            if source == 'mmrad_images':
                for original in record.get('originals') or []:
                    file = Path(original['path'])
                    if hashlib.sha256(file.read_bytes()).hexdigest() != original['sha256']:
                        return None
                if not record.get('originals'):
                    return None
            reader = validate_pdf(content, rut, exam['id'], source, exam['datetime'],exam.get('validation'))
            if source == 'his' and record.get('name'):
                exam['name'] = record['name']
            return path, len(reader.pages)
        except (OSError, LabsError, KeyError):
            return None

    def put(self, rut, source, exam, content, pages, originals=None):
        path = self.report_path(rut, source, exam)
        if path.exists() and path.read_bytes() != content:
            save_content(path.parent / 'versiones', path.stem, path.read_bytes())
        atomic_write(path, content)
        self.records(rut, source)[self.report_key(exam)] = {
            'date': exam['datetime'].isoformat(), 'sha256': hashlib.sha256(content).hexdigest(),
            'pages': pages, 'fingerprint': exam.get('fingerprint'),
            **({'validation':exam['validation']} if exam.get('validation') else {}),
            **({'name': exam.get('name')} if source == 'his' else {}),
            **({'originals': originals} if originals is not None else {})}
        self.save()
        return path


def report_bytes(report):
    return report.read_bytes() if isinstance(report, Path) else report


def safe_patient_name(exams):
    """Convierte el nombre mostrado por el portal en una parte segura del archivo."""
    for exam in exams:
        raw = str(exam.get('name') or '').strip()
        if raw:
            ascii_name = unicodedata.normalize('NFKD', raw).encode('ascii', 'ignore').decode('ascii')
            words = re.findall(r'[A-Za-z0-9]+', ascii_name)
            if words:
                return ' '.join(words).title()[:80].rstrip()
    return 'Nombre no disponible'


def public_pdf_stem(source, rut, downloaded_on, patient_name, exam=None):
    parts = [FILE_LABELS[source], downloaded_on.strftime('%d-%m-%Y'), rut, patient_name]
    if exam is not None:
        parts.extend([exam['datetime'].strftime('%d-%m-%Y'),
                      ('Atencion ' if source in ('eloisa','his') else 'Estudio ' if source in ('mmrad','mmrad_images') else 'Folio ') + str(exam['id'])])
    if exam and exam.get('validation',{}).get('kind')=='attachment':
        name=Path(exam['validation']['filename']).stem
        title=' '.join(re.findall(r'[A-Za-z0-9]+',unicodedata.normalize('NFKD',name).encode('ascii','ignore').decode()))[:80]
        parts.extend(['Adjunto',title,exam['validation']['path_digest'][:8]])
    return ' - '.join(parts)


def merge_reports(reports, rut, source):
    _, PdfWriter = pdf_library()
    writer = PdfWriter()
    expected = 0
    for exam, report in sorted(reports, key=lambda pair: (pair[0]['datetime'], str(pair[0]['id'])), reverse=True):
        reader = validate_pdf(report_bytes(report), rut, exam['id'], source, exam['datetime'],exam.get('validation'))
        first_page = len(writer.pages)
        for page in reader.pages:
            writer.add_page(page)
        kind = 'Atención' if source in ('eloisa','his') else 'Episodio' if source == 'rayen' else 'Estudio' if source == 'mmrad' else 'Folio'
        writer.add_outline_item(exam['datetime'].strftime('%d-%m-%Y') + ' - ' + kind + ' ' + exam['id'], first_page)
        expected += len(reader.pages)
    if not expected:
        raise LabsError('No hay páginas para consolidar.')
    writer.add_metadata({'/Title': LABELS[source] + ' - ' + rut})
    stream = BytesIO()
    writer.write(stream)
    content = stream.getvalue()
    PdfReader, _ = pdf_library()
    if len(PdfReader(BytesIO(content)).pages) != expected:
        raise LabsError('El número de páginas del consolidado no coincide con los originales.')
    return content, expected


def reading_pdf_stem(source, dates, partial=False):
    """Name a reading copy by the clinical dates actually included, not the search window."""
    start, end = min(dates), max(dates)
    first = SPANISH_MONTHS[start.month - 1]
    last = SPANISH_MONTHS[end.month - 1]
    if (start.year, start.month) == (end.year, end.month):
        span = f'{first} {end.year}'
    elif start.year == end.year:
        span = f'{first}-{last} {end.year}'
    else:
        span = f'{first} {start.year}-{last} {end.year}'
    return READING_LABELS[source] + ' ' + span + (' - PARCIAL' if partial else '')


def publish_reading_pdfs(progress, output):
    """Derive source reading copies only from original PDFs with matching identity/hash."""
    for row in list(progress.state['results']):
        source, rut = row.get('source'), row.get('rut')
        if source not in READING_LABELS or not rut:
            continue
        ct_ids = {str(folio['id']) for folio in row.get('folios', [])
                  if str(folio.get('modality', '')).upper() == 'CT'} if source == 'mmrad' else None
        reports = []
        for key, record in progress.records(rut, source).items():
            if not record.get('sha256') or record.get('validation', {}).get('kind') == 'attachment':
                continue
            folio = key.split('-')[0]
            if ct_ids is not None and folio not in ct_ids:
                continue
            original = progress.path.parent / 'originales' / rut / source / (key + '.pdf')
            try:
                content = original.read_bytes()
                if hashlib.sha256(content).hexdigest() != record['sha256']:
                    continue
                when = datetime.fromisoformat(record['date'])
                validate_pdf(content, rut, folio, source, when, record.get('validation'))
                reports.append(({'id':folio,'datetime':when},content))
            except (OSError, KeyError, TypeError, ValueError, LabsError):
                continue
        if not reports:
            continue
        expected = sum(1 for folio in row.get('folios', [])
                       if source != 'mmrad' or str(folio.get('modality', '')).upper() == 'CT')
        partial = (row.get('status') not in ('complete','empty','no_reports') or bool(row.get('errors'))
                   or (expected > 0 and len(reports) < expected))
        try:
            content, pages = merge_reports(reports, rut, source)
            stem = reading_pdf_stem(source, [exam['datetime'] for exam,_ in reports], partial)
            path = save_content(Path(output) / rut / source, stem, content)
            row = dict(row, reading_pdf=str(path), reading_count=len(reports),
                       files=list(dict.fromkeys([str(path), *row.get('files',[])])))
            progress.update(row)
        except (LabsError, OSError, ValueError) as error:
            row = dict(row, reading_error=str(error),
                       notice='No se pudo generar la copia combinada; conserva los originales verificados.')
            progress.update(row)


def merge_patient_documents(results, rut, output, downloaded_on):
    """Join only complete, already verified source PDFs for one patient."""
    PdfReader, PdfWriter = pdf_library()
    selected = [result for result in results if result['rut'] == rut]
    if not selected:
        raise LabsError('No hay fuentes seleccionadas para este paciente.')
    for result in selected:
        if result['status'] not in ('complete', 'empty', 'no_reports', 'no_images') or result.get('errors'):
            raise LabsError('No se creó el PDF único: {} quedó {}.'.format(
                LABELS[result['source']], result['status']))
        if result['status'] == 'complete' and result.get('folios') and not result['files']:
            raise LabsError('No se creó el PDF único: faltan archivos de {}.'.format(LABELS[result['source']]))
        if result['status'] == 'no_images' and result.get('folios'):
            raise LabsError('No se creó el PDF único: un estudio MMRAD no entregó imágenes.')
    writer = PdfWriter()
    total = 0
    patient_root = (Path(output) / rut).resolve()
    patient_name = next((result.get('patient_name') for result in selected
                         if result.get('patient_name') and result['patient_name'] != 'Nombre no disponible'),
                        'Nombre no disponible')
    for result in selected:
        for filename in result['files']:
            if result['source'] == 'email': continue  # Mensajes y adjuntos se entregan aparte, sin alterar originales.
            if filename == result.get('reading_pdf'): continue  # Evitar páginas duplicadas; originales siguen incluidos.
            path = Path(filename).resolve()
            if not path.is_relative_to(patient_root) or path.suffix.lower() != '.pdf':
                raise LabsError('Un PDF no pertenece a la carpeta del paciente.')
            content = path.read_bytes()
            if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
                raise LabsError('Un PDF del paciente está incompleto.')
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted or not reader.pages:
                raise LabsError('Un PDF del paciente no tiene páginas legibles.')
            if result['source'] != 'mmrad':
                first = (reader.pages[0].extract_text() or '').replace('.', '')
                if rut not in first:
                    raise LabsError('Un PDF no identifica el RUT del paciente.')
            writer.add_outline_item(LABELS[result['source']] + ' - ' + path.stem, total)
            for page in reader.pages:
                writer.add_page(page)
            total += len(reader.pages)
    if not total:
        return {'rut': rut, 'status': 'empty', 'files': [], 'pages': 0, 'errors': []}
    writer.add_metadata({'/Title': 'Expediente clinico - ' + rut})
    stream = BytesIO()
    writer.write(stream)
    content = stream.getvalue()
    if len(PdfReader(BytesIO(content)).pages) != total:
        raise LabsError('El PDF único no contiene todas las páginas verificadas.')
    stem = 'Expediente clinico - {} - {} - {}'.format(downloaded_on.strftime('%d-%m-%Y'), rut, patient_name)
    path = save_content(patient_root, stem, content)
    return {'rut': rut, 'status': 'complete', 'files': [str(path)], 'file_manifest':[{'path':str(path),'sha256':hashlib.sha256(content).hexdigest(),'pages':total}], 'pages': total, 'errors': []}


def collect_group(client, rut, source, period, today, output, merge=False, list_only=False, progress=None, retry_unavailable=False):
    syslab = load_backend('syslab')
    item_label = 'Atención' if source in ('eloisa','his') else 'Episodio' if source == 'rayen' else 'Estudio' if source == 'mmrad' else 'Folio'
    if source in ('eloisa', 'mmrad', 'rayen') and isinstance(client, Adapter):
        client.today = today
        client.period = period
    result = {'rut': rut, 'source': source, 'status': 'empty', 'folios': [], 'files': [], 'pages': 0, 'errors': []}
    incremental=getattr(client,'incremental',None);initial_metrics=dict(incremental.metrics) if incremental else None
    folder = output / rut / source
    result.update(status='searching', completed_folios=[], pending_folios=[], unavailable_folios=[])
    def publish():
        if incremental:result['retrieval']={key:value-initial_metrics[key] for key,value in incremental.metrics.items()}
        if progress:
            progress.update(result)
    publish()
    try:
        searched = client.search(rut)
        raw_client=client.client if isinstance(client,Adapter) else client
        if source=='mmrad' and 'ct_reports' in (getattr(raw_client,'content',None) or []):
            searched=[e for e in searched if str(e.get('modality') or '').upper()=='CT']
        if source == 'mmrad' and period == 'latest':
            eligible = [e for e in searched if e.get('pdf_url') or str(e.get('modality') or '').upper() == 'CT']
            found = syslab.select_exams(eligible or searched, period, today)
        elif source=='eloisa' and period=='latest':
            latest=syslab.select_exams(searched,period,today)
            found=[e for e in searched if latest and e['id']==latest[0]['id'] and e['datetime']==latest[0]['datetime']]
        else:
            found = syslab.select_exams(searched, period, today)
    except Exception as error:
        result.update(status='error', errors=[str(error)])
        result['auth_required'] = type(error).__name__ in ('SessionExpired', 'AuthenticationError')
        result['source_unavailable'] = type(error).__name__ in ('SourceUnavailable', 'SiteUnavailable')
        publish()
        return result
    if source in ('rayen','eloisa'):
        raw_client = client.client if isinstance(client, Adapter) else client
        result['date_basis'] = 'egreso' if source == 'rayen' else 'fecha de atención'
        if source == 'rayen' and 'record' in (getattr(raw_client,'content',None) or []):
            result['record_date_basis'] = 'hospitalización coincidente con el período; episodio completo hasta la referencia'
        result['auth_required'] = bool(getattr(raw_client,'auth_required',False))
        result['unavailable_records'] = list(getattr(raw_client, 'pending_records', []))
        result['errors'].extend('{} {}: {}'.format(item_label, e['episode'], e['reason']) for e in result['unavailable_records'])
    result['folios'] = [{'id': e['id'], 'date': e['datetime'].isoformat(),
                         **({'kind':'attachment','filename':e['validation']['filename'],'key':Progress.report_key(None,e)} if e.get('validation') else {}),
                         **({'report_type':e.get('report_type'), 'modality':e.get('modality')} if source == 'mmrad' else {})} for e in found]
    result['patient_name'] = safe_patient_name(found) if found else 'Nombre no disponible'
    if source == 'mmrad':
        skipped = [e for e in found if not e.get('pdf_url') and str(e.get('modality') or '').upper() != 'CT']
        result['no_report_expected'] = [{'id':e['id'], 'date':e['datetime'].isoformat(),
                                         'modality':e.get('modality')} for e in skipped]
        exams = [e for e in found if e not in skipped]
    else:
        exams = found
    result['pending_folios'] = [Progress.report_key(None,e) for e in exams]
    if source=='eloisa':result['attachment_count']=sum(e.get('validation',{}).get('kind')=='attachment' for e in exams)
    result['status'] = 'downloading' if exams else 'no_reports' if source == 'mmrad' and found else 'empty'
    publish()
    if not exams:
        if result['errors']:
            result['status'] = 'partial'
            publish()
        return result
    patient_name = safe_patient_name(exams)
    if list_only:
        result['status'] = 'partial' if result['errors'] else 'listed'
        result['pending_folios'] = []
        publish()
        return result
    reports = []
    exams=sorted(exams,key=lambda e:e.get('validation',{}).get('kind')=='attachment')
    for index, exam in enumerate(exams):
        unavailable = progress.unavailable(rut, source, exam) if progress and source in ('syslab', 'mmrad', 'rayen') and not retry_unavailable else None
        if unavailable:
            result['errors'].append('{} {}: {} (sin nuevo intento)'.format(item_label, exam['id'], unavailable))
            result['unavailable_folios'].append(str(exam['id']))
            publish()
            continue
        try:
            cached = progress.get(rut, source, exam) if progress else None
            if cached:
                report, pages = cached
            else:
                content = client.download(exam)
                pages = len(validate_pdf(content, rut, exam['id'], source, exam['datetime'],exam.get('validation')).pages)
                report = progress.put(rut, source, exam, content, pages) if progress else content
            reports.append((exam, report))
            result['pages'] += pages
            result['completed_folios'].append(Progress.report_key(None,exam))
            result['pending_folios'].remove(Progress.report_key(None,exam))
            publish()
            print('{} | {} | {} {} | {} ({}/{})'.format(rut, LABELS[source], item_label, exam['id'], 'reutilizado' if cached else 'guardado', len(result['completed_folios']), len(exams)), flush=True)
        except Exception as error:
            if (source == 'syslab' and type(error).__name__ == 'NoValidatedExams') or (source in ('mmrad', 'rayen') and type(error).__name__ == 'NoPdfReport'):
                if progress:
                    progress.mark_unavailable(rut, source, exam, str(error))
                result['unavailable_folios'].append(str(exam['id']))
            result['errors'].append('{} {}: {}'.format(item_label, exam['id'], error))
            publish()
            if type(error).__name__ in ('SourceUnavailable', 'SiteUnavailable'):
                result['source_unavailable'] = True
                break
            if type(error).__name__ in ('SessionExpired', 'AuthenticationError'):
                result['auth_required'] = True
                for pending in exams[index + 1:]:
                    result['errors'].append('{} {}: no intentado porque venció la sesión.'.format(item_label, pending['id']))
                break
    patient_name = safe_patient_name(exams)
    result['patient_name'] = patient_name
    downloaded_on = datetime.now(ZoneInfo('Pacific/Easter')).date()
    if result['errors']:
        # No se presenta un consolidado incompleto como si contuviera todos los folios.
        result['status'] = 'partial' if reports else 'error'
        destination = folder / 'incompletos'
        for exam, content in reports:
            stem = public_pdf_stem(source, rut, downloaded_on, patient_name, exam)
            result['files'].append(str(save_content(destination/'Documentos adjuntos' if exam.get('validation') else destination, stem, report_bytes(content))))
        publish()
        return result
    result['status'] = 'merging' if merge else 'saving'
    publish()
    if merge:
        attached=[(e,r) for e,r in reports if e.get('validation',{}).get('kind')=='attachment']
        for exam,report in attached:
            stem=public_pdf_stem(source,rut,downloaded_on,patient_name,exam)
            result['files'].append(str(save_content(folder/'Documentos adjuntos',stem,report_bytes(report))))
        reports=[(e,r) for e,r in reports if e.get('validation',{}).get('kind')!='attachment']
        if not reports:
            result['status']='complete';publish();return result
        try:
            content, count = merge_reports(reports, rut, source)
            stem = public_pdf_stem(source, rut, downloaded_on, patient_name)
            result['files'].append(str(save_content(folder, stem, content)))
        except Exception:
            result['status'] = 'partial'
            result['errors'].append('Falló la unión; se entregan los documentos individuales verificados.')
            for exam, content in reports:
                stem = public_pdf_stem(source, rut, downloaded_on, patient_name, exam)
                result['files'].append(str(save_content(folder / 'incompletos', stem, report_bytes(content))))
            publish()
            return result
    else:
        for exam, content in reports:
            stem = public_pdf_stem(source, rut, downloaded_on, patient_name, exam)
            result['files'].append(str(save_content(folder/'Documentos adjuntos' if exam.get('validation') else folder, stem, report_bytes(content))))
    result['status'] = 'complete'
    publish()
    return result


def collect_mmrad_images(client, rut, period, today, output, list_only=False, progress=None, image_types=None):
    """One image PDF per CR/DX/DR/US study; DICOM originals remain next to it."""
    mmrad = load_backend('mmrad')
    syslab = load_backend('syslab')
    raw = client.client if isinstance(client, Adapter) else client
    raw.image_types = mmrad.normalize_image_types(image_types)
    source = 'mmrad_images'
    result = {'rut':rut, 'source':source, 'status':'searching', 'folios':[], 'files':[],
              'originals':[], 'original_manifest':[], 'pages':0, 'errors':[], 'completed_folios':[],
              'pending_folios':[], 'no_images':[], 'excluded_images':[], 'image_types':list(raw.image_types)}
    def publish():
        if progress:
            progress.update(result)
    publish()
    try:
        searched = raw.search(rut, period, today, images_only=True)
        eligible = []
        for exam in searched:
            reason = mmrad.image_exclusion(exam, raw.image_types)
            if reason:
                result['excluded_images'].append({'id':str(exam['id']), 'reason':reason})
            else:
                eligible.append(exam)
        found = syslab.select_exams(eligible, period, today)
    except Exception as error:
        result.update(status='error', errors=[str(error)], auth_required=type(error).__name__ == 'AuthenticationError')
        publish()
        return result
    result['folios'] = [{'id':e['id'], 'date':e['datetime'].isoformat(), 'modality':e.get('modality')} for e in found]
    result['patient_name'] = safe_patient_name(found) if found else 'Nombre no disponible'
    result['pending_folios'] = [str(e['id']) for e in found]
    if not found:
        result['status'] = 'empty'
        publish()
        return result
    if list_only:
        result['status'] = 'listed'
        result['pending_folios'] = []
        publish()
        return result
    folder = output / rut / 'mmrad'
    for index, exam in enumerate(found):
        try:
            cached = progress.get(rut, source, exam) if progress else None
            if cached:
                content = cached[0].read_bytes()
                pages = cached[1]
                manifest = progress.records(rut, source)[progress.report_key(exam)]['originals']
                result['originals'].extend(item['path'] for item in manifest)
                result['original_manifest'].extend(manifest)
            else:
                viewer_url, instances = raw.image_instances(exam)
                originals, manifest = [], []
                study_dir = folder / 'originales_dicom' / str(exam['id'])
                index_path = study_dir / 'avance-instancias.json'
                try: saved = json.loads(index_path.read_text())
                except (OSError, ValueError): saved = {}
                if not isinstance(saved, dict): saved = {}
                originals = []
                workers = getattr(client, 'image_workers', 1)
                def obtain(item):
                    key = item['series_uid'] + '_' + item['sop_uid']
                    previous = saved.get(key)
                    if isinstance(previous, dict):
                        try:
                            path = Path(previous['path']).resolve()
                            if not path.is_relative_to(study_dir.resolve()): raise ValueError()
                            data = path.read_bytes()
                            if hashlib.sha256(data).hexdigest() != previous['sha256']: raise ValueError()
                            mmrad.validate_dicom(data, item['study_uid'], item['series_uid'], item['sop_uid'])
                            return item, data, path
                        except (OSError, KeyError, ValueError, mmrad.MMRADError): pass
                    fn = raw.download_dicom_isolated if workers > 1 else raw.download_dicom
                    data = fn(viewer_url, item)
                    return item, data, None
                # Ventanas pequeñas: no poner todo el estudio en una cola ni acumular solicitudes tras fallo.
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for offset in range(0, len(instances), workers):
                        futures = [pool.submit(obtain, item) for item in instances[offset:offset+workers]]
                        errors = []
                        for future in futures:
                            try:
                                item, dicom, path = future.result()
                                key = item['series_uid'] + '_' + item['sop_uid']
                                path = path or save_content(study_dir, key, dicom, extension='.dcm')
                                record = {'path':str(path), 'sha256':hashlib.sha256(dicom).hexdigest()}
                                saved[key] = record
                                atomic_write(index_path, json.dumps(saved).encode())
                                manifest.append(record)
                                result['originals'].append(str(path))
                                result['original_manifest'].append(record)
                                originals.append((item, dicom))
                                publish()
                            except Exception as error:
                                errors.append(error)
                        if errors: raise errors[0]
                content = mmrad.render_image_pdf(exam, originals)
                pages = len(validate_pdf(content, rut, exam['id'], source, exam['datetime'],exam.get('validation')).pages)
                if pages < len(instances):
                    raise LabsError('El PDF omitió una o más imágenes DICOM.')
                if progress:
                    progress.put(rut, source, exam, content, pages, originals=manifest)
            stem = public_pdf_stem(source, rut, datetime.now(ZoneInfo('Pacific/Easter')).date(),
                                   safe_patient_name([exam]), exam)
            safe_study = ' '.join(re.findall(r'[A-Za-z0-9]+', unicodedata.normalize('NFKD',
                              str(exam.get('exam_name') or 'Estudio de imagenologia')).encode('ascii', 'ignore').decode()))[:60]
            path = save_content(folder / 'imagenes_pdf', stem + ' - ' + safe_study, content)
            result['files'].append(str(path))
            result['pages'] += pages
            result['completed_folios'].append(str(exam['id']))
            result['pending_folios'].remove(str(exam['id']))
            print('{} | MMRAD imágenes | Estudio {} | {} ({}/{})'.format(
                rut, exam['id'], 'reutilizado' if cached else 'guardado', len(result['completed_folios']), len(found)), flush=True)
        except mmrad.ExcludedStudyImages as error:
            result['excluded_images'].append({'id':str(exam['id']), 'reason':str(error)})
            result['pending_folios'].remove(str(exam['id']))
        except mmrad.NoStudyImages as error:
            result['no_images'].append({'id':str(exam['id']), 'reason':str(error)})
            result['pending_folios'].remove(str(exam['id']))
        except Exception as error:
            result['errors'].append('Estudio {}: {}'.format(exam['id'], error))
            if type(error).__name__ in ('SourceUnavailable', 'SiteUnavailable'):
                result['source_unavailable'] = True
                break
            if type(error).__name__ == 'AuthenticationError':
                result['auth_required'] = True
                break
        publish()
    result['status'] = ('partial' if result['files'] else 'error') if result['errors'] else (
        'complete' if result['files'] else 'no_images')
    publish()
    return result


class Adapter:
    def __init__(self, source, client):
        self.source, self.client = source, client

    def search(self, rut):
        if self.source == 'eloisa':
            today = getattr(self, 'today', date.today())
            period = getattr(self, 'period', 'latest')
            since = None
            if getattr(self, 'bounded_dates', False) and period != 'latest':
                since = today - timedelta(days=30) if period == '30d' else load_backend('syslab').subtract_months(today, {'3m':3, '6m':6,'1y':12,'2y':24,'5y':60, '10y':120}[period])
            return self.client.search(rut, today=today, since=since)
        if self.source == 'rayen':
            return self.client.search(rut, self.period, self.today)
        if self.source == 'mmrad':
            return self.client.search(rut, getattr(self, 'period', None), getattr(self, 'today', None), reports_only=True)
        if self.source == 'syslab':
            # The portal searches by body only; PDF/cache identity remains the
            # validated full RUT of the request, including its check digit.
            return [dict(exam, rut=rut) for exam in self.client.search(rut.split('-')[0])]
        return self.client.search(rut)

    def download(self, exam):
        download=lambda:self.client.request(exam['url'],pdf=True) if self.source=='syslab' else self.client.download(exam)
        cache=getattr(self,'incremental',None)
        if cache is None:return download()
        validate=lambda content:validate_pdf(content,exam['rut'],exam['id'],self.source,exam['datetime'],exam.get('validation'))
        context=dict(version=1,source=self.source,rut=exam['rut'],id=exam['id'],date=exam['datetime'].isoformat(),origin=exam.get('source'),
                     content=getattr(self.client,'content',None),scope=getattr(self.client,'scope',None))
        if self.source=='eloisa' and not exam.get('validation') and isinstance(exam.get('raw'),dict):
            if not hasattr(self,'renderer_revision'):self.renderer_revision=hashlib.sha256(Path(load_backend('eloisa').__file__).read_bytes()).hexdigest()
            context.update(raw=exam['raw'],name=exam.get('name'),node=getattr(self.client,'node_id',None),
                           renderer=self.renderer_revision)
            return cache.structured(context,download,validate)
        if self.source in ('syslab','exalab','mmrad') and hasattr(self.client,'opener'):
            return cache.http(self.client,context,download,validate)
        return download()



def run_batch(ruts, source, period, today, output, clients, merge=False, list_only=False, setup_errors=None, resume=None, fresh=False, eloisa_scope='medicos', retry_unavailable=False, mmrad_mode='reports', patient_merge=False, retry_sources=None, image_workers=1, eloisa_bounded=True, setup_auth_sources=(), mmrad_image_types=None, source_periods=None, source_content=None, email_account='daniel.opazo@hospitalhangaroa.cl', cache_dir=None):
    if mmrad_mode not in ('reports', 'images', 'both'):
        raise LabsError('Modo MMRAD inválido.')
    if image_workers not in (1, 2): raise LabsError('Usa 1 o 2 descargas simultáneas de imágenes.')
    if retry_sources and not resume: raise LabsError('Reintento por fuente requiere --resume.')
    normalized = normalize_ruts(ruts)
    selected = selected_sources(source)
    source_periods = normalize_source_periods(source_periods, selected, period)
    source_content = normalize_source_content(source_content, selected)
    from clinical_content import validate_products
    validate_products(source_content,mmrad_mode)
    active = selected_sources(retry_sources) if retry_sources else selected
    if not set(active).issubset(selected): raise LabsError('Reintento fuera de las fuentes de la solicitud.')
    output = Path(output)
    request = build_request(normalized,source,period,today,output,merge=merge,list_only=list_only,
                            patient_merge=patient_merge,eloisa_scope=eloisa_scope,mmrad_mode=mmrad_mode,
                            mmrad_image_types=mmrad_image_types,source_periods=source_periods,
                            source_content=source_content,email_account=email_account)
    if 'mmrad_image_types' in request:mmrad_image_types=request['mmrad_image_types']
    progress = Progress(output, request, resume, fresh)
    setup_errors = dict(setup_errors or {})
    blocked_auth = set(setup_auth_sources)
    blocked_network = set()
    clients = dict(clients)
    for site, client in clients.items():
        if isinstance(client,Adapter):client.incremental=None
        if cache_dir and not fresh and isinstance(client,Adapter):
            from clinical_incremental import Cache
            client.incremental=Cache(Path(cache_dir)/site)
        if site in source_content:
            (client.client if isinstance(client, Adapter) else client).content = source_content[site]
        client.image_workers = image_workers
        client.bounded_dates = eloisa_bounded
        if site == 'rayen' and isinstance(client, Adapter):
            client.client.client.pdf_cache = Path(cache_dir)/'rayen' if cache_dir and not fresh else output / '.cache-http' / 'rayen'
    with progress.locked():
        from clinical_integrity import audit_results, result_keys
        previous_results = audit_results(progress.state['results'],output,result_keys(normalized,selected,mmrad_mode))
        progress.state['results']=previous_results
        for previous in previous_results:
            progress.previous[(previous['rut'], previous['source'])] = dict(previous, retained_verified=progress.verified_previous(previous))
        progress.state['results'] = [
            {'rut': rut, 'source': site, 'status': 'pending', 'folios': [], 'files': [], 'pages': 0, 'errors': []}
            for rut in normalized for site in selected if site != 'mmrad' or mmrad_mode != 'images'] + [
            {'rut':rut, 'source':'mmrad_images', 'status':'pending', 'folios':[], 'files':[], 'pages':0, 'errors':[]}
            for rut in normalized if 'mmrad' in selected and mmrad_mode in ('images','both')]
        if retry_sources:
            for i, result in enumerate(progress.state['results']):
                if result['source'].replace('mmrad_images', 'mmrad') not in active:
                    old = next((r for r in previous_results if (r['rut'],r['source']) == (result['rut'],result['source'])), None)
                    if old is not None:
                        retained = progress.previous[(old['rut'], old['source'])]['retained_verified']
                        from clinical_integrity import audit_result
                        old = audit_result(old, output)
                        if old['status'] not in ('complete','empty','listed','no_reports','no_images'):
                            old = dict(old, files=[x['path'] for x in retained], file_manifest=retained)
                        progress.state['results'][i] = old
        for initial in list(progress.state['results']): progress.update(initial)
        print('Avance: ' + str(progress.path), flush=True)
        patient_pdfs = list(progress.state.get('patient_pdfs', [])) if patient_merge else []
        for rut in normalized:
            for site in selected:
                if site not in active: continue
                started = time.monotonic()
                if site == 'mmrad' and mmrad_mode == 'images':
                    continue
                if site == 'email':
                    from clinical_email import load_result, pending
                    try:result = load_result(output,rut,source_periods.get(site,period),today.isoformat(),email_account)
                    except Exception:
                        result = pending(rut,source_periods.get(site,period),today.isoformat(),email_account,'Resultado de correo ausente, incompleto o inválido; revisión en Codex pendiente.')
                elif site not in clients:
                    result = {'rut': rut, 'source': site, 'status': 'error', 'folios': [], 'files': [], 'pages': 0, 'errors': [setup_errors.get(site, 'No hay una sesión disponible para este sitio.')]}
                    result['auth_required'] = site in blocked_auth
                    result['source_unavailable'] = site in blocked_network
                else:
                    try:
                        result = collect_group(clients[site], rut, site, source_periods.get(site, period), today, output, merge, list_only, progress, retry_unavailable)
                    except Exception as error:
                        # Mantiene folios verificados y pendientes si falló el guardado o la unión.
                        result = next(r for r in progress.state['results'] if r['rut'] == rut and r['source'] == site)
                        result['status'] = 'partial' if result.get('completed_folios') else 'error'
                        result['errors'].append(str(error))
                result['period'] = source_periods.get(site, period)
                result['elapsed_seconds'] = round(time.monotonic() - started, 3)
                result = progress.update(result)
                print('{} | {} | {}'.format(rut, LABELS[site], result['status']), flush=True)
                if result.get('source_unavailable'):
                    clients.pop(site, None)
                    blocked_network.add(site)
                    setup_errors[site] = 'Fuente pausada por fallo transitorio; reanudar más tarde.'
                if result.get('auth_required'):
                    clients.pop(site, None)
                    blocked_auth.add(site)
                    setup_errors[site] = 'La sesión venció. Renueva el acceso del sitio y reanuda la solicitud.'
        if not list_only:
            publish_reading_pdfs(progress, output)
        # Documentos de todas las fuentes/pacientes antes de iniciar las imágenes.
        for rut in normalized:
            if 'mmrad' in active and mmrad_mode in ('images', 'both'):
                if 'mmrad' not in clients:
                    result = {'rut':rut, 'source':'mmrad_images', 'status':'error', 'folios':[], 'files':[],
                              'pages':0, 'errors':[setup_errors.get('mmrad', 'No hay sesión MMRAD disponible.')]}
                else:
                    try:
                        result = collect_mmrad_images(clients['mmrad'], rut, source_periods.get('mmrad', period), today, output, list_only, progress, mmrad_image_types)
                    except Exception as error:
                        result = next(r for r in progress.state['results'] if r['rut'] == rut and r['source'] == 'mmrad_images')
                        result['status'] = 'partial' if result.get('completed_folios') else 'error'
                        result['errors'].append(str(error))
                result['period'] = source_periods.get('mmrad', period)
                result = progress.update(result)
                print('{} | MMRAD imágenes | {}'.format(rut, result['status']), flush=True)
                if result.get('source_unavailable'):
                    clients.pop('mmrad', None)
                    setup_errors['mmrad'] = 'Fuente pausada por fallo transitorio.'
                if result.get('auth_required'):
                    clients.pop('mmrad', None)
                    setup_errors['mmrad'] = 'La sesión MMRAD venció. Renueva el acceso y reanuda la solicitud.'
            if patient_merge and not list_only:
                try:
                    joined = merge_patient_documents(progress.state['results'], rut, output,
                                                     datetime.now(ZoneInfo('Pacific/Easter')).date())
                except (LabsError, OSError, ValueError) as error:
                    joined = {'rut': rut, 'status': 'error', 'files': [], 'pages': 0, 'errors': [str(error)]}
                if joined['status'] != 'complete':
                    previous = next((p for p in patient_pdfs if p.get('rut') == rut), {})
                    retained = []
                    for item in previous.get('file_manifest', []):
                        try:
                            path = Path(item['path']).resolve()
                            if path.is_relative_to(output.resolve() / rut) and hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']:
                                retained.append(item)
                        except (OSError, KeyError, TypeError): pass
                    if retained:
                        joined.update(status='partial', files=[p['path'] for p in retained], file_manifest=retained,
                                      freshness='update_pending', notice='Documento obtenido previamente; actualización pendiente.')
                patient_pdfs = [p for p in patient_pdfs if p.get('rut') != rut]
                patient_pdfs.append(joined)
                progress.state['patient_pdfs'] = patient_pdfs
                progress.save()
        summary = {'request':request, 'source': source, 'ruts': normalized, 'mmrad_mode':mmrad_mode, 'email_account':email_account, 'period': period, 'source_periods': source_periods, 'source_content': source_content, 'as_of': today.isoformat(), 'merge': merge,
                'list_only': list_only, 'patient_merge': patient_merge, 'patient_pdfs': patient_pdfs,
                'checkpoint': str(progress.path), 'results': progress.state['results']}
        from clinical_receipt import write
        write(summary,output)
        return summary


def main(argv=None, secrets=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ruts', nargs='+', required=True, help='Uno o varios RUT completos, con dígito verificador')
    parser.add_argument('--source', required=True, help='syslab, exalab, eloisa, mmrad, his, rayen, email, both, all (seis portales) o lista separada por coma')
    parser.add_argument('--eloisa-scope', choices=('medicos', 'todos'), default='medicos')
    parser.add_argument('--mmrad-mode', choices=('reports', 'images', 'both'), default='both',
                        help='Informes PDF, imágenes de radiografías/ecografías en PDF o ambos')
    parser.add_argument('--mmrad-image-types', default='radiographs,ultrasounds',
                        help='radiographs, ultrasounds o ambos separados por coma; excluye imágenes de ecocardiografías')
    parser.add_argument('--period', choices=PERIODS, required=True)
    parser.add_argument('--email-account', default='daniel.opazo@hospitalhangaroa.cl')
    parser.add_argument('--source-content', default='{}', help='JSON con contenidos por fuente Eloísa')
    parser.add_argument('--source-periods', default='{}', help='JSON con excepciones por fuente; las demás usan --period')
    parser.add_argument('--merge', action='store_true', help='Un PDF por paciente y fuente, con todas sus páginas')
    parser.add_argument('--patient-merge', action='store_true', help='Además, un PDF con todos los documentos completos de cada paciente')
    parser.add_argument('--output', type=Path, default=Path.cwd() / 'outputs' / 'laboratorios')
    parser.add_argument('--cache-dir',type=Path,help='Caché privada compartida entre pedidos; siempre revalida listado e identidad.')
    parser.add_argument('--as-of', type=date.fromisoformat)
    parser.add_argument('--list-only', action='store_true')
    parser.add_argument('--resume', type=Path, help='Archivo avance.json de una ejecución previa; conserva su fecha de referencia')
    parser.add_argument('--fresh', action='store_true', help='Nueva ejecución sin reutilizar los originales guardados')
    parser.add_argument('--retry-unavailable', action='store_true', help='Reintentar explícitamente folios Syslab o informes MMRAD marcados no disponibles')
    parser.add_argument('--session-stdin', action='store_true', help='Recibir sesiones/credenciales por una tubería privada')
    parser.add_argument('--retry-sources', help='Reanudar solo estas fuentes del mismo avance')
    parser.add_argument('--ready-sources', help='Preparar solo estas fuentes disponibles; las demás quedan pendientes')
    parser.add_argument('--image-workers', type=int, choices=(1,2), default=1)
    parser.add_argument('--eloisa-bounded', action='store_true', default=True, help='Consulta acotada por período, activada por defecto')
    parser.add_argument('--eloisa-full-history', dest='eloisa_bounded', action='store_false', help='Diagnóstico: consultar historial amplio y filtrar localmente')
    args = parser.parse_args(argv)
    selected = selected_sources(args.source)
    try: source_periods = normalize_source_periods(json.loads(args.source_periods), selected, args.period)
    except ValueError: raise LabsError('JSON de períodos por fuente inválido.') from None
    try: source_content = normalize_source_content(json.loads(args.source_content), selected)
    except ValueError: raise LabsError('Contenido por fuente inválido.') from None
    from clinical_content import validate_products
    validate_products(source_content,args.mmrad_mode)
    image_types = normalize_image_types(args.mmrad_image_types) if 'mmrad' in selected else ()
    if 'mmrad' in selected and args.mmrad_mode in ('images', 'both') and not image_types:
        raise LabsError('Selecciona al menos un tipo de imagen MMRAD.')
    active = selected_sources(args.retry_sources) if args.retry_sources else selected
    if not set(active).issubset(selected) or (args.retry_sources and not args.resume):
        raise LabsError('Reintento de fuentes inválido; requiere el mismo avance.')
    ready = selected_sources(args.ready_sources) if args.ready_sources else active
    if not set(ready).issubset(active): raise LabsError('Fuentes disponibles fuera de la solicitud activa.')
    exalab = load_backend('exalab')
    ruts = normalize_ruts(args.ruts)
    pdf_library()  # Verifica la dependencia antes de iniciar cualquier descarga.
    if args.resume and args.fresh:
        raise LabsError('--resume y --fresh no pueden usarse juntos.')
    today = args.as_of or (date.fromisoformat(read_progress(args.resume)['request']['as_of']) if args.resume else datetime.now(ZoneInfo('Pacific/Easter')).date())
    if args.resume:
        request = build_request(ruts,args.source,args.period,today,args.output,merge=args.merge,list_only=args.list_only,
                                patient_merge=args.patient_merge,eloisa_scope=args.eloisa_scope,mmrad_mode=args.mmrad_mode,
                                mmrad_image_types=image_types,source_periods=source_periods,
                                source_content=source_content,email_account=args.email_account)
        if read_progress(args.resume)['request'] != request:
            raise LabsError('El avance pertenece a otra solicitud.')
    if secrets is None:
        if args.session_stdin:
            try:
                secrets = json.loads(sys.stdin.read(65537))
            except ValueError:
                raise LabsError('No se recibió una sesión válida.') from None
        else:
            secrets = {}
    if not isinstance(secrets, dict):
        raise LabsError('No se recibió una sesión válida.')
    clients, errors = {}, {}
    auth_needed = False
    auth_sources = []
    for source in active:
        if source == 'email': continue
        if source not in ready:
            errors[source] = 'Acceso pendiente para esta fuente; las demás continúan.'
            continue
        try:
            if source == 'syslab':
                credentials = secrets.get('syslab') or {}
                username = credentials.get('username') or os.environ.get('SYSLAB_USERNAME')
                password = credentials.get('password') or os.environ.get('SYSLAB_PASSWORD')
                if sys.stdin.isatty() and not args.session_stdin:
                    username = username or input('Usuario Syslab: ').strip()
                    password = password or getpass('Contraseña Syslab (no se guarda): ')
                if not username or not password:
                    auth_needed = True
                    raise LabsError('Faltan las credenciales de Syslab.')
                module = load_backend('syslab')
                client = module.Syslab()
                client.login(username, password)
                del password
            elif source == 'exalab':
                if not isinstance(secrets.get('exalab'), dict):
                    auth_needed = True
                    auth_sources.append(source)
                    raise LabsError('Falta la sesión ClaveÚnica de Exalab. Renueva el acceso en Chrome.')
                client = exalab.Exalab(secrets['exalab'])
                client.preflight()
            elif source == 'mmrad':
                module = load_backend('mmrad')
                credentials = secrets.get('mmrad')
                if credentials is None:
                    username, password = module.local_credentials()
                elif isinstance(credentials, dict):
                    username, password = credentials.get('username'), credentials.get('password')
                else:
                    raise module.AuthenticationError('Credenciales MMRAD inválidas.')
                client = module.MMRAD()
                client.login(username, password)
                del password
            elif source == 'his':
                module = load_backend('his')
                credentials = secrets.get('his') or {}
                username = credentials.get('username') or os.environ.get('HIS_USER')
                password = credentials.get('password') or os.environ.get('HIS_PASS')
                if sys.stdin.isatty() and not args.session_stdin:
                    username = username or input('Usuario HIS: ').strip()
                    password = password or getpass('Contraseña HIS: ')
                if not username or not password:
                    auth_needed = True
                    raise module.AuthenticationError('Faltan las credenciales propias del HIS.')
                client = module.HIS()
                client.login(username, password)
                del password
            elif source == 'rayen':
                session = secrets.get('rayen')
                if not isinstance(session, dict):
                    auth_needed = True
                    auth_sources.append(source)
                    raise LabsError('Falta sesión del Registro Hospitalario en Chrome.')
                client = load_backend('rayen').Rayen(session)
            else:
                session = secrets.get('eloisa')
                if not isinstance(session, dict):
                    auth_needed = True
                    auth_sources.append(source)
                    raise LabsError('Falta la sesión de Eloísa. Entra desde Chrome y reanuda.')
                client = load_backend('eloisa').Eloisa(session, scope=args.eloisa_scope)
            clients[source] = Adapter(source, client)
        except Exception as error:
            errors[source] = str(error)
            if type(error).__name__ in ('SessionExpired', 'AuthenticationError'):
                auth_needed = True
                auth_sources.append(source)
    summary = run_batch(ruts, args.source, args.period, today, args.output, clients, args.merge, args.list_only, errors, args.resume, args.fresh, args.eloisa_scope, args.retry_unavailable, args.mmrad_mode, args.patient_merge, args.retry_sources, args.image_workers, args.eloisa_bounded, auth_sources, image_types, source_periods, source_content, args.email_account,args.cache_dir)
    summary['auth_sources'] = sorted(set(auth_sources + [r['source'].replace('mmrad_images','mmrad') for r in summary['results'] if r.get('auth_required')]))
    for result in summary['results']:
        unit = 'atención(es)' if result['source'] in ('eloisa','his') else 'estudio(s)' if result['source'] in ('mmrad','mmrad_images') else 'folio(s)'
        print('{} | {} | {} | {} {}, {} página(s)'.format(result['rut'], LABELS[result['source']], result['status'], len(result['folios']), unit, result['pages']))
        if result['source'] == 'mmrad' and result.get('no_report_expected'):
            print('  {} estudio(s) de otras modalidades sin informe PDF esperado.'.format(len(result['no_report_expected'])))
        for path in result['files']:
            print('  Archivo: ' + path)
        for item in result.get('no_images', []):
            print('  Sin imágenes | Estudio {}: {}'.format(item['id'], item['reason']))
        for error in result['errors']:
            print('  Pendiente: ' + error, file=sys.stderr)
    for joined in summary['patient_pdfs']:
        for path in joined['files']:
            print('PDF único: ' + path)
        for error in joined['errors']:
            print('  Pendiente PDF único: ' + error, file=sys.stderr)
    for receipt in summary['receipts']:
        print(receipt['text']+'TXT: '+receipt['path'])
    report = save_content(args.output, 'resumen_' + datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y_%H-%M-%S'), json.dumps(summary, ensure_ascii=False, indent=2).encode(), extension='.json')
    print('Resumen: ' + str(report))
    print('CLINICAL_RESULT ' + json.dumps({'checkpoint':summary['checkpoint'], 'auth_sources':summary['auth_sources'], 'summary':str(report)}))
    if auth_needed or any(result.get('auth_required') for result in summary['results']):
        return 2
    return 1 if any(result['status'] in ('partial', 'error', 'pending') for result in summary['results'] + summary['patient_pdfs']) else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (LabsError, EOFError, OSError, ValueError) as error:
        print('Error: {}'.format(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nCancelado.', file=sys.stderr)
        sys.exit(130)
