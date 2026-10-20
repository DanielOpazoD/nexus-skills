"""Import completed portable requests from a shared Drive folder into the local queue."""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import re
import secrets
import threading
import time
from clinical_presence import heartbeat

from clinical_archive import DEFAULT_ROOT
from portable_request import parse

INBOX = DEFAULT_ROOT / '_Solicitudes Nexo'
REQUEST_NAME = re.compile(r'^solicitud-([0-9a-f]{32})\.ready$')


def _write_receipt(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():raise OSError('Destino enlazado.')
    temporary = path.parent / ('.acuse-' + secrets.token_hex(8) + '.tmp')
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class DriveInbox:
    def __init__(self, launcher, root=INBOX, interval=5):
        self.launcher = launcher
        self.root = Path(root)
        self.interval = interval
        self.stop = threading.Event()
        self.thread = None
        self.instance=secrets.token_hex(8)
        self.last_seen=None
        self.accepting=False
        self._last_status=0

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return True

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=self.interval + 1)
        try:
            if self.root.is_dir() and not self.root.is_symlink():_write_receipt(self.root/'worker.json',heartbeat(self.instance,running=False))
        except OSError:pass

    def health(self):
        return dict(running=bool(self.thread and self.thread.is_alive() and not self.stop.is_set()),
                    drive=self.accepting,lastSeen=self.last_seen,instance=self.instance)

    def _loop(self):
        while not self.stop.is_set():
            try:
                self.scan_once()
            except OSError:
                self.accepting=False  # Drive may disappear; retry when it returns.
            self.stop.wait(self.interval)

    def scan_once(self):
        if self.root.parent.is_dir() and not self.root.is_symlink():
            self.root.mkdir(mode=0o700,exist_ok=True)
        if not self.root.is_dir() or self.root.is_symlink():
            self.accepting=False
            return 0
        self.accepting=True
        self.last_seen=datetime.now(ZoneInfo('Pacific/Easter')).isoformat()
        refresh=time.monotonic()-self._last_status>=15
        if refresh:
            alive=not hasattr(self.launcher,'thread') or bool(self.launcher.thread and self.launcher.thread.is_alive())
            _write_receipt(self.root/'worker.json',heartbeat(self.instance,accepting=alive))
            self._last_status=time.monotonic()
        count = 0
        for ready in sorted(self.root.glob('solicitud-*.ready'))[:1000]:
            match = REQUEST_NAME.fullmatch(ready.name)
            if not match or ready.is_symlink() or not ready.is_file():
                continue
            ident = match.group(1)
            payload = self.root / f'solicitud-{ident}.json'
            if payload.is_symlink() or not payload.is_file():
                continue
            digest = ''
            try:
                digest = ready.read_text(encoding='ascii').strip()
                if not re.fullmatch(r'[0-9a-f]{64}', digest) or ready.stat().st_size > 128:
                    continue
                if payload.stat().st_size > 65536:
                    continue
                raw = payload.read_bytes()
                if sha256(raw).hexdigest() != digest:
                    continue  # Drive may have delivered the marker before the request.
                receipt = self.root / 'acuses' / f'acuse-{ident}.json'
                if receipt.is_file() and not receipt.is_symlink():
                    try:
                        previous = json.loads(receipt.read_text(encoding='utf-8'))
                    except ValueError:
                        previous = {}
                    if previous.get('sha256') == digest:
                        if refresh and previous.get('status')=='imported':self.publish_progress(previous)
                        continue
                packet = parse(raw.decode('utf-8'))
                if packet['id'] != ident:
                    raise ValueError('El identificador del archivo no coincide con la solicitud.')
                result = self.launcher.new_job(dict(packet['request'], requestId=ident, asOf=packet['asOf']))
                response = {'id':ident, 'sha256':digest, 'status':'imported',
                            'jobId':result['id'], 'reused':result['reused']}
            except OSError:
                continue  # Queue/Drive failure is retryable; do not acknowledge it.
            except (UnicodeError, ValueError, TypeError, KeyError) as error:
                response = {'id':ident, 'sha256':digest, 'status':'rejected',
                            'error':str(error)[:200]}
            response['receivedAt'] = datetime.now(ZoneInfo('Pacific/Easter')).isoformat()
            try:
                _write_receipt(self.root / 'acuses' / f'acuse-{ident}.json', response)
                if response['status']=='imported':self.publish_progress(response)
                count += 1
            except OSError:
                continue
        return count

    def publish_progress(self,receipt):
        if not hasattr(self.launcher,'transport_status'):return
        try:
            state=self.launcher.transport_status(receipt['jobId'])
            state.update(version=1,kind='nexo-request-progress',id=receipt['id'],sha256=receipt['sha256'],
                         observedAt=datetime.now(ZoneInfo('Pacific/Easter')).isoformat())
            _write_receipt(self.root/'acuses'/f"progreso-{receipt['id']}.json",state)
        except (OSError,ValueError,KeyError):pass
