#!/usr/bin/env python3
"""Local, loopback-only launcher for the clinical PDF downloader."""
import argparse
import ctypes
from datetime import datetime
import errno
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import urlopen
import webbrowser


SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS = SCRIPT_DIR.parent / 'assets'
DOWNLOADER = SCRIPT_DIR / 'laboratorios_download.py'
DEFAULT_OUTPUT = Path.home() / 'Documents' / 'Descargas clínicas'
PORT = 8765
DOCUMENTS_EXTENSION = Path.home() / 'Documents' / 'Puente de descargas clínicas'
SERVICES = {'syslab': ('LABS_SYSLAB_USERNAME', 'LABS_SYSLAB_PASSWORD'),
            'mmrad': ('MMRAD_USERNAME', 'MMRAD_PASSWORD'),
            'his': ('LABS_HIS_USERNAME', 'LABS_HIS_PASSWORD')}


def extension_directory():
    if all((DOCUMENTS_EXTENSION / name).is_file() for name in ('manifest.json', 'bridge.js', 'worker.js')):
        return DOCUMENTS_EXTENSION
    return SCRIPT_DIR.parent / 'chrome-bridge'


def load_labs():
    spec = importlib.util.spec_from_file_location('local_labs', DOWNLOADER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Keychain:
    """Use Security.framework directly so passwords never enter process arguments."""
    _interaction_lock = threading.RLock()
    def __init__(self):
        self.api = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.core = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.api.SecKeychainFindGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
            ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p)]
        self.api.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        self.api.SecKeychainAddGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
            ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        self.api.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        self.api.SecKeychainItemModifyAttributesAndData.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_char_p]
        self.api.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        self.api.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.core.CFRelease.argtypes = [ctypes.c_void_p]
        self.api.SecKeychainGetUserInteractionAllowed.argtypes = [ctypes.POINTER(ctypes.c_bool)]
        self.api.SecKeychainGetUserInteractionAllowed.restype = ctypes.c_int32
        self.api.SecKeychainSetUserInteractionAllowed.argtypes = [ctypes.c_bool]
        self.api.SecKeychainSetUserInteractionAllowed.restype = ctypes.c_int32

    def _find(self, service):
        service_bytes, account = service.encode(), b'local-launcher'
        size, data, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
        status = self.api.SecKeychainFindGenericPassword(None, len(service_bytes), service_bytes,
            len(account), account, ctypes.byref(size), ctypes.byref(data), ctypes.byref(item))
        return status, size, data, item

    def get(self, service):
        # El ejecutor no se queda esperando un diálogo del llavero. Si está
        # bloqueado, esa fuente queda pendiente y las demás pueden continuar.
        with self._interaction_lock:
            allowed = ctypes.c_bool()
            if self.api.SecKeychainGetUserInteractionAllowed(ctypes.byref(allowed)):
                raise RuntimeError('El llavero no está disponible sin interacción.')
            if self.api.SecKeychainSetUserInteractionAllowed(False):
                raise RuntimeError('No se pudo consultar el llavero sin interacción.')
            try:
                status, size, data, item = self._find(service)
            finally:
                self.api.SecKeychainSetUserInteractionAllowed(allowed.value)
        try:
            if status == -25300:
                return None
            if status:
                raise RuntimeError('El llavero no permitió leer las credenciales ({}).'.format(status))
            return ctypes.string_at(data, size.value).decode()
        finally:
            if data.value:
                self.api.SecKeychainItemFreeContent(None, data)
            if item.value:
                self.core.CFRelease(item)

    def put(self, service, value):
        with self._interaction_lock:
            return self._put(service, value)

    def _put(self, service, value):
        if not value:
            raise ValueError('No se puede guardar una credencial vacía.')
        encoded, service_bytes, account = value.encode(), service.encode(), b'local-launcher'
        status, _, data, item = self._find(service)
        try:
            if status == -25300:
                result = self.api.SecKeychainAddGenericPassword(None, len(service_bytes), service_bytes,
                    len(account), account, len(encoded), encoded, None)
            elif status == 0:
                result = self.api.SecKeychainItemModifyAttributesAndData(item, None, len(encoded), encoded)
            else:
                result = status
            if result:
                raise RuntimeError('El llavero no permitió guardar las credenciales ({}).'.format(result))
        finally:
            if data.value:
                self.api.SecKeychainItemFreeContent(None, data)
            if item.value:
                self.core.CFRelease(item)


from clinical_delivery import models as delivery_models
from clinical_jobs import PersistentLauncher
from clinical_archive import DEFAULT_ROOT

