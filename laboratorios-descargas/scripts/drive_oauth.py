"""OAuth de metadatos de Drive: PKCE, consentimiento en Google y llavero local."""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
import secrets
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from clinical_transport import tls_context

SERVICE='CLINICAL_DRIVE_OAUTH'
SCOPE='https://www.googleapis.com/auth/drive.metadata.readonly'
class ConnectionRequired(Exception):pass

def token_request(values):
    request=urllib.request.Request('https://oauth2.googleapis.com/token',
        data=urllib.parse.urlencode(values).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(request,context=tls_context(),timeout=15) as response:return json.load(response)
    except Exception:raise ConnectionRequired('No se pudo renovar la conexión autorizada con Google Drive.') from None

class DriveTokenProvider:
    def __init__(self,keychain,transport=token_request,clock=time.monotonic):
        self.keychain=keychain;self.transport=transport;self.clock=clock;self.cached=None;self.expires=0;self.retry_at=0;self.lock=threading.Lock()
    def __call__(self):
        with self.lock:
            if self.cached and self.clock()<self.expires:return self.cached
            if self.clock()<self.retry_at:raise ConnectionRequired('Conexión de Drive pendiente; vuelve a comprobar más tarde.')
            try:
                raw=self.keychain.get(SERVICE)
                if not raw:
                    token=self.keychain.get('CLINICAL_DRIVE_ACCESS_TOKEN')
                    if token:return token
                    raise ConnectionRequired('Configura OAuth de Drive para comprobar la nube.')
                saved=json.loads(raw)
                values={'grant_type':'refresh_token','refresh_token':saved['refresh_token'],'client_id':saved['client_id']}
                if saved.get('client_secret'):values['client_secret']=saved['client_secret']
                result=self.transport(values)
                if not isinstance(result.get('access_token'),str) or not result['access_token']:raise ValueError()
                self.cached=result['access_token'];self.expires=self.clock()+max(1,int(result.get('expires_in',3600))-60)
                if result.get('refresh_token'):
                    saved['refresh_token']=result['refresh_token'];self.keychain.put(SERVICE,json.dumps(saved))
                return self.cached
            except Exception:
                self.cached=None;self.retry_at=self.clock()+30
                raise ConnectionRequired('Conexión autorizada de Drive pendiente; copias locales conservadas.') from None

def connect(client_file,keychain,open_browser=webbrowser.open,exchange=token_request):
    try:
        with open(client_file) as stream:client=json.load(stream)['installed']
        client_id=client['client_id']
        if not client_id.endswith('.apps.googleusercontent.com'):raise ValueError()
    except Exception:raise ConnectionRequired('Usa el JSON de un cliente OAuth de tipo aplicación de escritorio.') from None
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    response_data={}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            valid=secrets.compare_digest(query.get('state',[''])[0],state)
            if valid:response_data.update({key:values[0] for key,values in query.items()})
            content=('Autorización recibida. Puedes cerrar esta pestaña.' if valid else 'Solicitud no válida.').encode()
            self.send_response(200 if valid else 400);self.send_header('Content-Type','text/plain; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
    with HTTPServer(('127.0.0.1',0),Callback) as server:
        redirect='http://127.0.0.1:'+str(server.server_port)+'/'
        params={'client_id':client_id,'redirect_uri':redirect,'response_type':'code','scope':SCOPE,'state':state,
                'code_challenge':challenge,'code_challenge_method':'S256','access_type':'offline','prompt':'consent'}
        open_browser('https://accounts.google.com/o/oauth2/v2/auth?'+urllib.parse.urlencode(params))
        server.timeout=1;deadline=time.monotonic()+180
        while not response_data and time.monotonic()<deadline:server.handle_request()
    if response_data.get('error') or not response_data.get('code'):raise ConnectionRequired('Autorización no completada; las copias locales se conservan.')
    values={'client_id':client_id,'code':response_data['code'],'code_verifier':verifier,'redirect_uri':redirect,'grant_type':'authorization_code'}
    if client.get('client_secret'):values['client_secret']=client['client_secret']
    tokens=exchange(values)
    if not tokens.get('refresh_token') or SCOPE not in tokens.get('scope',SCOPE).split():raise ConnectionRequired('Google no entregó el acceso de metadatos renovable solicitado.')
    keychain.put(SERVICE,json.dumps({'client_id':client_id,'client_secret':client.get('client_secret'),'refresh_token':tokens['refresh_token']}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--client-json',required=True);args=parser.parse_args()
    from local_launcher import Keychain
    try:
        connect(args.client_json,Keychain());print('Conexión autorizada guardada en el llavero. Vuelve a comprobar el archivo en Drive.')
    except (ConnectionRequired,KeyboardInterrupt):print('Conexión no completada; documentos locales conservados.');raise SystemExit(1)
