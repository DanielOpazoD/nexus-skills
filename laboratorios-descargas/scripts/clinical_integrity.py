"""Una misma comprobación de integridad para estado, reanudación y cierre."""
from pathlib import Path
import hashlib

DONE=('complete','empty','no_reports','no_images')
INTEGRITY_ERROR='Archivo ausente o modificado; requiere revisión.'

def verified_files(row,output,cache=None):
    root=Path(output).resolve();rut=row['rut'];valid=[];broken=False
    manifests={};conflicts=set()
    items=row.get('file_manifest',[])
    if not isinstance(items,list):items=[];broken=True
    for item in items:
        if (not isinstance(item,dict) or not isinstance(item.get('path'),str) or
            not isinstance(item.get('sha256'),str) or len(item['sha256'])!=64 or
            type(item.get('pages',0)) is not int or item.get('pages',0)<0):
            broken=True;continue
        filename=item['path']
        if filename in manifests and manifests[filename]!=item:conflicts.add(filename);broken=True
        else:manifests[filename]=item
    filenames=row.get('files',[])
    if not isinstance(filenames,list):filenames=[];broken=True
    seen=set()
    for filename in filenames:
        if not isinstance(filename,str) or filename in conflicts:broken=True;continue
        if filename in seen:continue
        seen.add(filename)
        try:
            original=Path(filename);path=original.resolve();item=manifests[filename]
            patient_path=path.is_relative_to(root/rut)
            # Originales recuperados: carpeta del mismo paciente/fuente y evidencia
            # de validación de identidad, además del hash. Nunca cualquier .avance.
            parts=path.relative_to(root).parts
            recovered=(len(parts)==6 and parts[0]=='.avance' and parts[2:5]==('originales',rut,row.get('source')) and item.get('validation_version')==2)
            if original.is_symlink() or not (patient_path or recovered):raise ValueError()
            stat=path.stat();key=(item['sha256'],stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
            cached=cache.get(str(path)) if cache is not None else None
            ok=cached[1] if cached and cached[0]==key else hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
            if cache is not None:cache[str(path)]=(key,ok)
            if not ok:raise ValueError()
            valid.append(dict(item,path=str(path)))
        except (OSError,ValueError,KeyError,TypeError):broken=True
    return valid,broken

def audit_result(row,output,cache=None):
    result=dict(row);valid,broken=verified_files(row,output,cache)
    if not isinstance(result.get('errors',[]),list) or any(not isinstance(x,str) for x in result.get('errors',[])):
        result['errors']=[];broken=True
    if not isinstance(result.get('status'),str) or not isinstance(result.get('folios',[]),list):
        result['status']='partial';result['folios']=[];broken=True
    if 'attachment_count' in result and (type(result['attachment_count']) is not int or result['attachment_count']<0):
        result['attachment_count']=0;broken=True
    missing=row.get('status')=='complete' and bool(row.get('folios')) and not valid
    result.update(files=[item['path'] for item in valid],file_manifest=valid,pages=sum(item.get('pages',0) for item in valid))
    if broken or missing:
        result.update(status='partial',freshness='update_pending')
        result['errors']=list(dict.fromkeys([*result.get('errors',[]),INTEGRITY_ERROR]))
    return result

def completed(row,list_only=False):
    accepted=DONE+('listed',) if list_only else DONE
    return row.get('status') in accepted and not row.get('errors') and not (row.get('status')=='complete' and row.get('folios') and not row.get('files'))


def audit_results(rows, output, expected, cache=None):
    """Una fila por paciente/producto; errores locales no invalidan otras fuentes."""
    groups={key:[] for key in expected}
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict):continue
        rut,source=row.get('rut'),row.get('source')
        if not isinstance(rut,str) or (source is not None and not isinstance(source,str)):continue
        if (rut,source) in groups:groups[(rut,source)].append(row)
    results=[]
    for (rut,source),group in groups.items():
        row={'rut':rut,'status':'pending','folios':[],'files':[],'file_manifest':[],'errors':[]}
        if source is not None:row['source']=source
        if group:
            audited=[audit_result(item,output,cache) for item in group]
            row=audited[0]
            if len(group)>1:
                manifests={item['path']:item for part in audited for item in part['file_manifest']}
                row=dict(row,status='partial',files=list(manifests),file_manifest=list(manifests.values()),
                         errors=list(dict.fromkeys([error for part in audited for error in part.get('errors',[])]+
                                                   ['Resultados duplicados para el mismo paciente y fuente; revisión pendiente.'])))
                row['pages']=sum(item.get('pages',0) for item in manifests.values())
        results.append(row)
    return results


def result_keys(ruts, sources, mmrad_mode='reports'):
    kinds=[source for source in sources if source!='mmrad' or mmrad_mode!='images']
    if 'mmrad' in sources and mmrad_mode!='reports':kinds.append('mmrad_images')
    return [(rut,kind) for rut in ruts for kind in kinds]
