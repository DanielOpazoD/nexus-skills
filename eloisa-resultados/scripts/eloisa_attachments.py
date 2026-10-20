"""Originales PDF vinculados al historial autenticado; firmas SAS sólo en memoria."""
from hashlib import sha256
from io import BytesIO
import json,re,unicodedata
from urllib.parse import urlsplit,urlunsplit,quote,unquote,parse_qs
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from clinical_transport import tls_context,ReliableOpener

MAX_BYTES=32*1024*1024
class AttachmentError(Exception):pass

def identifier(value):
    if not re.fullmatch(r'[1-9][0-9]{0,11}',str(value or '')):raise AttachmentError('Identificador de adjunto/atención inválido.')
    return str(value)

def folded(value):return ''.join(c for c in unicodedata.normalize('NFD',str(value)) if unicodedata.category(c)!='Mn').lower()
def normal_name(value):return re.findall(r'[a-z]+',folded(value))
def rut(value):return re.sub(r'[^0-9K]','',str(value).upper()).lstrip('0')

def enumerate_attachments(row,patient_id,node_id,expected,name,when):
    parent=identifier(row['Id']);patient=identifier(patient_id);node=identifier(node_id)
    values=row.get('ArchivosAdjunto') or []
    if not isinstance(values,list):raise AttachmentError('Listado de adjuntos inválido; requiere revisión.')
    result=[];pending=[];seen=set()
    for a in values:
        try:
            if not isinstance(a,dict):raise AttachmentError('Metadatos del adjunto inválidos.')
            for key,want in [('IdUsuario',patient),('IdNodo',node),('IdAtencion',parent)]:
                if a.get(key) is not None and identifier(a[key])!=want:raise AttachmentError('Adjunto vinculado a otro paciente, nodo o atención.')
            if a.get('RutPaciente') and rut(a['RutPaciente'])!=rut(expected):raise AttachmentError('Adjunto de otro paciente.')
            path=a.get('PathAzure');filename=a.get('NombreArchivo')
            if not isinstance(path,str) or not path or len(path)>4096 or not isinstance(filename,str) or not filename.strip():raise AttachmentError('Adjunto sin ruta o nombre verificable.')
            if path in seen:continue
            seen.add(path)
            if not filename.lower().endswith('.pdf'):raise AttachmentError('Adjunto no PDF: descarga y revisión manual pendientes.')
            key=sha256(path.encode()).hexdigest()
            context={'kind':'attachment','version':1,'patient_id':patient,'node_id':node,'visit_id':parent,'rut':expected,'name':name,'filename':filename,'path_digest':key}
            result.append({'id':parent,'source':'attachment:'+key,'datetime':when,'rut':expected,'name':name,
                           'attachment_path':path,'validation':context,'fingerprint':sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()})
        except AttachmentError as e:pending.append({'episode':parent,'report_type':'attachment','reason':str(e)})
    return result,pending

def signed_url(token,path,patient_id):
    """Only the patient container on the authenticated Azure connection; no bearer."""
    patient=identifier(patient_id)
    if not isinstance(token,dict):raise AttachmentError('Respuesta del gestor documental inválida.')
    connection=token.get('connection');sas=token.get('sas')
    if not isinstance(connection,str) or not isinstance(sas,str):raise AttachmentError('Falta acceso temporal al adjunto.')
    con=urlsplit(connection);item=urlsplit(path)
    if (con.scheme!='https' or not con.hostname or not con.hostname.endswith('.blob.core.windows.net') or
        con.username or con.password or con.port not in (None,443) or con.fragment or
        con.path.strip('/') not in ('',patient)):
        raise AttachmentError('Origen/contenedor del gestor documental no permitido.')
    if any(c in path for c in '\r\n\\') or item.fragment or item.query:raise AttachmentError('Ruta de adjunto inválida.')
    if item.scheme or item.netloc:
        if item.scheme!='https' or item.netloc!=con.netloc or item.path.split('/')[1:2]!=[patient]:raise AttachmentError('El adjunto apunta a otro origen o paciente.')
        blobpath=item.path
    else:
        if path.startswith('/'):raise AttachmentError('Ruta de adjunto inválida.')
        blobpath='/'+patient+'/'+quote(unquote(path),safe='/')
    decoded=unquote(blobpath)
    if any(x in ('.','..','') for x in decoded.split('/')[1:]) or '\\' in decoded or re.search(r'%[0-9a-f]{2}',decoded,re.I):raise AttachmentError('Ruta de adjunto ambigua.')
    sas=sas.lstrip('?');params=parse_qs(sas)
    if not sas or not params.get('sig') or any(c in sas for c in '\r\n#'):raise AttachmentError('Acceso temporal inválido.')
    return urlunsplit(('https',con.netloc,blobpath,sas,''))

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise AttachmentError('Redirección del adjunto no permitida.')