class Launcher(PersistentLauncher):
    def __init__(self, output=DEFAULT_OUTPUT, python=None, keychain=None, downloader=DOWNLOADER,
                 archive_root=DEFAULT_ROOT, verifier=None, autostart=True, **kwargs):
        super().__init__(output, python or os.environ.get('LABS_PYTHON') or sys.executable,
                         keychain or Keychain(), downloader, load_labs(), SERVICES,
                         archive_root, verifier, autostart, **kwargs)


class Handler(BaseHTTPRequestHandler):
    server_version = 'LaboratoriosLocal/2.0'

    def log_message(self, *_):
        pass

    @property
    def launcher(self):
        return self.server.launcher

    def _headers(self, status, content_type, size):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(size))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()

    def send_json(self, status, body):
        content = json.dumps(body, ensure_ascii=False).encode()
        self._headers(status, 'application/json; charset=utf-8', len(content))
        self.wfile.write(content)

    def _allowed(self):
        port = self.server.server_port
        return self.headers.get('Host') in ('127.0.0.1:{}'.format(port), 'localhost:{}'.format(port))

    def do_GET(self):
        if not self._allowed():
            self.send_json(403, {'error':'Host no permitido.'})
            return
        path = urlsplit(self.path)
        if path.path in ('/', '/app.js', '/app.css', '/form.js', '/catalog.js', '/packet.js', '/agenda-core.js', '/agenda-ui.js', '/nexo.png'):
            asset = {'/':'local_app.html','/app.js':'local_app.js','/app.css':'local_app.css','/form.js':'request_form.js','/catalog.js':'clinical_catalog.js','/packet.js':'request_packet.js','/agenda-core.js':'agenda_core.js','/agenda-ui.js':'agenda_ui.js','/nexo.png':'brand/nexo-128.png'}[path.path]
            content = (ASSETS / asset).read_bytes()
            mime = 'text/html' if asset.endswith('.html') else 'text/javascript' if asset.endswith('.js') else 'image/png' if asset.endswith('.png') else 'text/css'
            self._headers(200, mime + '; charset=utf-8', len(content))
            self.wfile.write(content)
            return
        query = parse_qs(path.query)
        if path.path == '/api/config':
            self.send_json(200, {'app':'laboratorios-descargas',
                                 'extension_dir':str(extension_directory()),
                                 'output_dir':str(self.launcher.output),'delivery_models':delivery_models()})
            return
        if path.path == '/api/credentials/status':
            self.send_json(200, self.launcher.credential_status())
            return
        if path.path == '/api/jobs':
            self.send_json(200, {'jobs':self.launcher.history(), 'quarantined':self.launcher.quarantined})
            return
        if path.path == '/api/status':
            try:
                self.send_json(200, self.launcher.status(query.get('id',[''])[0]))
            except ValueError as error:
                self.send_json(404, {'error':str(error)})
            return
        if path.path == '/api/delivery':
            try:
                self.send_json(200, self.launcher.delivery_request(query.get('id',[''])[0]))
            except ValueError as error:
                self.send_json(404, {'error':str(error)})
            return
        if path.path == '/api/mail':
            try:self.send_json(200,self.launcher.mail_request(query.get('id',[''])[0]))
            except ValueError as error:self.send_json(404,{'error':str(error)})
            return
        if path.path in ('/api/file','/api/receipt','/api/artifact'):
            try:
                ident, index = query.get('id',[''])[0], int(query.get('index',[''])[0])
                with self.launcher.lock:
                    if index < 0:raise ValueError()
                    if path.path=='/api/artifact':
                        from clinical_artifacts import states
                        row=states(self.launcher.jobs[ident])[index]
                        if row['status'] not in ('verified','archived'):raise ValueError()
                        artifact=row['artifact'];item={'path':artifact['path'],'sha256':artifact['path_sha256']}
                    else:item = self.launcher.jobs[ident]['receipts' if path.path=='/api/receipt' else 'files'][index]
                if query.get('sha256', [''])[0] != item.get('sha256'):raise ValueError()
                file = Path(item['path']).resolve()
                from clinical_email import ALLOWED_EXTENSIONS
                allowed={'.txt'} if path.path=='/api/receipt' else ALLOWED_EXTENSIONS
                if not file.is_relative_to(self.launcher.output) or file.suffix.lower() not in allowed:
                    raise ValueError()
                content = file.read_bytes()
                if hashlib.sha256(content).hexdigest() != item.get('sha256'):raise ValueError()
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf' if file.suffix.lower()=='.pdf' else 'text/plain; charset=utf-8' if file.suffix.lower()=='.txt' else 'application/octet-stream')
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(file.name))
                self.send_header('Content-Length', str(len(content)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(content)
            except (ValueError, KeyError, IndexError, OSError):
                self.send_json(404, {'error':'Archivo no disponible.'})
            return
        self.send_json(404, {'error':'Ruta no disponible.'})

    def do_POST(self):
        if not self._allowed():
            self.send_json(403, {'error':'Host no permitido.'})
            return
        path = urlsplit(self.path).path
        origin = self.headers.get('Origin','')
        if path != '/api/sessions' and origin not in (
                'http://127.0.0.1:{}'.format(self.server.server_port),
                'http://localhost:{}'.format(self.server.server_port)):
            self.send_json(403, {'error':'Origen no permitido.'})
            return
        if path not in ('/api/jobs','/api/import','/api/sessions','/api/cancel','/api/credentials','/api/retry','/api/archive','/api/delivery/register'):
            self.send_json(404, {'error':'Ruta no disponible.'})
            return
        try:
            size = int(self.headers.get('Content-Length','0'))
            limit=2*1024*1024 if path=='/api/delivery/register' else 65536
            if not 0 < size <= limit:
                raise ValueError('Solicitud demasiado grande.')
            from clinical_request import decode_json
            body = decode_json(self.rfile.read(size))
            if not isinstance(body, dict):raise ValueError('Solicitud inválida.')
            if path == '/api/import':
                from portable_request import parse
                packet = parse(json.dumps(body))
                result = self.launcher.new_job(dict(packet['request'], requestId=packet['id'], asOf=packet['asOf']))
            elif path == '/api/jobs':
                result = self.launcher.new_job(body)
            elif path == '/api/credentials':
                result = self.launcher.store_credentials(body)
            elif path == '/api/sessions':
                result = self.launcher.provide_sessions(body)
            elif path == '/api/retry':
                result = self.launcher.retry(body.get('id'))
            elif path == '/api/archive':
                result = self.launcher.verify_archive(body.get('id'))
            elif path == '/api/delivery/register':
                result = self.launcher.register_delivery(body)
            else:
                self.launcher.cancel_waiting(body.get('id'))
                result = {'ok':True}
            self.send_json(200, result)
        except (ValueError, TypeError, KeyError, RuntimeError, self.launcher.labs.LabsError) as error:
            self.send_json(400, {'error':str(error)})


def serve(output=DEFAULT_OUTPUT, python=None, open_browser=True):
    try:
        server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        try:
            with urlopen('http://127.0.0.1:{}/api/config'.format(PORT), timeout=2) as response:
                config = json.load(response)
            if config.get('app') != 'laboratorios-descargas' and Path(config['extension_dir']).name != 'chrome-bridge':
                raise ValueError('Hay otro servidor en el puerto local.')
        except (OSError, ValueError, KeyError):
            raise RuntimeError('El puerto local {} ya está ocupado por otra aplicación.'.format(PORT)) from None
        if open_browser:
            open_local_page()
        print('Descargas clínicas ya estaba abierto en http://127.0.0.1:{}/'.format(PORT))
        return
    server.launcher = Launcher(output, python)
    server.daemon_threads = True
    from drive_inbox import DriveInbox
    inbox = DriveInbox(server.launcher)
    try:
        inbox_active = inbox.start()
    except OSError:
        inbox_active = False
    if open_browser:
        open_local_page()
    print('Descargas clínicas: http://127.0.0.1:{}/'.format(PORT), flush=True)
    print('Los PDF se guardan en: {}'.format(server.launcher.output), flush=True)
    if inbox_active:
        print('Bandeja Drive activa: {}'.format(inbox.root), flush=True)
    try:
        server.serve_forever()
    finally:
        inbox.close()
        server.launcher.close()
        server.server_close()


def open_local_page():
    url = 'http://127.0.0.1:{}/'.format(PORT)
    if sys.platform == 'darwin':
        try:
            profile_file = Path.home() / 'Library/Application Support/Google/Chrome/Local State'
            profiles = json.loads(profile_file.read_text())['profile']['info_cache']
            profile = next(name for name, data in profiles.items()
                           if data.get('user_name') == 'd.opazo.damiani@gmail.com')
            subprocess.Popen(['open', '-a', 'Google Chrome', '--args',
                              '--profile-directory=' + profile, url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except (OSError, KeyError, ValueError, StopIteration):
            pass
    webbrowser.open(url)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--python')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    serve(args.output, args.python, not args.no_browser)
