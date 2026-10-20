"""Selección de imágenes MMRAD, sin sesiones ni dependencias de red."""
import re
import unicodedata

from clinical_content import CATALOG
IMAGE_TYPES = tuple(CATALOG['mmrad']['imageTypes'])


def normalize_image_types(value=None):
    if value is None:
        return IMAGE_TYPES
    if isinstance(value, str):
        value = value.split(',') if value else []
    if not isinstance(value, (list, tuple)) or any(v not in IMAGE_TYPES for v in value):
        raise ValueError('Selecciona radiografías y/o ecografías para las imágenes MMRAD.')
    return tuple(v for v in IMAGE_TYPES if v in value)


def is_echocardiography(record):
    # Sólo descripciones del estudio/series; nunca el nombre o texto clínico del paciente.
    keys = ('exam_name', 'studyDescription', 'StudyDescription', 'seriesDescription',
            'SeriesDescription', 'protocolName', 'ProtocolName')
    descriptions = [str(record.get(key) or '') for key in keys]
    for series in record.get('seriesList', []) or []:
        if isinstance(series, dict) and is_echocardiography(series):
            return True
    text = unicodedata.normalize('NFKD', ' '.join(descriptions)).encode('ascii', 'ignore').decode().upper()
    return bool(re.search(r'E(?:C|CH)O\s*[- ]?\s*CARD|\b(?:ECOTT|ECOTE|ETT|ETE|TTE|TEE)\b|'
                         r'\bECO\s+(?:TT|TE|STRESS|ESTRES)\b|'
                         r'(?:ECO|ULTRASOUND|ULTRASON|DOPPLER).*?(?:CARDIAC|CORAZON|TRANSTORAC|TRANSESOFAG)|'
                         r'(?:CARDIAC|HEART).*?(?:ECHO|ULTRASOUND)', text))


def image_exclusion(exam, image_types=None):
    if is_echocardiography(exam):
        return 'Ecocardiografía: imágenes excluidas por preferencia del usuario.'
    modality = str(exam.get('modality') or '').strip().upper()
    kind = 'radiographs' if modality in ('CR', 'DX', 'DR') else 'ultrasounds' if modality == 'US' else None
    if kind is None:
        return 'Modalidad fuera de radiografías/ecografías.'
    if kind not in normalize_image_types(image_types):
        return 'Tipo de imagen no seleccionado.'
    return None


