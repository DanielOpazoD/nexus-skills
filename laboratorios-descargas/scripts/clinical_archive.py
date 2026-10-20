"""Archivo por identidad, copia íntegra y comprobación independiente en Drive."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import os
import re
import tempfile
import unicodedata
import urllib.parse
import urllib.request

DRIVE_ROOT_ID = '1hMcac9_0IxeuB4o28LDm5zYCXYOJs3WT'
DEFAULT_ROOT = Path.home() / 'Library/CloudStorage/GoogleDrive-d.opazo.damiani@gmail.com/Mi unidad/Archivos Mac mini'
FOLDERS = {'syslab':'Laboratorio HHR', 'exalab':'Laboratorio HDS', 'eloisa':'Atenciones Eloisa',
           'email':'Correo', 'his':'Atenciones HIS HHR', 'rayen':'Epicrisis Rayen', 'mmrad':'Imagenologia MMRAD',
           'mmrad_images':'Imagenologia MMRAD/imagenes_pdf'}

class ArchiveError(Exception): pass

def digest(path, kind='sha256'):
    value = hashlib.new(kind)
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): value.update(chunk)
    return value.hexdigest()

def canonical_rut(value):
    raw = re.sub(r'[^0-9Kk]', '', str(value)).upper()
    if not re.fullmatch(r'\d{7,8}[0-9K]', raw): raise ArchiveError('Identidad inválida.')
    body, check = raw[:-1], raw[-1]
    number = 11-sum(int(n)*(2+i%6) for i,n in enumerate(reversed(body)))%11
    if check != ('0' if number == 11 else 'K' if number == 10 else str(number)):
        raise ArchiveError('Dígito de identidad inválido.')
    return body+'-'+check

def clean_name(value):
    text = re.sub(r'[\x00-\x1f/\\:*?"<>|]', ' ', str(value or ''))
    text = re.sub(r'\s+', ' ', text).strip(' .')[:140].rstrip()
    if len(text.split()) < 2 or text.casefold() in ('nombre no disponible', 'sin nombre'):
        raise ArchiveError('Falta nombre de paciente verificado; archivo pendiente.')
    return text

def name_key(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value).casefold() if c.isalnum())

def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix='.estado-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2);f.flush();os.fsync(f.fileno())
        os.replace(temp, path)
    finally: Path(temp).unlink(missing_ok=True)

def copy_version(source, destination, expected=None):
    """Publicar bytes completos, sin sobrescribir versiones y verificando la copia."""
    source = Path(source)
    checksum = digest(source)
    if expected and checksum != expected: raise ArchiveError('El original cambió después de verificarse.')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Reutilizar contenido igual aunque el archivo anterior tenga otro sufijo.
    for prior in destination.parent.glob(destination.stem+'*'+destination.suffix):
        if prior.is_file() and not prior.is_symlink() and digest(prior) == checksum: return prior, checksum
    fd, temporary = tempfile.mkstemp(prefix='.copia-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as out, source.open('rb') as incoming:
            for chunk in iter(lambda:incoming.read(1024*1024), b''): out.write(chunk)
            out.flush();os.fsync(out.fileno())
        if digest(temporary) != checksum: raise ArchiveError('La copia no coincide con el original.')
        target=destination;version=1
        stamp=datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y_%H-%M-%S')
        while True:
            try:
                os.link(temporary, target)
                break
            except FileExistsError:
                if digest(target) == checksum: return target, checksum
                version+=1;target=destination.with_name(destination.stem+' - '+stamp+' - v'+str(version)+destination.suffix)
        if digest(target) != checksum: raise ArchiveError('No se pudo comprobar el archivo publicado.')
        return target, checksum
    finally: Path(temporary).unlink(missing_ok=True)

class DriveVerifier:
    """Solo lectura: confirma ancestros, nombre, tamaño y checksum remotos.

    token_provider devuelve un access token de Drive obtenido por OAuth; nunca se
    guarda aquí. Sin conexión autorizada la sincronización queda pendiente.
    """
    def __init__(self, token_provider=None, transport=None, root_id=DRIVE_ROOT_ID):
        self.token_provider=token_provider or (lambda:None);self.transport=transport;self.root_id=root_id

    def _get(self, path, params):
        if self.transport: return self.transport(path,params)
        token=self.token_provider()
        if not token: raise ArchiveError('Falta conexión autorizada para comprobar Drive en la nube.')
        from clinical_transport import tls_context
        request=urllib.request.Request('https://www.googleapis.com/drive/v3/'+path+'?'+urllib.parse.urlencode(params),
                                       headers={'Authorization':'Bearer '+token})
        try:
            with urllib.request.urlopen(request,context=tls_context(),timeout=15) as r:return json.load(r)
        except Exception: raise ArchiveError('No se pudo comprobar Drive en la nube; conservar copia local.') from None

    def verify(self, path, relative):
        parent=self.root_id;parts=Path(relative).parts
        for i,name in enumerate(parts):
            escaped=name.replace('\\','\\\\').replace("'","\\'")
            q="'{}' in parents and name = '{}' and trashed = false".format(parent,escaped)
            matches=[];page=None
            while True:
                args={'q':q,'fields':'nextPageToken,files(id,name,mimeType,size,md5Checksum,sha256Checksum)', 'pageSize':1000}
                if page:args['pageToken']=page
                data=self._get('files',args);matches.extend(data.get('files',[]));page=data.get('nextPageToken')
                if not page:break
            if len(matches)!=1: return {'status':'pending','reason':'Archivo/carpeta aún no visible o nombre ambiguo en Drive.'}
            remote=matches[0];parent=remote['id']
            if i<len(parts)-1 and remote.get('mimeType')!='application/vnd.google-apps.folder':
                return {'status':'pending','reason':'Ruta remota no coincide.'}
        if str(Path(path).stat().st_size)!=str(remote.get('size')):
            return {'status':'pending','reason':'Tamaño remoto pendiente o diferente.'}
        kind='sha256' if remote.get('sha256Checksum') else 'md5'
        if not remote.get(kind+'Checksum') or digest(path,kind)!=remote[kind+'Checksum']:
            return {'status':'pending','reason':'Contenido remoto pendiente o diferente.'}
        return {'status':'confirmed','file_id':parent,'checked_at':datetime.now(ZoneInfo('Pacific/Easter')).isoformat()}

class PatientArchive:
    def __init__(self, output, root=DEFAULT_ROOT, verifier=None):
        self.output=Path(output).resolve();self.root=Path(root)
        self.verifier=verifier or DriveVerifier()
        self.index_path=self.output/'.archivo-drive'/'identidades.json'
        try:self.index=json.loads(self.index_path.read_text())
        except FileNotFoundError:self.index={}
        except (ValueError,OSError):raise ArchiveError('Índice de identidades ilegible; requiere revisión.') from None

    def _root(self):
        # Nunca fabricar un sustituto local cuando el volumen de Drive falta.
        if not self.root.is_dir():raise ArchiveError('Carpeta de Drive no disponible; archivos conservados localmente.')
        return self.root.resolve()

    def _folder_identity(self, folder):
        identities=set()
        names=['Identidad del paciente.txt','Resumen de antecedentes.txt']
        files=[folder/n for n in names]+list(folder.glob('Estado de descargas - *.txt'))
        for p in files:
            if p.is_symlink() or not p.is_file():continue
            for value in re.findall(r'^\s*(?:RUN|RUT)(?:\s+del paciente)?\s*:\s*([\d.]+\s*-\s*[\dKk])\s*$',p.read_text(errors='replace')[:2000],re.M|re.I):
                try:identities.add(canonical_rut(value))
                except ArchiveError:pass
        return identities

    def folder(self,rut,name):
        root=self._root();patients=root/'Pacientes'
        if patients.is_symlink():raise ArchiveError('Ruta de pacientes no admitida.')
        patients.mkdir(exist_ok=True)
        rut=canonical_rut(rut);name=clean_name(name)
        if rut in self.index:
            folder=patients/self.index[rut]['folder']
            if folder.is_symlink() or folder.parent!=patients or self._folder_identity(folder)!={rut}:
                raise ArchiveError('La identidad de la carpeta registrada necesita revisión.')
            return folder
        for folder in patients.iterdir():
            if not folder.is_dir() or folder.is_symlink():continue
            identity=self._folder_identity(folder)
            if identity=={rut}:
                self.index[rut]={'folder':folder.name};atomic_json(self.index_path,self.index);return folder
        matches=[p for p in patients.iterdir() if name_key(re.sub(r' \(\d+\)$','',p.name))==name_key(name)]
        if any(not p.is_dir() or p.is_symlink() or len(self._folder_identity(p))!=1 for p in matches):
            raise ArchiveError('Hay una carpeta homónima sin identidad comprobable; requiere revisión antes de unir.')
        folder=patients/name;counter=1
        while folder.exists():counter+=1;folder=patients/(name+' ('+str(counter)+')')
        folder.mkdir(mode=0o700)
        (folder/'Identidad del paciente.txt').write_text('Paciente: '+name+'\nRUT: '+rut+'\n')
        self.index[rut]={'folder':folder.name};atomic_json(self.index_path,self.index)
        return folder

    def archive(self, summary):
        result={'status':'complete','files':[],'pending':[]}
        records=summary.get('results',[]);checkpoint=None
        try:
            path=Path(summary.get('checkpoint','')).resolve()
            if path.is_relative_to(self.output) and path.is_file():checkpoint=json.loads(path.read_text())
        except (ValueError,OSError):pass
        by_rut={}
        for row in records:by_rut.setdefault(row['rut'],[]).append(row)
        for rut,rows in by_rut.items():
            try:
                name=next((r.get('patient_name') for r in rows if r.get('patient_name') and r['patient_name']!='Nombre no disponible'),None)
                # No crear expediente vacío si no se obtuvo documento verificable.
                if not any(r.get('files') or r.get('originals') or r.get('completed_folios') for r in rows):continue
                folder=self.folder(rut,name);sources=[]
                for row in rows:
                    source=row['source'];category=FOLDERS.get(source)
                    if not category:continue
                    manifests={m['path']:m for m in row.get('file_manifest',[])}
                    for filename in row.get('files',[]):
                        manifest=manifests.get(filename)
                        if not manifest:
                            result['pending'].append('Falta evidencia de integridad de un archivo publicado.');continue
                        sources.append((Path(filename),folder/'Fuentes primarias'/category/('Documentos adjuntos' if 'Documentos adjuntos' in Path(filename).parts else '')/Path(filename).name,manifest['sha256']))
                    if checkpoint:
                        for key,item in checkpoint.get('reports',{}).get(rut,{}).get(source,{}).items():
                            if not item.get('sha256'):continue
                            original=path.parent/'originales'/rut/source/(key+'.pdf')
                            if source=='mmrad_images':continue
                            if item.get('validation',{}).get('kind')=='attachment' and item['sha256'] in {m['sha256'] for m in manifests.values()}:continue
                            try:
                                from laboratorios_download import validate_pdf
                                content=original.read_bytes()
                                if digest(original)!=item['sha256']:raise ArchiveError('Original modificado.')
                                validate_pdf(content,rut,key.split('-')[0],source,datetime.fromisoformat(item['date']),item.get('validation'))
                            except Exception:
                                result['pending'].append('Original de '+source+' pendiente de verificación de identidad/integridad.');continue
                            date=datetime.fromisoformat(item['date']).strftime('%d-%m-%Y')
                            target=folder/'Fuentes primarias'/category/('Documentos adjuntos' if item.get('validation',{}).get('kind')=='attachment' else 'Originales individuales')/(date+' - '+key+'.pdf')
                            sources.append((original,target,item['sha256']))
                    for original in row.get('original_manifest',[]):
                        if isinstance(original,dict):
                            src=Path(original['path']);sha=original.get('sha256')
                        else:
                            src=Path(original);sha=None
                        # DICOM no se archiva sin huella comprobada por el cliente.
                        if sha:
                            relative=src.resolve().relative_to((self.output/rut/'mmrad'/'originales_dicom').resolve())
                            sources.append((src,folder/'Fuentes primarias'/'Imagenologia MMRAD'/'originales_dicom'/relative,sha))
                for joined in summary.get('patient_pdfs',[]):
                    if joined.get('rut')==rut:
                        for item in joined.get('file_manifest',[]):sources.append((Path(item['path']),folder/Path(item['path']).name,item['sha256']))
                def record_copy(copied,checksum):
                    entry={'path':str(copied),'sha256':checksum,'copy':'verified','sync':'pending'}
                    try:
                        sync=self.verifier.verify(copied,copied.relative_to(self._root()))
                        entry['sync']=sync['status'];entry['remote']=sync
                    except Exception:entry['sync_reason']='Verificación de subida a Drive pendiente.'
                    result['files'].append(entry)

                for original,target,sha in sources:
                    try:
                        if original.is_symlink() or not original.resolve().is_relative_to(self.output):raise ArchiveError('Origen fuera del área de trabajo.')
                        if not target.resolve().is_relative_to(folder.resolve()):raise ArchiveError('Destino fuera del expediente.')
                        record_copy(*copy_version(original,target,sha))
                    except (ArchiveError,OSError,ValueError) as error:result['pending'].append(str(error))
                # Estado humano; no contiene sesiones ni rutas técnicas de reanudación.
                state='Paciente: '+clean_name(name)+'\nRUT: '+rut+'\nFecha: '+datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y')+'\n'
                state+='\n'.join(r['source']+': '+r['status']+(' — '+r['notice'] if r.get('notice') else '') for r in rows)
                state+='\nCopia local y sincronización se comprueban por separado.\n'
                state_source=self.output/'.archivo-drive'/(rut+'-estado.txt');state_source.parent.mkdir(parents=True,exist_ok=True)
                state_source.write_text(state)
                status_path=folder/('Estado de descargas - '+datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y')+'.txt')
                if not status_path.resolve().is_relative_to(folder.resolve()):raise ArchiveError('Destino de estado fuera del expediente.')
                record_copy(*copy_version(state_source,status_path))
                identity=folder/'Identidad del paciente.txt'
                if identity.is_file() and not identity.is_symlink():record_copy(identity,digest(identity))
            except (ArchiveError,OSError,ValueError,KeyError,StopIteration) as error:result['pending'].append(str(error))
        for receipt in summary.get('receipts',[]):
            try:
                source=Path(receipt['path'])
                if source.is_symlink() or not source.resolve().is_relative_to(self.output):raise ArchiveError('Resumen fuera del trabajo.')
                rows=by_rut.get(receipt['rut'],[])
                name=next((r.get('patient_name') for r in rows if r.get('patient_name') and r['patient_name']!='Nombre no disponible' and r.get('file_manifest')),None)
                if name:destination=self.folder(receipt['rut'],name)
                else:
                    matches=[f for f in (self._root()/'Pacientes').glob('*') if f.is_dir() and not f.is_symlink() and self._folder_identity(f)=={receipt['rut']}]
                    destination=matches[0] if len(matches)==1 else self._root()/'Documentos generales'/'Cierres pendientes de identificar'
                target=destination/(source.stem+' - '+receipt['rut']+'.txt')
                if not target.resolve().is_relative_to(self._root()):raise ArchiveError('Destino de resumen inválido.')
                copied,checksum=copy_version(source,target,receipt['sha256'])
                entry={'path':str(copied),'sha256':checksum,'copy':'verified','sync':'pending'}
                try:
                    remote=self.verifier.verify(copied,copied.relative_to(self._root()));entry.update(sync=remote['status'],remote=remote)
                except Exception:entry['sync_reason']='Verificación de subida a Drive pendiente.'
                result['files'].append(entry)
            except (ArchiveError,OSError,ValueError,KeyError) as error:result['pending'].append(str(error))
        result['files']=list({f['path']:f for f in result['files']}.values())
        if result['pending']:result['status']='partial'
        result['sync']='confirmed' if result['files'] and all(f['sync']=='confirmed' for f in result['files']) and not result['pending'] else 'pending'
        return result