def download(client,exam):
    context=exam['validation']
    token=client.request('/API/api/rayen/Autentificacion/TokenGestorDocumento/{}/{}'.format(context['patient_id'],context['node_id']))
    url=signed_url(token,exam['attachment_path'],context['patient_id'])
    opener=getattr(client,'attachment_opener',None) or ReliableOpener(build_opener(HTTPSHandler(context=tls_context()),NoRedirect()))
    try:
        with opener.open(Request(url,headers={'Accept':'application/pdf'}),timeout=30) as response:
            if response.url!=url:raise AttachmentError('Respuesta de adjunto inesperada.')
            content=response.read(MAX_BYTES+1)
        if len(content)>MAX_BYTES:raise AttachmentError('Adjunto excede 32 MiB; descarga manual pendiente.')
    except HTTPError as e:
        raise AttachmentError('Adjunto no disponible (HTTP {}); se conservan los otros documentos.'.format(e.code)) from None
    except (URLError,TimeoutError):raise AttachmentError('No se pudo descargar el adjunto; actualización pendiente.') from None
    validate(content,exam['rut'],context)
    return content

def validate(content,expected,context):
    from pypdf import PdfReader
    if (not isinstance(context,dict) or context.get('kind')!='attachment' or context.get('version')!=1 or
        rut(context.get('rut'))!=rut(expected) or not context.get('name') or not re.fullmatch(r'[0-9a-f]{64}',str(context.get('path_digest','')))):
        raise AttachmentError('Falta el vínculo verificado del adjunto con el paciente.')
    for key in ('patient_id','node_id','visit_id'):identifier(context.get(key))
    if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:] or len(content)>MAX_BYTES:raise AttachmentError('Adjunto PDF incompleto o inválido.')
    try:
        reader=PdfReader(BytesIO(content),strict=True)
        if reader.is_encrypted or not reader.pages:raise ValueError()
        pages=[page.extract_text() or '' for page in reader.pages]
    except Exception:raise AttachmentError('No se puede leer el PDF adjunto; revisión manual pendiente.') from None
    identities=[];names=normal_name(context['name'])
    for index,text in enumerate(pages):
        text=folded(text)
        header_end=re.search(r'\b(?:anamnesis|conclusiones|descripcion|resultados|antecedentes|observaciones)\s*:',text)
        header=text[:header_end.start()] if header_end else text[:1200]
        for match in re.finditer(r'(?m)^\s*(?:nombre(?:\s+del\s+paciente)?|paciente)\s*:\s*([^\n]+)',header):
            name=re.split(r'\b(?:edad|rut|run|diagnostico|fecha)\s*:',match.group(1))[0]
            if sorted(normal_name(name))!=sorted(names):raise AttachmentError('El nombre del encabezado del adjunto no coincide.')
            block=text[match.start():match.start()+650]
            stop=re.search(r'\b(?:medico|profesional|solicitante|familiar|acompanante|firma|conclusiones|descripcion|mediciones|responsable|tratante|informante|derivador|operador|tecnico|anamnesis|antecedentes|procedimiento|resultados|observaciones)\b',block)
            if stop:block=block[:stop.start()]
            found=re.findall(r'\b(?:rut|run)(?:\s+(?:del\s+)?paciente)?\s*:\s*([\d.]{6,10}\s*-\s*[\dk])\b',block)
            if found and any(rut(x)!=rut(expected) for x in found):raise AttachmentError('El RUT del encabezado del adjunto no coincide.')
            if index==0:identities.extend(found)
        for value in re.findall(r'\bid\s+de\s+atencion\s*:\s*(\d+)',text):
            if value!=context['visit_id']:raise AttachmentError('El adjunto identifica otra atención.')
    if not identities:raise AttachmentError('Identidad del adjunto no verificable en el encabezado; revisión manual pendiente.')
    return reader
