#!/usr/bin/env python3
"""Empaquetar únicamente la extensión versionada en HEAD; nunca sesiones o archivos de trabajo."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'laboratorios-descargas/chrome-bridge/'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def package(output):
    commit = git('rev-parse', 'HEAD').decode().strip()
    entries = git('ls-tree', '-rz', commit, '--', PREFIX).split(b'\0')
    files = {}
    for entry in entries:
        if not entry:
            continue
        metadata, raw_path = entry.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        path = raw_path.decode()
        if mode not in ('100644', '100755') or kind != 'blob' or not path.startswith(PREFIX):
            raise ValueError('Entrada de extensión no admitida: ' + path)
        relative = path[len(PREFIX):]
        if '..' in PurePosixPath(relative).parts:
            raise ValueError('Ruta no admitida.')
        files[relative] = git('cat-file', 'blob', oid)
    manifest = json.loads(files['manifest.json'])
    if manifest['manifest_version'] != 3:
        raise ValueError('Se esperaba Manifest V3.')
    required = [manifest['background']['service_worker'], 'request/index.html']
    if manifest.get('side_panel'):required.append(manifest['side_panel']['default_path'])
    required += list(manifest.get('icons', {}).values())
    required += list(manifest.get('action', {}).get('default_icon', {}).values())
    for content in manifest.get('content_scripts', []):
        required += content.get('js', []) + content.get('css', [])
    if any(name not in files for name in required):
        raise ValueError('Falta un archivo referenciado por la extensión.')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            archive.writestr(item, data)
    data = buffer.getvalue()
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as target:
        target.write(data)
    digest = hashlib.sha256(data).hexdigest()
    print(f'Extensión {manifest["version"]}: {len(files)} archivos; commit {commit}')
    print(f'ZIP: {output}')
    print(f'SHA256: {digest}')
    return digest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    package(args.output)
