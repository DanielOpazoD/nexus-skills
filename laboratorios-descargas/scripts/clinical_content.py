"""Contrato común de contenidos; omitirlo conserva solicitudes antiguas."""
import json
from pathlib import Path
CATALOG=json.loads((Path(__file__).resolve().parents[1]/'assets'/'clinical_catalog.json').read_text())
OPTIONS={source:tuple(x['id'] for x in items) for source,items in CATALOG['content'].items()}
DEFAULTS={source:[x['id'] for x in items if x['default']] for source,items in CATALOG['content'].items()}
CONTENT_LABELS={x['id']:x['label'] for items in CATALOG['content'].values() for x in items}

def normalize_source_content(value,selected,version=4):
    if value is None:return {}
    if not isinstance(value,dict):raise ValueError('Contenido por fuente inválido.')
    result={}
    for source,items in value.items():
        if source not in selected or source not in OPTIONS:raise ValueError('Contenido para una fuente no seleccionada.')
        options=[x['id'] for x in CATALOG['content'][source] if x.get('since',1)<=version]
        if (not isinstance(items,list) or not items or any(not isinstance(x,str) or x not in options for x in items) or len(items)!=len(set(items))):
            raise ValueError('Selecciona al menos un contenido válido para esta versión.')
        result[source]=[x for x in options if x in items]
    return result

def validate_products(content,mmrad_mode):
    if content.get('mmrad') and mmrad_mode=='images':
        raise ValueError('Informes TAC requiere modo reports o both; no sólo imágenes.')
