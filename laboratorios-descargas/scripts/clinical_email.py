"""Gmail plan + import of evidence reviewed by Codex. Never logs in or sends mail."""
import argparse
from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

DEFAULT_ACCOUNT='daniel.opazo@hospitalhangaroa.cl'
ALLOWED_EXTENSIONS={'.pdf','.txt','.eml','.png','.jpg','.jpeg','.docx','.xlsx','.csv'}

def account(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',value):
        raise ValueError('Cuenta de correo inválida.')
    return value.lower()

def plan(rut,period,as_of,email_account=DEFAULT_ACCOUNT,name=None):
    import laboratorios_download as labs
    rut=labs.normalize_ruts([rut])[0];email_account=account(email_account)
    if period not in labs.PERIODS:raise ValueError('Período de correo inválido.')
    end=date.fromisoformat(as_of)
    start=None if period=='latest' else end-timedelta(days=30) if period=='30d' else labs.load_backend('syslab').subtract_months(end,{'3m':3,'6m':6,'1y':12,'2y':24,'5y':60,'10y':120}[period])
    zone=ZoneInfo('Pacific/Easter');before=int(datetime.combine(end+timedelta(days=1),time.min,zone).timestamp())
    after=int(datetime.combine(start,time.min,zone).timestamp())-1 if start else None
    body,dv=rut.split('-');dotted=f'{int(body):,}'.replace(',','.')
    variants=[rut,body+dv,dotted+'-'+dv,body,dotted]
    dates=(f'after:{after} ' if after is not None else '')+f'before:{before}'
    queries=['{'+ ' '.join('"'+v+'"' for v in variants) +'} '+dates+' -in:spam -in:trash -in:drafts']
    if name:
        if not isinstance(name,str) or not re.fullmatch(r"[\wÀ-ÿ' .-]{5,140}",name) or len(name.split())<2:raise ValueError('Nombre verificado inválido.')
        queries.append('"'+name.strip()+'" '+dates+' -in:spam -in:trash -in:drafts')
    return {'rut':rut,'period':period,'as_of':as_of,'account':email_account,'queries':queries,
            'date_basis':'fecha del mensaje; fechas clínicas del contenido se declaran por separado',
            'name_search':'incluida' if name else 'añadir sólo si se obtiene nombre verificado',
            'start':start.isoformat() if start else None,'before_epoch':before,'after_epoch':after}

def pending(rut,period,as_of,email_account,reason=None):
    return {'rut':rut,'source':'email','status':'pending','requires_codex':True,'period':period,
            'account':email_account,'folios':[],'files':[],'file_manifest':[],'pages':0,
            'errors':[reason or 'Correo pendiente de consultar con Gmail en Codex.']}

def load_result(output,rut,period,as_of,email_account=DEFAULT_ACCOUNT):
    """Read only a matching report; recheck scoped files and hashes on every import."""
    output=Path(output).resolve();expected=plan(rut,period,as_of,email_account)
    folder=output/expected['rut']/'email';path=folder/'resultado-correo.json'
    if not path.exists():return pending(rut,period,as_of,email_account)
    if folder.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to((output/expected['rut']).resolve()):raise ValueError('Resultado de correo fuera del trabajo.')
    if path.stat().st_size>16*1024*1024:raise ValueError('Resultado de correo demasiado grande.')
    data=json.loads(path.read_text())
    for key in ('rut','period','as_of','account'):
        if data.get(key)!=expected[key]:raise ValueError('El resultado de correo pertenece a otra solicitud o cuenta.')
    if data.get('version')!=1 or data.get('status') not in ('complete','empty','partial','error'):raise ValueError('Estado de correo inválido.')
    queries=data.get('queries');messages=data.get('messages');files=data.get('files');errors=data.get('pending',[])
    if not all(isinstance(x,list) for x in (queries,messages,files,errors)):raise ValueError('Evidencia de correo incompleta.')
    if any(not isinstance(x,str) or len(x)>1000 for x in errors):raise ValueError('Pendientes de correo inválidos.')
    searched=set();seen=set();included=set();all_reviewed=True
    for q in queries:
        if not isinstance(q,dict) or not isinstance(q.get('query'),str) or not isinstance(q.get('message_ids'),list):raise ValueError('Búsqueda de correo inválida.')
        if any(not isinstance(i,str) or not re.fullmatch(r'[0-9a-f]{8,64}',i) for i in q['message_ids']):raise ValueError('IDs de correo inválidos.')
        searched.update(q['message_ids'])
        all_reviewed=all_reviewed and q.get('complete') is True and not q.get('next_page_token')
    if not any(q['query']==expected['queries'][0] for q in queries):raise ValueError('Falta la búsqueda por variantes del RUT y período solicitado.')
    for msg in messages:
        if not isinstance(msg,dict):raise ValueError('Mensaje inválido.')
        ident=msg.get('id');decision=msg.get('decision')
        if ident not in searched or ident in seen or decision not in ('include','exclude','pending'):raise ValueError('Revisión de mensaje inválida.')
        seen.add(ident)
        if decision=='include':
            try:
                if msg.get('identity_verified') is not True or not isinstance(msg.get('identity_basis'),str) or len(msg['identity_basis'].strip())<10:raise ValueError('Falta revisión de identidad del paciente en el mensaje.')
                instant=datetime.fromisoformat(str(msg.get('received_at','')).replace('Z','+00:00'))
                if instant.tzinfo is None or instant.timestamp()>=expected['before_epoch'] or (expected['after_epoch'] is not None and instant.timestamp()<=expected['after_epoch']):raise ValueError('Mensaje fuera del período solicitado.')
                included.add(ident)
                all_reviewed=all_reviewed and msg.get('attachments_reviewed') is True
            except (ValueError,TypeError):
                errors.append("Mensaje sin identidad o fecha comprobable; revisión pendiente.")
                all_reviewed=False
        elif decision=='exclude':
            if not msg.get('reason'):raise ValueError('Falta motivo de exclusión del mensaje.')
        else:all_reviewed=False
    all_reviewed=all_reviewed and searched==seen and bool(queries)
    manifests=[];with_files=set()
    for item in files:
        try:
            if not isinstance(item,dict) or not isinstance(item.get('path'),str):raise ValueError('Archivo inválido.')
            if item.get('message_id') not in included or item.get('identity_verified') is not True:raise ValueError('Archivo sin paciente verificado.')
            relative=Path(item.get('path',''))
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Ruta de correo inválida.')
            source=folder/relative
            if source.is_symlink() or not source.resolve().is_relative_to(folder.resolve()) or source.suffix.lower() not in ALLOWED_EXTENSIONS:raise ValueError('Archivo de correo no permitido.')
            content=source.read_bytes();checksum=hashlib.sha256(content).hexdigest()
            if not content or checksum!=item.get('sha256'):raise ValueError('Archivo de correo ausente o modificado.')
            if source.suffix.lower()=='.pdf':
                from pypdf import PdfReader
                from io import BytesIO
                reader=PdfReader(BytesIO(content))
                if reader.is_encrypted or not reader.pages or not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:raise ValueError('PDF de correo incompleto.')
            manifests.append({'path':str(source.resolve()),'sha256':checksum,'message_id':item['message_id'],'identity_review':'Codex'})
            with_files.add(item['message_id'])
        except Exception:
            errors.append("Adjunto o mensaje guardado ausente, modificado o sin identidad verificada; conservar los demás archivos válidos.")
            all_reviewed=False
    if period=='latest' and len(included)>1:raise ValueError('Último registro admite sólo el mensaje elegible más reciente.')
    all_reviewed=all_reviewed and included<=with_files and not errors
    if data['status'] in ('complete','empty') and not all_reviewed:
        errors.append('Consulta incompleta: revisar paginación, mensajes y adjuntos pendientes.')
        data['status']='partial'
    if data['status']=='empty' and included:raise ValueError('Correo vacío contiene mensajes incluidos.')
    if data['status']=='complete' and not included:raise ValueError('Sin mensajes incluidos corresponde estado empty.')
    return {'rut':rut,'source':'email','status':data['status'],'account':email_account,'period':period,
            'patient_name':data.get('patient_name') if included and data.get('patient_name_verified') is True else 'Nombre no disponible',
            'folios':[{'id':i} for i in sorted(included)],'completed_folios':sorted(included & with_files),
            'files':[x['path'] for x in manifests],'file_manifest':manifests,'pages':0,'errors':errors,
            'messages_reviewed':len(seen),'date_basis':expected['date_basis'],'requires_codex':not all_reviewed}

def handoff(job):
    period=job.get('source_periods',{}).get('email',job['period']);email_account=job.get('email_account',DEFAULT_ACCOUNT)
    payload={'job_id':job['id'],'account':email_account,'as_of':job['as_of'],'period':period,'ruts':job['ruts'],'output':job['work_output'],'checkpoint':job.get('checkpoint'),'sources':job['selected']}
    return {'prompt':'Usa $flujo-clinico y $correo-clinico para consultar solamente el correo de estos pacientes y período. Verifica primero la cuenta conectada. Conserva las demás fuentes ya obtenidas. Guarda mensajes y adjuntos clínicos verificados, registra resultado-correo.json según la skill y actualiza el resumen obligatorio de fuentes en respuesta y TXT. Al terminar, usa Reanudar pendientes en este trabajo para importar la evidencia, archivar y regenerar el cierre de todas las fuentes; no declares completa la orden antes de comprobarlo. No envíes, modifiques ni borres correos. Contexto:\n'+json.dumps(payload,ensure_ascii=False,indent=2)}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--rut',required=True);p.add_argument('--period',required=True);p.add_argument('--as-of',required=True);p.add_argument('--account',default=DEFAULT_ACCOUNT);p.add_argument('--name');p.add_argument('--verify-output',type=Path);a=p.parse_args()
    try:
        value=load_result(a.verify_output,a.rut,a.period,a.as_of,a.account) if a.verify_output else plan(a.rut,a.period,a.as_of,a.account,a.name)
        print(json.dumps(value,ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError) as error:p.error(str(error))
