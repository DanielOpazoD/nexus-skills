"""Entregas clínicas: evidencia vigente → registro inmutable → copia comprobada.

Valida identidad, fechas y referencias; no certifica la exactitud médica de la
prosa. La revisión clínica sigue correspondiendo al redactor.
"""
import copy
import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from clinical_archive import ArchiveError, atomic_json, canonical_rut, clean_name, digest, name_key

ZONE = ZoneInfo('Pacific/Easter')


def policy():
    from clinical_delivery import CATALOG
    return json.loads(CATALOG.read_text())['baseline']


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def inside(path, root):
    path = Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()) or not path.is_file():
        raise ValueError('Archivo fuera del trabajo o no disponible.')
    return path.resolve()


def evidence(job, rut):
    """Toda evidencia del paciente y cobertura; cambia incluso sin nuevos PDF."""
    if rut not in job['ruts']:
        raise ValueError('Paciente fuera de la solicitud.')
    files = []
    for item in job['files']:
        if item['rut'] != rut:
            continue
        try:
            path = inside(item['path'], job['work_output'])
            if digest(path) != item['sha256']:
                continue
            files.append(dict(path=str(path), sha256=item['sha256'], source=item['source']))
        except (OSError, ValueError):
            continue
    rows = [r for r in job['summary'] if r.get('rut') == rut]
    names = {}
    preference={'eloisa':0,'rayen':1,'syslab':2,'exalab':3,'mmrad':4,'his':5,'email':6}
    for row in sorted(rows,key=lambda r:preference.get(r.get('source'),99)):
        if row.get('file_manifest') and row.get('patient_name') and row['patient_name'] != 'Nombre no disponible':
            try:
                name=clean_name(row['patient_name'])
                signature=tuple(sorted(name_key(part) for part in name.split()))
                names.setdefault(signature,name)
            except ArchiveError:pass
    name = next(iter(names.values())) if len(names) == 1 else None
    context = dict(job=job['id'], rut=rut, asOf=job['as_of'], name=name,
                   sources=job['selected'], period=job['period'],
                   sourcePeriods=job.get('source_periods', {}), sourceContent=job.get('source_content', {}),
                   coverage=sorted([{'source':r['source'], 'status':r['status'],
                                     'freshness':r.get('freshness'), 'errors':r.get('errors', [])} for r in rows],
                                   key=lambda r:r['source']),
                   files=sorted(files, key=lambda f:(f['source'], f['path'], f['sha256'])))
    return dict(context, revision=fingerprint(context))


def ledger_path(job):
    return Path(job['work_output'])/'.entregas'/'registro.json'


def load(job):
    path = ledger_path(job)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Registro de entregas enlazado; requiere revisión.')
    try:
        from clinical_request import decode_json
        data = decode_json(path.read_text())
    except FileNotFoundError:
        return {'version':1, 'job':job['id'], 'artifacts':[]}
    if (not isinstance(data, dict) or data.get('version') != 1 or data.get('job') != job['id']
        or not isinstance(data.get('artifacts'), list)):
        raise ValueError('Registro de entregas incompatible; conservado para revisión.')
    return data


def text_of(path, content=None):
    content=content if content is not None else path.read_bytes()
    if len(content) > 10*1024*1024:
        raise ValueError('Entrega demasiado grande para validar.')
    if path.suffix.lower() == '.txt':
        return content.decode('utf-8')
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        return '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(content)).pages)
    if path.suffix.lower() == '.docx':
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if not {'[Content_Types].xml','_rels/.rels','word/document.xml'}.issubset(archive.namelist()):
                raise ValueError('Paquete DOCX incompleto.')
            item = archive.getinfo('word/document.xml')
            if item.file_size > 5*1024*1024:
                raise ValueError('Documento demasiado grande para validar.')
            root = ET.fromstring(archive.read(item))
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        if root.tag != ns+'document':raise ValueError('Documento Word inválido.')
        return '\n'.join(''.join(p.itertext()) for p in root.iter(ns+'p'))
    raise ValueError('Tipo de entrega no admitido.')


