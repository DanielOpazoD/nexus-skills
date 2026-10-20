"""Validate a pasted/exported request, without consulting portals or starting jobs."""
import argparse
from datetime import date
import json
from pathlib import Path
import re
import laboratorios_download as labs

PACKET_KEYS={'kind','version','id','target','timeZone','asOf','request'}
from clinical_request import BASE_KEYS as REQUEST_KEYS, CONTENT_KEYS as NEW_KEYS, decode_json, validate_request

def parse(text):
    blocks=re.findall(r'```json\s*\n(.*?)\n```',text,re.S)
    if len(blocks)>1:raise ValueError('Se requiere una sola solicitud.')
    packet=decode_json(blocks[0] if blocks else text)
    if not isinstance(packet,dict) or set(packet)!=PACKET_KEYS:raise ValueError('Estructura de solicitud inválida.')
    if packet['kind']!='hhr-clinical-request' or type(packet['version']) is not int or packet['version'] not in (1,2,3,4):raise ValueError('Versión de solicitud no compatible.')
    if packet['target']!='mac-mini' or packet['timeZone']!='Pacific/Easter':raise ValueError('Destino o zona horaria inválidos.')
    if not isinstance(packet['id'],str) or not re.fullmatch(r'[0-9a-f]{32}',packet['id']):raise ValueError('Identificador inválido.')
    as_of=packet['asOf']
    if not isinstance(as_of,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',as_of):raise ValueError('Fecha de referencia inválida.')
    date.fromisoformat(as_of)
    req=packet['request']
    if not isinstance(req,dict) or set(req)!=(REQUEST_KEYS | NEW_KEYS | {'emailAccount'} if packet['version']>=3 else REQUEST_KEYS | NEW_KEYS if packet['version']==2 else REQUEST_KEYS) or type(req['schema']) is not int or req['schema']!=2:raise ValueError('Opciones de solicitud inválidas.')
    normalized=validate_request(req,version=packet['version'])
    # Las versiones antiguas mantienen su forma, sin introducir nuevos contenidos.
    packet['request']={key:normalized[key] for key in req}
    return packet

def download_args(packet):
    req=packet['request']
    args=['--ruts',*req['ruts'],'--source',req['source'],'--period',req['period'],'--as-of',packet['asOf'],
          '--source-periods',json.dumps(req['sourcePeriods'],sort_keys=True),'--eloisa-scope',req['eloisaScope']]
    if 'mmrad' in req['source'].split(','):
        args+=['--mmrad-mode',req['mmradMode'],'--mmrad-image-types',','.join(req['mmradImageTypes'])]
    if 'email' in req['source'].split(','):args+=['--email-account',req['emailAccount']]
    if req.get('sourceContent'):args+=['--source-content',json.dumps(req['sourceContent'],sort_keys=True)]
    if req['merge']:args.append('--merge')
    if req['patientMerge']:args.append('--patient-merge')
    return args

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('file',type=Path);args=parser.parse_args()
    try:
        packet=parse(args.file.read_text());print(json.dumps({'packet':packet,'download_args':download_args(packet)},ensure_ascii=False,indent=2))
    except (ValueError,TypeError,labs.LabsError) as error:parser.error(str(error))
