"""Reutilización entre pedidos: contenido estructurado o validación HTTP 304.

Siempre se consulta el listado autenticado y se valida nuevamente el PDF.
No ofrece documentos de la caché cuando falla la fuente.
"""
import hashlib
from http.client import HTTPMessage
import io
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError

MAXIMUM=32*1024*1024

def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

class Cache:
    def __init__(self,root):self.root=Path(root);self.metrics=dict(reused=0,revalidated=0,downloaded=0)

    def path(self,key,suffix):
        if self.root.is_symlink():raise ValueError('Caché enlazada.')
        return self.root/(key+suffix)

    def load(self,key,validate):
        try:
            metadata=self.path(key,'.json')
            if metadata.is_symlink() or metadata.stat().st_size>4096:return None
            record=json.loads(metadata.read_text())
            sha=record['sha256']
            if record.get('version')!=1 or not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):return None
            path=self.path(sha,'.pdf')
            if path.is_symlink() or path.stat().st_size>MAXIMUM:return None
            content=path.read_bytes()
            if hashlib.sha256(content).hexdigest()!=sha:return None
            validate(content)
            return content,record
        except Exception:return None  # Caché inválida: obtener y validar nuevamente, nunca bloquear la fuente.

    def atomic(self,path,content):
        fd,temporary=tempfile.mkstemp(prefix='.cache-',dir=self.root)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        finally:Path(temporary).unlink(missing_ok=True)

    def save(self,key,content,headers=None):
        if len(content)>MAXIMUM:return
        try:
            self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
            sha=hashlib.sha256(content).hexdigest();self.atomic(self.path(sha,'.pdf'),content)
            record=dict(version=1,sha256=sha)
            for name in ('etag','last-modified'):
                value=(headers or {}).get(name)
                if isinstance(value,str) and 0<len(value)<1024 and not any(c in value for c in '\r\n'):record[name]=value
            self.atomic(self.path(key,'.json'),json.dumps(record,sort_keys=True).encode())
        except (OSError,ValueError):pass  # Una optimización fallida no pierde la descarga.

    def structured(self,context,download,validate):
        key=fingerprint(context);old=self.load(key,validate)
        if old:self.metrics['reused']+=1;return old[0]
        content=download();validate(content);self.save(key,content);self.metrics['downloaded']+=1;return content

    def http(self,client,context,download,validate):
        prior=client.opener;wrapper=Conditional(prior,self,context,validate);client.opener=wrapper
        try:
            content=download();validate(content)
            if wrapper.received:
                key,headers=wrapper.received
                if 'no-store' in headers.get('cache-control','').lower() or headers.get('vary'):
                    try:self.atomic(self.path(key,'.json'),b'{"version":1,"blocked":true}')
                    except (OSError,ValueError):pass
                elif any(headers.get(field) for field in ('etag','last-modified')):self.save(key,content,headers)
            self.metrics['revalidated' if wrapper.revalidated else 'downloaded']+=1
            return content
        finally:client.opener=prior


class CachedResponse(io.BytesIO):
    def __init__(self,content,url,headers=None):
        super().__init__(content);self.url=url;self.headers=HTTPMessage();self.status=200
        for key,value in (headers or {}).items():self.headers[key]=value
    def geturl(self):return self.url
    def getcode(self):return 200
    def info(self):return self.headers


class Conditional:
    def __init__(self,opener,cache,context,validate):
        self.opener=opener;self.cache=cache;self.context=context;self.validate=validate;self.received=None;self.revalidated=False

    def open(self,request,timeout=None):
        if not getattr(request,'nexo_pdf',False) or request.get_method()!='GET':return self.opener.open(request,timeout=timeout)
        key=fingerprint([self.context,hashlib.sha256(request.full_url.encode()).hexdigest()])
        old=self.cache.load(key,self.validate);conditional=False
        if old:
            for field,header in [('etag','If-None-Match'),('last-modified','If-Modified-Since')]:
                value=old[1].get(field)
                if isinstance(value,str) and 0<len(value)<1024 and not any(c in value for c in '\r\n'):
                    request.add_header(header,value);conditional=True
        try:response=self.opener.open(request,timeout=timeout)
        except HTTPError as error:
            if error.code!=304:raise
            same_url=error.geturl()==request.full_url;headers=dict(error.headers or {});error.close()
            if not old or not conditional or not same_url:raise ValueError('304 sin copia vigente verificable.') from None
            self.received=(key,{str(k).lower():v for k,v in headers.items()})
            self.revalidated=True;return CachedResponse(old[0],request.full_url,headers)
        self.received=(key,{str(k).lower():v for k,v in response.headers.items()})
        return response
