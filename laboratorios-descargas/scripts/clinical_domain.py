"""Identidad y alcance del encargo; sin motor, red, sesiones ni escritura."""
from pathlib import Path
import re
from clinical_content import normalize_source_content
from mmrad_selection import normalize_image_types

PERIODS = ('30d', '3m', '6m', '1y', '2y', '5y', '10y', 'latest')
SOURCE_ORDER = ('syslab', 'exalab', 'eloisa', 'mmrad', 'his', 'rayen', 'email')


def selected_sources(source):
    if source == 'both':
        return ['syslab', 'exalab']
    if source == 'all':
        return list(SOURCE_ORDER[:-1])  # Compatibilidad: all histórico no amplía acceso al correo.
    selected = source.split(',')
    if not selected or len(set(selected)) != len(selected) or any(item not in SOURCE_ORDER for item in selected):
        raise LabsError('Fuentes inválidas; usa nombres separados por coma o all.')
    return [item for item in SOURCE_ORDER if item in selected]


class LabsError(Exception):
    pass


def normalize_ruts(ruts):
    """Contrato de identidad independiente de clientes y credenciales."""
    result = []
    for value in ruts:
        if not isinstance(value, str):
            raise LabsError('RUT inválido.')
        value = value.strip().replace('.', '').upper()
        match = re.fullmatch(r'(\d{7,8})-([0-9K])', value)
        if not match:
            raise LabsError('Ingresa el RUT con dígito verificador y guion.')
        body, digit = match.groups()
        check = 11 - sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(body))) % 11
        expected = '0' if check == 11 else 'K' if check == 10 else str(check)
        if digit != expected:
            raise LabsError('El dígito verificador no coincide.')
        if value not in result:
            result.append(value)
    return result


def normalize_source_periods(value, selected, common):
    """Sólo excepciones efectivas; solicitudes antiguas mantienen su checkpoint."""
    if value is None:
        return {}
    if not isinstance(value, dict) or any(not isinstance(k,str) or k not in selected or not isinstance(v,str) or v not in PERIODS for k,v in value.items()):
        raise LabsError('Períodos por fuente inválidos.')
    return {k:value[k] for k in sorted(value) if value[k] != common}


def build_request(ruts, source, period, today, output, *, merge=False, list_only=False,
                  patient_merge=False, eloisa_scope='medicos', mmrad_mode='reports',
                  mmrad_image_types=None, source_periods=None, source_content=None,
                  email_account='daniel.opazo@hospitalhangaroa.cl'):
    """Identidad completa del avance, compartida por CLI, motor y recuperación."""
    normalized = normalize_ruts(ruts)
    selected = selected_sources(source)
    if not isinstance(period, str) or period not in PERIODS:
        raise LabsError('Período inválido.')
    if eloisa_scope not in ('medicos', 'todos') or mmrad_mode not in ('reports', 'images', 'both'):
        raise LabsError('Filtros inválidos.')
    if any(type(value) is not bool for value in (merge, list_only, patient_merge)):
        raise LabsError('Opciones de PDF inválidas.')
    source_periods = normalize_source_periods(source_periods, selected, period)
    source_content = normalize_source_content(source_content, selected)
    from clinical_content import validate_products
    validate_products(source_content, mmrad_mode)
    output = Path(output)
    request = {'ruts': normalized, 'source': source, 'period': period, 'as_of': today.isoformat(),
               'merge': merge, 'list_only': list_only, 'output': str(output.resolve())}
    if 'email' in selected:
        from clinical_email import account
        request['email_account'] = account(email_account)
    if source_periods:
        request['source_periods'] = source_periods
    if source_content:
        request['source_content'] = source_content
    if patient_merge:
        request['patient_merge'] = True
    if 'eloisa' in selected:
        request['eloisa_scope'] = eloisa_scope
    if 'mmrad' in selected:
        request['mmrad_mode'] = mmrad_mode
        if mmrad_mode in ('images', 'both'):
            mmrad_image_types = normalize_image_types(mmrad_image_types)
            if not mmrad_image_types:
                raise LabsError('Selecciona al menos un tipo de imagen MMRAD.')
            request['mmrad_image_types'] = list(mmrad_image_types)
            request['mmrad_image_policy'] = 'exclude-echocardiography-v1'
    return request

