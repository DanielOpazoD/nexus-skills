#!/usr/bin/env python3
"""Servicio de usuario Nexo. No usa sudo ni cambia colas, credenciales o red."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import socket
import subprocess
import sys
import urllib.request
from zoneinfo import ZoneInfo

LABEL='cl.hhr.nexo.worker'
SKILL=Path(__file__).resolve().parents[1]


def runtime(skill=SKILL,home=None):
    home=Path(home or Path.home())
    digest=hashlib.sha256((skill/'requirements.lock').read_bytes()).hexdigest()
    folder=home/'Library/Application Support/HHR Clinical/runtime'/digest[:16]
    if json.loads((folder/'runtime.ok').read_text()).get('lock_sha256')!=digest:
        raise ValueError('El entorno no corresponde al lock; ejecuta setup_runtime.py.')
    python=folder/'bin/python3'
    if not python.is_file() or not os.access(python,os.X_OK):raise ValueError('Falta el intérprete verificado.')
    return python


def configuration(python,skill=SKILL,home=None):
    home=Path(home or Path.home());logs=home/'Library/Logs/Nexo'
    return dict(Label=LABEL,ProgramArguments=[str(python),str(skill/'scripts/local_launcher.py'),'--no-browser'],
                RunAtLoad=True,KeepAlive=True,ThrottleInterval=15,ExitTimeOut=30,ProcessType='Background',
                WorkingDirectory=str(skill),Umask=0o077,
                EnvironmentVariables={'PYTHONUNBUFFERED':'1','PYTHONNOUSERSITE':'1','NEXO_MANAGED':'1'},
                StandardOutPath=str(logs/'servicio.log'),StandardErrorPath=str(logs/'errores.log'))


def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=3) as response:
            data=json.load(response)
        return data if data.get('app')=='laboratorios-descargas' and data.get('version')==1 else None
    except (OSError,ValueError):return None


def port_busy():
    try:
        with socket.create_connection(('127.0.0.1',8765),timeout=1):return True
    except OSError:return False


class Service:
    def __init__(self,home=None,skill=SKILL,runner=subprocess.run):
        self.home=Path(home or Path.home());self.skill=Path(skill).resolve();self.runner=runner
        self.path=self.home/'Library/LaunchAgents'/f'{LABEL}.plist'
        self.domain='gui/'+str(os.getuid());self.target=self.domain+'/'+LABEL

    def command(self,*args):
        return self.runner(['/bin/launchctl',*args],capture_output=True,text=True,timeout=40)

    def loaded(self):return self.command('print',self.target).returncode==0

    def install(self):
        python=runtime(self.skill,self.home)
        payload=plistlib.dumps(configuration(python,self.skill,self.home),sort_keys=True)
        if self.loaded():
            if self.path.read_bytes()!=payload:raise ValueError('Detén el servicio antes de actualizar su configuración.')
            return
        if port_busy():raise ValueError('El puerto del lanzador ya está ocupado; cierra su instancia manual antes de instalar el servicio.')
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        (self.home/'Library/Logs/Nexo').mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.is_symlink():raise ValueError('Archivo de servicio enlazado; no se reemplazó.')
        if self.path.exists() and self.path.read_bytes()!=payload:
            stamp=datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y %H-%M-%S')
            backup=self.home/'Library/Application Support/HHR Clinical/respaldos'/('Servicio '+stamp+'.plist')
            backup.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with backup.open('xb') as stream:stream.write(self.path.read_bytes())
        temporary=self.path.with_suffix('.'+secrets.token_hex(6)+'.tmp')
        descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(descriptor,'wb') as stream:stream.write(payload)
        os.replace(temporary,self.path)
        result=self.command('bootstrap',self.domain,str(self.path))
        if result.returncode:raise ValueError('macOS no pudo iniciar Nexo; configuración conservada para revisar.')

    def stop(self):
        if self.loaded() and self.command('bootout',self.target).returncode:
            raise ValueError('macOS no confirmó la detención del servicio.')

    def status(self):
        return dict(installed=self.path.is_file(),loaded=self.loaded(),health=health())


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['install','status','stop'])
    args=parser.parse_args()
    if sys.platform!='darwin':parser.error('El servicio requiere macOS.')
    try:
        service=Service()
        if args.action=='install':service.install()
        if args.action=='stop':service.stop()
        print(json.dumps(service.status(),ensure_ascii=False));return 0
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
