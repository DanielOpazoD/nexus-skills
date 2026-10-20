"""Persistencia versionada de la cola y aislamiento de trabajos dañados."""
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import copy
import hashlib
import json
import re

from clinical_archive import atomic_json
from clinical_request import decode_json, validate_request

from clinical_state import JOB_STATES, SOURCE_STATES

PERSISTED_FIELDS = (
    'id', 'status', 'selected', 'ruts', 'source', 'period', 'eloisa_scope', 'mmrad_mode',
    'mmrad_image_types', 'merge', 'patient_merge', 'lines', 'files', 'summary', 'code',
    'started_at', 'updated_at', 'checkpoint', 'result_path', 'work_output',
    'pending_sources', 'source_states', 'attempted', 'cancel_requested', 'archive',
    'archive_dirty', 'as_of', 'delivery', 'source_periods', 'source_content',
    'email_account', 'receipts', 'request_id', 'request_fingerprint',
)

@dataclass
class QueueSnapshot:
    jobs: dict
    quarantined: list


def validate_saved_job(key, value, output):
    """Valida el estado persistido antes de usar rutas o reanudar trabajo."""
    if not isinstance(value, dict):
        raise ValueError('Estructura de trabajo inválida.')
    job = copy.deepcopy(value)
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', key) or job.get('id') != key:
        raise ValueError('Identificador de trabajo inválido.')
    request = {
        'schema': 2, 'ruts': job['ruts'], 'source': job['source'], 'period': job['period'],
        'eloisaScope': job['eloisa_scope'], 'mmradMode': job['mmrad_mode'],
        'mmradImageTypes': job.get('mmrad_image_types', ['radiographs', 'ultrasounds']),
        'merge': job['merge'], 'patientMerge': job['patient_merge'],
        'sourcePeriods': job.get('source_periods', {}), 'sourceContent': job.get('source_content', {}),
        'emailAccount': job.get('email_account', 'daniel.opazo@hospitalhangaroa.cl'),
        'deliveryModel': job.get('delivery', {}).get('id', 'documents'),
        'deliveryInstructions': job.get('delivery', {}).get('instructions', ''),
    }
    if 'request_id' in job:
        request.update(requestId=job['request_id'], asOf=job['as_of'])
    normalized = validate_request(request, local=True)
    if 'request_id' in job:
        from clinical_request import request_fingerprint
        if request_fingerprint(normalized) != job.get('request_fingerprint'):
            raise ValueError('La solicitud guardada cambió de contenido.')
    if job['ruts'] != normalized['ruts'] or job['source'] != normalized['source']:
        raise ValueError('Identidad o fuentes no canónicas.')
    if job['selected'] != normalized['source'].split(','):
        raise ValueError('Selección de fuentes incoherente.')
    if job['status'] not in JOB_STATES:
        raise ValueError('Estado de trabajo desconocido.')
    for field in ('attempted', 'cancel_requested'):
        if type(job[field]) is not bool:
            raise ValueError('Estado de ejecución inválido.')
    for field in ('lines', 'files', 'summary', 'pending_sources'):
        if not isinstance(job[field], list):
            raise ValueError('Colección de trabajo inválida.')
    if any(not isinstance(line, str) for line in job['lines']):
        raise ValueError('Registro de eventos inválido.')
    if any(source not in job['selected'] for source in job['pending_sources']):
        raise ValueError('Fuente pendiente fuera del alcance.')
    states = job['source_states']
    if not isinstance(states, dict) or set(states) != set(job['selected']) or any(state not in SOURCE_STATES for state in states.values()):
        raise ValueError('Estados por fuente incoherentes.')
    if not isinstance(job['as_of'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', job['as_of']):
        raise ValueError('Fecha de referencia inválida.')
    date.fromisoformat(job['as_of'])
    for field in ('started_at', 'updated_at'):
        datetime.fromisoformat(job[field])
    work = Path(output).resolve() / '.trabajos' / key / 'datos'
    if Path(job['work_output']).resolve() != work:
        raise ValueError('Carpeta de trabajo fuera de la cola.')
    for field in ('checkpoint', 'result_path'):
        if job.get(field) is not None and (not isinstance(job[field], str) or not Path(job[field]).resolve().is_relative_to(work)):
            raise ValueError('Referencia de archivo fuera del trabajo.')
    if not isinstance(job['archive'], dict) or not isinstance(job.get('delivery', {}), dict):
        raise ValueError('Estado de archivo o entrega inválido.')
    return job


class QueueStore:
    VERSION = 2

    def __init__(self, path, output):
        self.path = Path(path)
        self.output = Path(output)
        self.quarantined = []
        self.original = None

    def backup(self):
        """Conservar exactamente los bytes previos, también en una migración."""
        if self.original is None:
            return None
        checksum = hashlib.sha256(self.original).hexdigest()
        stamp = datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y')
        path = self.path.parent / 'recuperacion' / f'Cola - {stamp} - {checksum[:16]}.json'
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with path.open('xb') as stream:
                import os
                os.chmod(path, 0o600)
                stream.write(self.original)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if path.read_bytes() != self.original:
                raise RuntimeError('El respaldo de la cola requiere revisión.') from None
        return str(path)

    def quarantine(self, key, reason, value=None):
        backup = self.backup()
        entry = {'id': str(key)[:128], 'reason': reason, 'backup': backup}
        request_id = value.get('request_id') if isinstance(value, dict) else None
        if isinstance(request_id, str) and re.fullmatch(r'[0-9a-f]{32}', request_id):
            entry['request_id'] = request_id
        self.quarantined.append(entry)

    def load(self):
        try:
            self.original = self.path.read_bytes()
        except FileNotFoundError:
            return QueueSnapshot({}, [])
        try:
            data = decode_json(self.original)
            if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] not in (1, self.VERSION) or not isinstance(data.get('jobs'), dict):
                raise ValueError()
            quarantined = data.get('quarantined', [])
            if not isinstance(quarantined, list) or any(not isinstance(item, dict) or not isinstance(item.get('id'), str) or not isinstance(item.get('reason'), str) for item in quarantined):
                raise ValueError()
        except (ValueError, TypeError):
            raise RuntimeError('La cola guardada es ilegible o de una versión incompatible; se conservó sin reemplazar.') from None
        self.quarantined = quarantined
        if data['version'] == 1:
            self.backup()
        jobs = {}
        for key, value in data['jobs'].items():
            try:
                jobs[key] = validate_saved_job(key, value, self.output)
            except (ValueError, TypeError, KeyError, AttributeError):
                self.quarantine(key, 'Trabajo inválido; revisar el respaldo antes de recuperarlo.', value)
        ids = {}
        for key, job in jobs.items():
            if job.get('request_id'):
                ids.setdefault(job['request_id'], []).append(key)
        for keys in ids.values():
            if len(keys) > 1:
                for key in keys:
                    self.quarantine(key, 'Identificador de solicitud duplicado; revisión pendiente.', jobs.pop(key))
        return QueueSnapshot(jobs, self.quarantined)

    def save(self, jobs):
        saved = {key: {field: copy.deepcopy(job[field]) for field in PERSISTED_FIELDS if field in job}
                 for key, job in jobs.items()}
        atomic_json(self.path, {'version': self.VERSION, 'jobs': saved, 'quarantined': self.quarantined})
