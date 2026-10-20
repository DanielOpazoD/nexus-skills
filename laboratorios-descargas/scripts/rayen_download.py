"""Adaptador del cliente Rayen a la descarga y avance comunes."""
from pathlib import Path
from datetime import datetime, date, timedelta, time, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
import hashlib
import importlib.util
import json

path = Path(__file__).resolve().parents[2] / 'rayen-epicrisis/scripts/rayen_epicrisis.py'
spec = importlib.util.spec_from_file_location('rayen_client', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Rayen:
    def __init__(self, session, content=None):
        self.client = module.Client(session)
        self.pending_records = []
        self.content = content
        self.auth_required = False

    def search(self, rut, period, today):
        from laboratorios_download import load_backend
        subtract_months = load_backend('syslab').subtract_months
        start = date(1900, 1, 1) if period == 'latest' else today - timedelta(days=30) if period == '30d' else subtract_months(today, {'3m':3, '6m':6,'1y':12,'2y':24,'5y':60, '10y':120}[period])
        from clinical_content import normalize_source_content
        content = normalize_source_content({'rayen':self.content},['rayen'])['rayen'] if getattr(self,'content',None) is not None else ['epicrisis']
        self.pending_records, self.auth_required, rows = [], False, []
        for kind in content:
            try:
                found, pending = self.client.episodes(rut,start,today,history=True) if kind == 'record' else self.client.episodes(rut,start,today)
                self.pending_records.extend(dict(p,report_type=kind) for p in pending)
                if kind == 'epicrisis': rows = found
                else:
                    for row in found[:1] if period == 'latest' else found:
                        self.pending_records.append({'episode':row['encounterId'],'report_type':'record',
                            'reason':'Ficha completa: descargar y verificar el PDF desde el visor oficial.',
                            'patient_identifier':rut,'patient_name':row['patientName'],
                            'start':row['startPeriod'],'end':row.get('endPeriod'),
                            'viewer_url':history_viewer_url(row,today)})
            except (module.ReportError, module.SourceUnavailable) as error:
                self.auth_required = self.auth_required or isinstance(error,module.SessionExpired)
                self.pending_records.append({'episode':'búsqueda','report_type':kind,'reason':str(error)})
        return [{'id':str(row['encounterId']), 'rut':rut, 'name':row['patientName'],
                 'datetime':datetime.combine(date.fromisoformat(str(row['endPeriod'])[:10]), datetime.min.time()),
                 'raw':row, 'fingerprint':hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()}
                for row in rows]

    def download(self, exam):
        return self.client.pdf(exam['raw'])


def history_viewer_url(row, today):
    """Official viewer URL from HHR-entornodeprueba; no credentials in the URL."""
    if not module.valid_id(row.get('encounterId')): raise module.ReportError('Episodio inválido.')
    try:
        start = datetime.fromisoformat(str(row['startPeriod']).replace('Z','+00:00'))
        end = datetime.fromisoformat(str(row['endPeriod']).replace('Z','+00:00')) if row.get('endPeriod') else None
        if end and end.date() < start.date(): raise ValueError()
    except (KeyError,ValueError,TypeError): raise module.ReportError('Fechas de hospitalización inválidas.') from None
    limit = datetime.combine(today,time.max,tzinfo=ZoneInfo('Pacific/Easter')).astimezone(timezone.utc)
    params={'enc_id':str(row['encounterId']),'start_date':row['startPeriod'],
            'end_date':row['endPeriod'] if end and end.date() <= today else limit.isoformat()}
    return 'https://fichamedico.rayensalud.cl/dashboard/reports?'+urlencode({
        'isReportServer':'true','report':'GetHospitalizedEncounterHistory',
        'params':json.dumps(params,separators=(',',':'))})
