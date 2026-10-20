"""Contrato de entrada compartido por el formulario local y el paquete portátil.

Validar sin leer credenciales ni crear archivos. La omisión conserva los valores
históricos; un valor explícito inválido nunca se reemplaza por un valor inicial.
"""
import copy
import json
import re
import hashlib
from datetime import date
import clinical_domain as domain
from mmrad_selection import normalize_image_types
from clinical_content import normalize_source_content, validate_products
from clinical_delivery import selection
from clinical_email import account, DEFAULT_ACCOUNT

BASE_KEYS={'schema','ruts','source','period','sourcePeriods','deliveryModel','eloisaScope',
           'mmradMode','mmradImageTypes','merge','patientMerge'}
CONTENT_KEYS={'sourceContent','deliveryInstructions'}
LOCAL_KEYS=BASE_KEYS | CONTENT_KEYS | {'emailAccount','credentials','remember','requestId','asOf'}
CREDENTIAL_SOURCES={'syslab','mmrad','his'}

def unique_object(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('Clave repetida en la solicitud.')
        value[key]=item
    return value

def decode_json(text):
    def invalid_constant(_):raise ValueError('Número JSON inválido.')
    return json.loads(text,object_pairs_hook=unique_object,parse_constant=invalid_constant)

def validate_request(request, *, local=False, version=4):
    try:return _validate_request(request,local=local,version=version)
    except domain.LabsError as error:raise ValueError(str(error)) from None

def _validate_request(request, *, local=False, version=4):
    if not isinstance(request,dict) or set(request)-LOCAL_KEYS:raise ValueError('Opciones de solicitud desconocidas.')
    req=copy.deepcopy(request)
    if 'schema' in req and (type(req['schema']) is not int or req['schema']!=2):raise ValueError('Versión de formulario no compatible.')
    if 'requestId' in req or 'asOf' in req:
        if (not local or not isinstance(req.get('requestId'),str) or
            not re.fullmatch(r'[0-9a-f]{32}',req['requestId']) or
            not isinstance(req.get('asOf'),str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',req['asOf'])):
            raise ValueError('Identificador y fecha de solicitud inválidos.')
        date.fromisoformat(req['asOf'])
    ruts=req.get('ruts')
    if not isinstance(ruts,list) or not 1<=len(ruts)<=200 or any(not isinstance(x,str) for x in ruts):raise ValueError('Ingresa entre 1 y 200 RUT.')
    req['ruts']=domain.normalize_ruts(ruts)
    source=req.get('source')
    if not isinstance(source,str):raise ValueError('Selecciona fuentes.')
    if not local and source in ('all','both'):raise ValueError('Indica fuentes explícitas.')
    # Las pestañas anteriores a schema=2 seleccionaban cinco portales con «all».
    if local and source=='all' and 'schema' not in req:source='syslab,exalab,eloisa,mmrad,his'
    selected=domain.selected_sources(source)
    req['source']=','.join(selected) if local else source
    period=req.get('period')
    if not isinstance(period,str) or period not in domain.PERIODS:raise ValueError('Período inválido.')
    for key in ('sourcePeriods','sourceContent'):
        if key in req and not isinstance(req[key],dict):raise ValueError('Opciones por fuente inválidas.')
    req['sourcePeriods']=domain.normalize_source_periods(req.get('sourcePeriods'),selected,period)
    req['sourceContent']=normalize_source_content(req.get('sourceContent'),selected,version)
    if 'email' in selected and version<3:raise ValueError('Correo requiere versión 3 y cuenta explícita.')
    req['emailAccount']=account(req.get('emailAccount',DEFAULT_ACCOUNT))
    req.setdefault('deliveryModel','documents');req.setdefault('deliveryInstructions','')
    selection(req['deliveryModel'],req['deliveryInstructions'])
    req.setdefault('eloisaScope','medicos');req.setdefault('mmradMode','both')
    if req['eloisaScope'] not in ('medicos','todos') or req['mmradMode'] not in ('reports','images','both'):raise ValueError('Filtros inválidos.')
    validate_products(req['sourceContent'],req['mmradMode'])
    images=req.get('mmradImageTypes',list(normalize_image_types()))
    if (not isinstance(images,list) or any(not isinstance(x,str) or x not in ('radiographs','ultrasounds') for x in images)
        or len(images)!=len(set(images))):raise ValueError('Tipos de imágenes MMRAD inválidos.')
    req['mmradImageTypes']=list(normalize_image_types(images))
    if 'mmrad' in selected and req['mmradMode']!='reports' and not images:raise ValueError('Selecciona imágenes MMRAD.')
    for key in ('merge','patientMerge','remember'):
        if key in req and type(req[key]) is not bool:raise ValueError('Las opciones de casillero deben ser booleanas.')
    req.setdefault('merge',False);req.setdefault('patientMerge',False)
    if 'credentials' in req:
        credentials=req['credentials']
        if not isinstance(credentials,dict) or set(credentials)-CREDENTIAL_SOURCES:raise ValueError('Credenciales inválidas.')
        for pair in credentials.values():
            if (not isinstance(pair,dict) or set(pair)-{'username','password'} or
                any(not isinstance(value,str) or len(value)>1024 for value in pair.values())):raise ValueError('Credenciales inválidas.')
    return req


def request_fingerprint(request):
    """Huella del encargo canónico; nunca incluye credenciales ni preferencias de llavero."""
    payload = {key: value for key, value in request.items()
               if key not in ('credentials', 'remember', 'requestId', 'schema')}
    payload['deliveryInstructions'] = payload.get('deliveryInstructions', '').strip()
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()
