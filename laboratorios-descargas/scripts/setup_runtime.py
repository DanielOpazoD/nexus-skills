#!/usr/bin/env python3
"""Instalar y verificar un entorno aislado con versiones y hashes fijados."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import venv

SKILL = Path(__file__).resolve().parents[1]
LOCK = SKILL / 'requirements.lock'


def default_runtime():
    digest = hashlib.sha256(LOCK.read_bytes()).hexdigest()[:16]
    return Path.home() / 'Library/Application Support/HHR Clinical/runtime' / digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--venv', type=Path, default=default_runtime())
    parser.add_argument('--wheelhouse', type=Path, help='Instalar sin red desde wheels descargados y verificados.')
    args = parser.parse_args(argv)
    if sys.version_info[:2] != (3, 12) or sys.platform != 'darwin':
        parser.error('Este paquete requiere CPython 3.12 para macOS.')
    if platform.machine() not in ('arm64', 'x86_64'):
        parser.error('Arquitectura de macOS no compatible con este lock.')
    target = args.venv.expanduser().absolute()
    if target.is_symlink() or (target.exists() and not (target / 'pyvenv.cfg').is_file()):
        parser.error('El destino ya existe y no es un entorno virtual administrable; elige una carpeta nueva.')
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = target / 'runtime.ok'
    marker.unlink(missing_ok=True)
    try:
        venv.EnvBuilder(with_pip=True).create(target)
        python = target / 'bin/python3'
        command = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                   '--require-hashes', '--only-binary=:all:', '-r', str(LOCK)]
        if args.wheelhouse:
            command += ['--no-index', '--find-links', str(args.wheelhouse.expanduser().resolve())]
        subprocess.run(command, check=True)
        subprocess.run([str(python), str(SKILL / 'scripts/check_foundations.py')], check=True)
        temporary = marker.with_suffix('.tmp')
        temporary.write_text(json.dumps({'lock_sha256': hashlib.sha256(LOCK.read_bytes()).hexdigest(),
                                         'python': platform.python_version(), 'architecture': platform.machine()}))
        os.replace(temporary, marker)
        print(f'Entorno instalado y verificado: {python}')
        return 0
    except (OSError, subprocess.SubprocessError) as error:
        print(f'Instalación incompleta ({type(error).__name__}); no se habilitó este entorno.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
