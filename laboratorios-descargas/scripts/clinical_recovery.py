"""Lectura y reconciliación de avances. No crea trabajos ni persiste la cola."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import copy
import json
from clinical_domain import build_request
from clinical_integrity import audit_results, result_keys, completed

BROWSER_SOURCES = ('exalab', 'eloisa', 'rayen')

@dataclass(frozen=True)
class SourceProgress:
    states: dict[str, str]
    pending: list[str]

@dataclass(frozen=True)
class RecoverySnapshot:
    checkpoint: str | None
    summary: dict
    files: list[dict]
    failed: bool
    messages: tuple[str, ...]
    cache: dict


def reconcile_sources(job):
    states = {}
    pending = []
    for source in job['selected']:
        expected = set(result_keys(job['ruts'], [source], job['mmrad_mode']))
        done = {(row['rut'], row['source']) for row in job['summary']
                if (row.get('rut'), row.get('source')) in expected and completed(row)}
        if done == expected:
            states[source] = 'complete'
            continue
        pending.append(source)
        if source == 'email':
            states[source] = 'needs_codex'
        elif source in BROWSER_SOURCES:
            states[source] = 'needs_session'
        elif job['source_states'].get(source) == 'needs_credentials':
            states[source] = 'needs_credentials'
        else:
            states[source] = 'attention'
    return SourceProgress(states, pending)


def expected_request(job):
    return build_request(job['ruts'],job['source'],job['period'],date.fromisoformat(job['as_of']),
        job['work_output'],merge=job['merge'],patient_merge=job['patient_merge'],
        eloisa_scope=job['eloisa_scope'],mmrad_mode=job['mmrad_mode'],
        mmrad_image_types=job.get('mmrad_image_types',('radiographs','ultrasounds')),
        source_periods=job.get('source_periods'),source_content=job.get('source_content'),
        email_account=job.get('email_account','daniel.opazo@hospitalhangaroa.cl'))


def recover(job, engine):
    """Resultado explícito; el llamador decide si publica/persiste este estado."""
    work = Path(job['work_output']).resolve()
    expected = expected_request(job)
    pointer = job.get('checkpoint')
    paths = [Path(pointer)] if pointer else []
    paths += list((work / '.avance').glob('*/avance.json'))
    candidates = []
    seen = set()
    invalid = False
    summary = None
    # El avance atómico es autoridad; un resumen reciente no cambia su identidad.
    for path in paths:
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        if not path.is_relative_to(work):
            invalid = True
            continue
        try:
            data = engine.read_progress(path)
            if data['request'] != expected:
                invalid = True
                continue
            candidates.append((path, data))
        except engine.LabsError:
            invalid = True
    # Una referencia explícita válida puede distinguir avances --fresh.
    chosen = next((item for item in candidates if pointer and item[0] == Path(pointer).resolve()), None)
    if chosen is None and len(candidates) == 1:
        chosen = candidates[0]
    checkpoint = str(chosen[0]) if chosen else None
    if chosen:
        summary = dict(chosen[1]['request'], results=chosen[1]['results'], checkpoint=checkpoint,
                       patient_pdfs=chosen[1].get('patient_pdfs', []))
    elif not paths and job.get('result_path'):
        path = Path(job['result_path']).resolve()
        try:
            data = json.loads(path.read_text()) if path.is_relative_to(work) else {}
            if data.get('request') == expected:
                summary = data
            else:
                invalid = True
        except (OSError, ValueError, AttributeError):
            invalid = True
    failed = summary is None and (invalid or len(candidates) > 1)
    message = 'Avance incompatible, ambiguo o ilegible; archivos conservados. Crea otra solicitud para continuar.'
    if summary is None:
        summary = {'results': copy.deepcopy(job['summary']),
                   'patient_pdfs': copy.deepcopy(job.get('_summary', {}).get('patient_pdfs', []))}
        if failed:
            for row in summary['results'] + summary['patient_pdfs']:
                if isinstance(row, dict):
                    row.update(status='partial', errors=[message])
    cache = dict(job.get('_integrity_cache', {}))
    summary['results'] = audit_results(summary.get('results'), work,
                                      result_keys(job['ruts'], job['selected'], job['mmrad_mode']), cache)
    summary['patient_pdfs'] = audit_results(summary.get('patient_pdfs'), work,
                                           [(rut, None) for rut in job['ruts']] if job['patient_merge'] else [], cache)
    # Un SIGINT puede preceder la publicación: recuperar originales clínicamente verificados.
    if checkpoint:
        try:
            data = engine.read_progress(checkpoint)
            recovery = engine.Progress(work, data['request'], resume=checkpoint)
            recovery.state = data
            for row in summary['results']:
                if row['status'] not in ('complete', 'empty', 'listed', 'no_reports', 'no_images'):
                    retained = recovery.verified_previous(row)
                    if retained:
                        row.update(files=[item['path'] for item in retained], file_manifest=retained, status='partial')
                        row.setdefault('notice', 'Documentos verificados conservados; ejecución pendiente.')
        except (OSError, ValueError, KeyError, TypeError, engine.LabsError):
            pass
    files = {}
    for row in summary['results'] + summary['patient_pdfs']:
        for item in row.get('file_manifest', []):
            path = Path(item['path']).resolve()
            if path.is_relative_to(work) and path.is_file():
                files[str(path)] = {'name': path.name, 'path': str(path), 'sha256': item['sha256'],
                                    'source': row.get('source', 'PDF único'), 'rut': row['rut']}
    return RecoverySnapshot(checkpoint, summary, list(files.values()), failed,
                            (message,) if failed else (), cache)