def validate_header(text, snapshot, created_on, baseline):
    header = text[:2000]
    # Pareja adyacente Paciente/RUT: nunca una coincidencia bajo otro rol.
    identity = re.search(r'^Paciente:\s*([^\n]+)\n(?:RUT|RUN):\s*([\d.]+-[\dKk])\s*$', header, re.M|re.I)
    if not identity or canonical_rut(identity[2]) != snapshot['rut']:
        raise ValueError('Falta la pareja Paciente/RUT en el encabezado de la entrega.')
    if ((not snapshot['name'] and snapshot['files']) or
        name_key(identity[1]) != name_key(snapshot['name'] or 'Nombre no disponible')):
        raise ValueError('El nombre no coincide con la identidad verificada del trabajo.')
    if len(re.findall(r'^Paciente:',header,re.M|re.I)) != 1:
        raise ValueError('Encabezado con varios pacientes; requiere revisión.')
    if baseline:
        for label, expected in (('Fecha de elaboración', created_on),
                                ('Fecha de referencia', datetime.fromisoformat(snapshot['asOf']).strftime('%d-%m-%Y'))):
            if not re.search(r'^'+label+r':\s*'+re.escape(expected)+r'\s*$', header, re.M):
                raise ValueError('Encabezado incompleto: '+label+'.')
        if re.search(r'\b\d{4}-\d{2}-\d{2}\b', text):
            raise ValueError('Usa DD-MM-AAAA en el texto clínico.')
        for day in re.findall(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b', text):
            if not re.fullmatch(r'\d{2}-\d{2}-\d{4}',day):raise ValueError('Usa DD-MM-AAAA en el texto clínico.')
            datetime.strptime(day, '%d-%m-%Y')
        clinical_lines=[line for line in text.splitlines() if line.strip() and
                        not re.match(r'^(Paciente|RUT|RUN|Fecha de elaboración|Fecha de referencia):',line,re.I)
                        and line.strip().casefold() not in ('resumen antecedentes','resumen de antecedentes')]
        if len(' '.join(clinical_lines).strip()) < 20:
            raise ValueError('El TXT basal contiene solo el encabezado; falta la síntesis clínica.')
    if len(text.strip()) < 80 or '\x00' in text:
        raise ValueError('Entrega vacía o texto inválido.')


def register(job, submission):
    from pypdf.errors import PyPdfError
    from xml.etree.ElementTree import ParseError
    try:return _register(job, submission)
    except (ArchiveError, TypeError, KeyError, OverflowError, zipfile.BadZipFile, PyPdfError, ParseError, OSError, UnicodeError) as error:
        raise ValueError('Estructura, identidad o archivo de entrega inválido.') from error


def _register(job, submission):
    """Idempotente por contenido. Publicar registro solo tras verificar ambos TXT."""
    allowed = {'version','jobId','rut','asOf','evidenceRevision','createdOn','kind','path','citations','notes'}
    if not isinstance(submission, dict) or set(submission)-allowed or submission.get('version') != 1:
        raise ValueError('Contrato de entrega inválido.')
    rut = submission.get('rut')
    snapshot = evidence(job, rut)
    if (submission.get('jobId') != job['id'] or submission.get('asOf') != job['as_of']
        or submission.get('evidenceRevision') != snapshot['revision']):
        raise ValueError('La evidencia cambió o la entrega pertenece a otra solicitud; actualiza el encargo.')
    if job['status'] in ('running', 'cancelling', 'queued'):
        raise ValueError('Espera a que termine la descarga activa antes de registrar la entrega.')
    created_on = submission.get('createdOn')
    if not isinstance(created_on,str) or not re.fullmatch(r'\d{2}-\d{2}-\d{4}',created_on):
        raise ValueError('La fecha de elaboración debe usar DD-MM-AAAA.')
    created = datetime.strptime(created_on, '%d-%m-%Y').date()
    if created > datetime.now(ZONE).date() or created < datetime.fromisoformat(job['started_at']).astimezone(ZONE).date():
        raise ValueError('La fecha de elaboración está fuera de esta corrida.')
    kind = submission.get('kind')
    baseline = kind == policy()['id']
    if (not baseline and kind != job.get('delivery', {}).get('id')) or kind == 'documents':
        raise ValueError('Producto no solicitado.')
    path = inside(submission.get('path', ''), job['work_output'])
    if baseline and path.name != policy()['filename'].format(date=created_on):
        raise ValueError('Nombre del TXT basal incompatible con el catálogo.')
    if not baseline and created_on not in path.name:
        raise ValueError('El nombre de la entrega debe incluir DD-MM-AAAA.')
    with path.open('rb') as stream:content=stream.read(10*1024*1024+1)
    validate_header(text_of(path,content), snapshot, created_on, baseline)
    citations = submission.get('citations')
    if not isinstance(citations, list) or len(citations) > 1000:
        raise ValueError('Referencias de sustento inválidas.')
    if snapshot['files'] and not citations:
        raise ValueError('La entrega necesita sustento en los documentos verificados.')
    if not snapshot['files'] and 'No se obtuvo documentación clínica verificable' not in content.decode('utf-8', errors='replace'):
        raise ValueError('Sin evidencia, declara que no se obtuvo documentación clínica verificable.')
    verified = {(f['path'], f['sha256']) for f in snapshot['files']}
    lines = [];page_counts = {}
    for ref in citations:
        if not isinstance(ref, dict) or set(ref) != {'path','sha256','pages','claim'}:
            raise ValueError('Referencia de sustento incompleta.')
        if (ref['path'], ref['sha256']) not in verified:
            raise ValueError('Referencia de otro paciente o archivo no vigente.')
        pages = ref['pages']
        if not isinstance(ref['claim'], str) or not ref['claim'].strip() or len(ref['claim']) > 4000:
            raise ValueError('Indica qué afirmación sustenta cada referencia.')
        if not isinstance(pages, list) or any(type(p) is not int or p < 1 for p in pages):
            raise ValueError('Páginas de sustento inválidas.')
        if Path(ref['path']).suffix.lower() == '.pdf':
            from pypdf import PdfReader
            key=(ref['path'],ref['sha256'])
            if key not in page_counts:
                reference_content=Path(ref['path']).read_bytes()
                if hashlib.sha256(reference_content).hexdigest()!=ref['sha256']:
                    raise ValueError('El documento de sustento cambió durante el registro.')
                page_counts[key] = len(PdfReader(io.BytesIO(reference_content)).pages)
            count=page_counts[key]
            if not pages or any(p > count for p in pages):
                raise ValueError('Página inexistente o ausente en el sustento.')
        elif pages:
            raise ValueError('El archivo no tiene páginas PDF verificables; usa pages: [].')
        lines.append(ref['claim'].strip()+'\n  '+Path(ref['path']).name+' · páginas '+(', '.join(map(str,pages)) or 'no aplica')+'\n  SHA-256: '+ref['sha256'])
    notes = submission.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 20000:
        raise ValueError('Observaciones de sustento inválidas.')
    support = ('Paciente: '+(snapshot['name'] or 'Nombre no disponible')+'\nRUT: '+rut+'\nFecha de elaboración: '+created_on+
               '\nFecha de referencia: '+datetime.fromisoformat(job['as_of']).strftime('%d-%m-%Y')+
               '\nSolicitud: '+job['id']+'\nRevisión de evidencia: '+snapshot['revision']+'\n\n'+
               '\n\n'.join(lines)+'\n\n'+notes.strip()+'\n').encode()
    key = fingerprint(dict(submission, path=None, content=hashlib.sha256(content).hexdigest()))
    data = load(job)
    for item in data['artifacts']:
        if item.get('key') == key:
            if all(digest(inside(item[f], job['work_output'])) == item[f+'_sha256'] for f in ('path','support')):
                return dict(item, reused=True)
            raise ValueError('Una entrega registrada fue modificada; conserva esa edición y registra una revisión nueva.')
    directory = ledger_path(job).parent/uuid.uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    target = directory/path.name
    support_path = directory/(policy()['supportFilename'].format(date=created_on) if baseline else created_on+' Sustento '+kind+'.txt')
    for target_path, value in ((target, content), (support_path, support)):
        import os
        with target_path.open('xb') as stream:
            stream.write(value);stream.flush();os.fsync(stream.fileno())
    item = dict(key=key, kind=kind, rut=rut, name=snapshot['name'], createdOn=created_on,
                registered_at=datetime.now(ZONE).isoformat(), evidence_revision=snapshot['revision'],
                path=str(target), path_sha256=digest(target), support=str(support_path),
                support_sha256=digest(support_path), citations=copy.deepcopy(citations))
    if digest(target) != hashlib.sha256(content).hexdigest() or evidence(job,rut)['revision'] != snapshot['revision']:
        raise ValueError('La entrega cambió durante el registro.')
    data['artifacts'].append(item)
    atomic_json(ledger_path(job), data)
    return dict(item, reused=False)


def states(job):
    """Ausencia, vigencia y archivo son hechos diferentes de descargar o copiar."""
    try:
        artifacts = load(job)['artifacts'];error = None
    except (OSError, ValueError, TypeError):
        artifacts = [];error = 'Registro de entregas pendiente de revisión.'
    rows = []
    for rut in job['ruts']:
        snapshot = evidence(job, rut)
        for kind in [policy()['id']]+([job['delivery']['id']] if job['delivery']['id'] != 'documents' else []):
            candidates = [a for a in artifacts if isinstance(a,dict) and a.get('rut') == rut and a.get('kind') == kind]
            item = candidates[-1] if candidates else None
            state = 'modified' if error else 'pending';reason = error or 'Redacción pendiente.'
            if item:
                try:
                    for field in ('path','support'):
                        if digest(inside(item[field], job['work_output'])) != item[field+'_sha256']:
                            raise ValueError()
                    state = 'verified' if item['evidence_revision'] == snapshot['revision'] else 'stale'
                    reason = 'Documento verificado; copia pendiente.' if state == 'verified' else 'Fuentes actualizadas; revisar la entrega anterior.'
                except (OSError, ValueError, KeyError):
                    state = 'modified';reason = 'Entrega o sustento modificado/ausente; revisión pendiente.'
                if state == 'verified':
                    copies = job.get('archive', {}).get('files', [])
                    matched = [next((f for f in copies if f.get('artifact_key') == item['key'] and f.get('sha256') == item[field+'_sha256']
                                     and f.get('copy') == 'verified'), None) for field in ('path','support')]
                    if all(matched):
                        try:
                            if not all(digest(f['path']) == f['sha256'] for f in matched):raise ValueError()
                            state = 'archived';reason = 'Copia local verificada.'
                            if all(f.get('sync') == 'confirmed' for f in matched):reason = 'Copia y sincronización verificadas.'
                        except (OSError, ValueError):
                            reason = 'Copia archivada modificada/ausente; revisión pendiente.'
            public_item={k:copy.deepcopy(v) for k,v in item.items() if k!='citations'} if item else None
            rows.append(dict(rut=rut, name=snapshot['name'], kind=kind, status=state, reason=reason,
                             evidenceRevision=snapshot['revision'], artifact=public_item))
    return rows
