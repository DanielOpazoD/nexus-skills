#!/usr/bin/env python3
"""Verificación reproducible con datos ficticios; no consulta portales ni llavero."""
import argparse
import ast
from datetime import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent
ROOT = SKILL.parent
SKILLS = ('flujo-clinico', 'laboratorios-descargas', 'syslab-resultados', 'exalab-resultados',
          'eloisa-resultados', 'mmrad-resultados', 'his-resultados', 'rayen-epicrisis',
          'correo-clinico', 'eloisa-archivo-drive', 'reporte-clinico', 'formularios-clinicos',
          'telereumatologia', 'resumen-antecedentes')


def locked_versions(path=SKILL / 'requirements.lock'):
    return dict(re.findall(r'^([A-Za-z0-9_-]+)==([^\s\\]+)', Path(path).read_text(), re.M))


def environment():
    if sys.version_info[:2] != (3, 12):
        raise ValueError('Usa Python 3.12 para este entorno reproducible.')
    for name, expected in locked_versions().items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            raise ValueError(f'Falta {name}; ejecuta setup_runtime.py.') from None
        if actual != expected:
            raise ValueError(f'{name}: esperado {expected}, encontrado {actual}; ejecuta setup_runtime.py.')
    node = shutil.which('node')
    if not node:
        raise ValueError('Falta Node.js 22 para comprobar los formularios y puentes.')
    version = subprocess.check_output([node, '--version'], text=True).strip()
    if not version.startswith('v22.'):
        raise ValueError('La verificación reproducible requiere Node.js 22.')
    return node


def documents():
    import yaml
    count = 0
    for name in SKILLS:
        folder = ROOT / name
        path = folder / 'SKILL.md'
        content = path.read_text()
        match = re.match(r'^---\n(.*?)\n---', content, re.S)
        data = yaml.safe_load(match[1]) if match else None
        if not isinstance(data, dict) or data.get('name') != name or not isinstance(data.get('description'), str):
            raise ValueError(f'{name}: frontmatter inválido.')
        description = data['description'].strip()
        if not description or len(description) > 1024 or '<' in description or '>' in description:
            raise ValueError(f'{name}: descripción inválida.')
        for link in re.findall(r'\]\(([^)]+)\)', content):
            link = link.strip('<>').split('#')[0]
            if not link or ':' in link or link.startswith('/'):
                continue
            if not (folder / link).exists():
                raise ValueError(f'{name}: referencia inexistente {link}.')
        metadata = folder / 'agents' / 'openai.yaml'
        if metadata.exists():
            if not isinstance(yaml.safe_load(metadata.read_text()), dict):
                raise ValueError(f'{name}: metadatos de interfaz inválidos.')
        for script in (folder / 'scripts').rglob('*.py'):
            ast.parse(script.read_text(), filename=str(script))
            count += 1
    return count


def generated_assets():
    from build_portable_form import build
    names = ('clinical_catalog.js', 'local_app.html', 'solicitud-examenes.html', 'solicitud-portatil.html')
    original = SKILL / 'assets'
    with tempfile.TemporaryDirectory(prefix='hhr-assets-') as temporary:
        copied = Path(temporary) / 'assets'
        shutil.copytree(original, copied)
        build(copied)
        changed = [name for name in names if (copied / name).read_bytes() != (original / name).read_bytes()]
        generated = copied.parent / 'chrome-bridge'
        for path in generated.rglob('*'):
            if path.is_file():
                relative = path.relative_to(generated)
                installed = SKILL / 'chrome-bridge' / relative
                if not installed.exists() or installed.read_bytes() != path.read_bytes():
                    changed.append('chrome-bridge/' + str(relative))
    if changed:
        raise ValueError('Formularios desactualizados: ejecuta build_portable_form.py (' + ', '.join(changed) + ').')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment-only', action='store_true')
    parser.add_argument('--log-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        node = environment()
        if args.environment_only:
            print('Python, Node y dependencias fijadas: correctos.')
            return 0
        stamp = datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y')
        logs = args.log_dir or Path(tempfile.mkdtemp(prefix=f'hhr-verificacion-{stamp}-'))
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        scripts = documents()
        generated_assets()
        print(f'Skills: {len(SKILLS)}; scripts: {scripts}; formularios generados: correctos.', flush=True)
        commands = [
            ('dependencias', [sys.executable, '-m', 'pip', 'check']),
            ('motor', [sys.executable, '-m', 'unittest', 'discover', '-s', str(SCRIPTS / 'tests')]),
            ('hospitalizados', [sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT / 'rayen-epicrisis/scripts/tests')]),
            ('formularios', [node, '--test', *map(str, sorted((SCRIPTS / 'tests').glob('*.test.mjs'))),
                             *map(str, sorted((ROOT / 'rayen-epicrisis/scripts/tests').glob('*.test.mjs')))]),
        ]
        env = dict(os.environ, PYTHONPYCACHEPREFIX=str(logs / 'cache'), PYTHONNOUSERSITE='1')
        for label, command in commands:
            log = logs / f'{label} - {stamp}.txt'
            with log.open('w') as output:
                try:
                    result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT,
                                            cwd=ROOT, env=env, timeout=120)
                except subprocess.TimeoutExpired:
                    raise ValueError(f'{label}: tiempo excedido; detalle en {log}') from None
            if result.returncode:
                raise ValueError(f'{label}: falló; detalle en {log}')
            content = log.read_text()
            count = re.search(r'Ran (\d+) tests', content) or re.search(r'# tests (\d+)', content)
            print(f'{label}: correcto' + (f' ({count[1]} pruebas)' if count else ''), flush=True)
        print(f'Verificación completa. Registros: {logs}')
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('Verificación incompleta: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
