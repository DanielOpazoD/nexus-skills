"""Biblioteca de TXT clínicos. Solo lectura; nunca consulta portales ni interpreta."""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from clinical_archive import ArchiveError, canonical_rut, digest, name_key
from clinical_domain import CATALOG

RULES=CATALOG['library']


def read_text(path, root, maximum=RULES['maxTextBytes']):
    if (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
        or any(p.is_symlink() for p in path.parents if p.is_relative_to(root))):
        raise ValueError('Ruta no admitida.')
    with path.open('rb') as stream:raw=stream.read(maximum+1)
    if len(raw)>maximum:raise ValueError('Documento demasiado grande.')
    text=raw.decode('utf-8-sig').replace('\r\n','\n')
    if '\x00' in text:raise ValueError('Texto no admitido.')
    return text,hashlib.sha256(raw).hexdigest()


def identity(text):
    header=text[:2000]
    match=re.search(r'^Paciente:\s*([^\n]+)\n(?:RUT|RUN):\s*([\d.]+\s*-\s*[\dKk])\s*$',header,re.M|re.I)
    if not match or len(re.findall(r'^Paciente:',header,re.M|re.I))!=1:
        raise ValueError('Identidad del encabezado pendiente.')
    return match[1].strip(),canonical_rut(match[2])


def same_name(one,two):
    return sorted(name_key(x) for x in one.split())==sorted(name_key(x) for x in two.split())


def document_identity(text,expected_name):
    try:return identity(text)
    except ValueError:
        # Formato histórico conocido: nombre completo en primera línea, RUT en segunda.
        lines=text.splitlines()
        if len(lines)<2 or not same_name(lines[0].strip(),expected_name):raise ValueError('Nombre del encabezado no coincide.') from None
        match=re.fullmatch(r'(?:RUT|RUN)\s*:?\s*([\d.]+\s*-\s*[\dKk])',lines[1].strip(),re.I)
        if not match:raise ValueError('RUT del encabezado ausente.') from None
        return lines[0].strip(),canonical_rut(match[1])


def filename_date(name):
    for pattern in RULES['filenamePatterns']:
        match=re.fullmatch(pattern,name,re.I)
        if match:
            day=match[1] if match.lastindex else None
            if day:datetime.strptime(day,'%d-%m-%Y')
            return day or ''
    return None


def folder_identity(folder):
    """Archivo actual o controles antiguos explícitos; nunca inferir por el nombre."""
    for base in (folder/RULES['controlFolder'],folder):
        path=base/RULES['identityFilename']
        if path.exists():return identity(read_text(path,folder,4096)[0])
    found=[]
    for base in (folder/RULES['controlFolder'],folder):
        if base.is_symlink():raise ValueError('Control enlazado.')
        for pattern in ('Estado de descargas - *.txt','Resumen de fuentes - *.txt'):
            for path in sorted(base.glob(pattern))[:100]:
                try:found.append(identity(read_text(path,folder,16384)[0]))
                except (ValueError,OSError,ArchiveError):continue
    if not found or any(rut!=found[0][1] or not same_name(name,found[0][0]) for name,rut in found):
        raise ValueError('Identidad del expediente ambigua o ausente.')
    return found[0]


class ClinicalLibrary:
    def __init__(self,root):self.root=Path(root)

    def _scan(self):
        patients=self.root/RULES['patientsFolder']
        if not self.root.is_dir() or self.root.is_symlink() or not patients.is_dir() or patients.is_symlink():
            return [],{},0,False
        rows=[];references={};issues=0
        for folder in sorted(patients.iterdir()):
            if not folder.is_dir() or folder.is_symlink() or folder.name.startswith('.'):continue
            if len(rows)>=RULES['maxPatients']:issues+=1;break
            try:
                control=folder/RULES['controlFolder']
                name,rut=folder_identity(folder)
                display=re.sub(r' \(\d+\)$','',folder.name)
                if not same_name(display,name):raise ValueError('Nombre de carpeta contradictorio.')
                current=None
                manifest=control/RULES['manifestFilename']
                if manifest.exists():
                    data=json.loads(read_text(manifest,folder,1024*1024)[0])
                    if data.get('version')!=1:raise ValueError('Índice no compatible.')
                    current=data.get('products',{}).get('delivery-antecedentes',{}).get('current')
                documents=[];reading=folder/RULES['readingFolder']
                if reading.is_dir() and not reading.is_symlink():
                    for path in sorted(reading.iterdir()):
                        if not path.is_file() or path.is_symlink():continue
                        try:
                            day=filename_date(path.name)
                            if day is None:continue
                            if len(documents)>=RULES['maxDocuments']:issues+=1;break
                            text,sha=read_text(path,folder)
                            doc_name,doc_rut=document_identity(text,name)
                            if doc_rut!=rut or not same_name(doc_name,name):raise ValueError('Identidad contradictoria.')
                            if current and (current.get('path')!=str(path.relative_to(folder)) or current.get('sha256')!=sha):continue
                            status=current.get('freshness','current') if current else 'existing'
                            ident=hashlib.sha256((rut+'\0'+str(path.relative_to(self.root))+'\0'+sha).encode()).hexdigest()
                            reference_date=re.search(r'^Fecha de referencia:\s*(\d{2}-\d{2}-\d{4})\s*$',text[:2000],re.M)
                            if reference_date:datetime.strptime(reference_date[1],'%d-%m-%Y')
                            documents.append(dict(id=ident,date=day,referenceDate=reference_date[1] if reference_date else '',status=status,sha256=sha))
                            references[ident]=(path,sha,folder,rut,name,status)
                        except (ValueError,OSError,ArchiveError,UnicodeError):issues+=1
                if current and not documents:issues+=1
                rows.append(dict(id=hashlib.sha256((rut+'\0'+folder.name).encode()).hexdigest(),name=name,rut=rut,documents=documents))
            except (ValueError,OSError,ArchiveError,UnicodeError,AttributeError,TypeError):issues+=1
        # No escoger arbitrariamente entre dos carpetas con el mismo RUT.
        counts={}
        for row in rows:counts[row['rut']]=counts.get(row['rut'],0)+1
        duplicates={rut for rut,count in counts.items() if count>1}
        issues+=len(duplicates)
        rows=[row for row in rows if row['rut'] not in duplicates]
        valid_ids={d['id'] for row in rows for d in row['documents']}
        return rows,{k:v for k,v in references.items() if k in valid_ids},issues,True

    def list(self):
        rows,_,issues,available=self._scan()
        return dict(version=1,available=available,patients=rows,issues=issues)

    def read(self,ident,sha256):
        if not isinstance(ident,str) or not re.fullmatch(r'[0-9a-f]{64}',ident) or not isinstance(sha256,str):
            raise ValueError('Documento no válido.')
        _,references,_,_=self._scan()
        ref=references.get(ident)
        if not ref or ref[1]!=sha256:raise ValueError('El resumen cambió o no está disponible. Actualiza la lista.')
        path,expected,folder,rut,name,status=ref
        text,sha=read_text(path,folder)
        doc_name,doc_rut=document_identity(text,name)
        if sha!=expected or doc_rut!=rut or not same_name(doc_name,name):raise ValueError('El documento cambió durante la lectura.')
        return dict(id=ident,sha256=sha,text=text,status=status,rut=rut,name=name)
