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

from clinical_archive import DEFAULT_ROOT
from portable_request import parse

INBOX = DEFAULT_ROOT / '_Solicitudes Nexo'
REQUEST_NAME = re.compile(r'^solicitud-([0-9a-f]{32})\.ready$')


def _write_receipt(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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

    def start(self):
        if not self.root.parent.is_dir():
            return False
        self.root.mkdir(mode=0o700, exist_ok=True)
        (self.root / 'acuses').mkdir(mode=0o700, exist_ok=True)
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return True

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=self.interval + 1)

    def _loop(self):
        while not self.stop.is_set():
            try:
                self.scan_once()
            except OSError:
                pass  # Drive may disappear; retry when it returns.
            self.stop.wait(self.interval)

    def scan_once(self):
        if not self.root.is_dir() or self.root.is_symlink():
            return 0
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
                count += 1
            except OSError:
                continue
        return count
