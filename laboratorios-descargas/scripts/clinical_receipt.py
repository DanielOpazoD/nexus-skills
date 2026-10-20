"""Cierre obligatorio de una orden: cobertura comprobable, respuesta y TXT."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import json
import re

ORDER=('syslab','exalab','eloisa','his','rayen','mmrad','email')
LABELS={'syslab':'Syslab','exalab':'Exalab','eloisa':'Eloísa Ambulatorio','his':'HIS','rayen':'Eloísa Hospitalizados','mmrad':'MMRAD','email':'Correo institucional'}
from clinical_integrity import audit_results, result_keys, completed

def clean(value):
    value=re.sub(r'(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)',r'\3-\2-\1',str(value))
    return ' '.join(value.split())[:600]

def window(period,as_of):
    import laboratorios_download as labs
    end=date.fromisoformat(as_of)
    if period=='latest':return 'último registro hasta '+end.strftime('%d-%m-%Y')
    start=end-timedelta(days=30) if period=='30d' else labs.load_backend('syslab').subtract_months(end,{'3m':3,'6m':6,'1y':12,'2y':24,'5y':60,'10y':120}[period])
    return start.strftime('%d-%m-%Y')+' → '+end.strftime('%d-%m-%Y')

def text(summary,rut,output):
    import laboratorios_download as labs
    selected=labs.selected_sources(summary['source'])
    rows=audit_results(summary.get('results'),output,result_keys([rut],selected,summary.get('mmrad_mode','reports')))
    name=next((r.get('patient_name') for r in rows if r.get('patient_name') and r['patient_name']!='Nombre no disponible' and r.get('file_manifest')),None)
    lines=['Resumen de fuentes','Paciente: '+clean(name or 'nombre pendiente de verificar'),'RUT: '+rut,
           'Fecha de referencia: '+date.fromisoformat(summary['as_of']).strftime('%d-%m-%Y')]
    if summary.get('order_status')=='cancelled':lines.append('Orden cancelada; se conserva la documentación verificada.')
    lines.append('')
    for number,source in enumerate(ORDER,1):
        prefix=str(number)+'. '+LABELS[source]
        if source not in selected:
            lines.append('[ ] '+prefix+' — no solicitada');continue
        kinds=['mmrad','mmrad_images'] if source=='mmrad' and summary.get('mmrad_mode','reports')=='both' else ['mmrad_images'] if source=='mmrad' and summary.get('mmrad_mode')=='images' else [source]
        found=[r for r in rows if r['source'] in kinds]
        valid={p for row in found for p in row.get('files',[])}
        complete={r['source'] for r in found if completed(r,summary.get('list_only',False))}==set(kinds)
        notes=list(dict.fromkeys(clean(e) for r in found for e in r.get('errors',[]) if e))
        if any(r.get('notice') for r in found):notes+=list(dict.fromkeys(clean(r['notice']) for r in found if r.get('notice')))
        if complete:
            mark='X';status='listado completado; sin descarga solicitada' if summary.get('list_only') else 'consulta completada' if valid else 'sin registros' if all(r['status']=='empty' for r in found) else 'consulta completada; sin archivos disponibles'
        elif valid or any(r['status'] in ('partial','listed','no_reports','no_images','complete','empty') for r in found):mark='~';status='parcial'
        else:mark=' ';status='pendiente'
        own=summary.get('source_periods',{}).get(source,summary['period'])
        line='['+mark+'] '+prefix+' — '+status+' · '+str(len(valid))+' archivo(s) verificado(s) · '+window(own,summary['as_of'])
        content=summary.get('source_content',{}).get(source,[])
        from clinical_content import CONTENT_LABELS
        names=CONTENT_LABELS
        if content:line+=' · '+', '.join(names.get(item,item) for item in content)
        if source=='eloisa' and 'attachments' in content:line+=' · '+str(sum(r.get('attachment_count',0) for r in found))+' adjunto(s) PDF localizado(s)'
        if source=='mmrad':line+=' · '+{'reports':'informes','images':'imágenes','both':'informes e imágenes'}.get(summary.get('mmrad_mode','reports'),'productos seleccionados')
        if source=='email':line+=' · '+summary.get('email_account','daniel.opazo@hospitalhangaroa.cl')+' · fecha del mensaje'
        if notes:line+=' · '+ '; '.join(notes)
        elif not complete:line+=' · '+('Consulta pendiente en Codex.' if source=='email' else 'Acceso o revisión pendiente.')
        lines.append(line)
    lines+=['','[X] consulta completada · [~] parcial · [ ] pendiente/no solicitada',
            'Copia en Drive y sincronización: comprobar por separado; este cierre no acredita la subida.']
    return '\n'.join(lines)+'\n'

def write(summary,output,ruts=None):
    import laboratorios_download as labs
    ruts=ruts or summary.get('ruts') or list(dict.fromkeys(r['rut'] for r in summary.get('results',[])))
    stamp=datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y');receipts=[]
    for rut in labs.normalize_ruts(ruts):
        value=text(summary,rut,output);content=value.encode()
        path=labs.save_content(Path(output)/rut,'Resumen de fuentes - '+stamp,content,'.txt')
        receipts.append({'rut':rut,'path':str(path),'sha256':hashlib.sha256(content).hexdigest(),'text':value})
    summary['receipts']=receipts
    return receipts

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('summary',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    data=json.loads(a.summary.read_text())
    for receipt in write(data,a.output):print(receipt['text']+'TXT: '+receipt['path'])
