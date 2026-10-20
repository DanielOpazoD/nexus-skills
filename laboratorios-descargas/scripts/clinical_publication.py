"""Vista vigente por producto, sin deducir versiones por nombres de archivos."""
import fcntl
import json
from datetime import datetime
from pathlib import Path

from clinical_archive import (ArchiveError, CONTROL_FOLDER, READING_FOLDER, atomic_json,
                              copy_version, digest, publish_without_replace)


def safe_path(folder, relative):
    path = folder/relative
    if (folder.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(folder.resolve())
        or any(p.is_symlink() for p in path.parents if p != folder.parent and p.is_relative_to(folder))):
        raise ArchiveError('Ruta de publicación no admitida.')
    return path


def publish(source, folder, sha256, slot, job, *, revision=None):
    """Solo productos registrados; archivos anteriores desconocidos no se mueven.

    Primero registrar la nueva copia; después retirar versiones sustituidas.
    Si se interrumpe la retirada, el siguiente intento la completa.
    """
    if not slot or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in slot):
        raise ArchiveError('Producto de publicación inválido.')
    folder = Path(folder)
    control = safe_path(folder, CONTROL_FOLDER)
    control.mkdir(exist_ok=True)
    ledger = safe_path(folder, CONTROL_FOLDER+'/Entregas vigentes.json')
    lock = safe_path(folder, CONTROL_FOLDER+'/.entregas.lock')
    with lock.open('a+b') as owner:
        fcntl.flock(owner.fileno(), fcntl.LOCK_EX)
        try:
            data = json.loads(ledger.read_text())
        except FileNotFoundError:
            data = {'version':1, 'products':{}}
        except (ValueError, OSError):
            raise ArchiveError('Índice de entregas ilegible; no se reemplazó.') from None
        if data.get('version') != 1 or not isinstance(data.get('products'), dict):
            raise ArchiveError('Índice de entregas incompatible; no se reemplazó.')
        product = data['products'].setdefault(slot, {'current':None, 'history':[]})
        current = product['current']
        rank = [job['as_of'], datetime.fromisoformat(job['started_at']).timestamp(), job['id']]
        historical = bool(current and current['rank'] > rank)
        base = CONTROL_FOLDER+'/Archivo anterior/Entregas/'+slot if historical else READING_FOLDER
        target = safe_path(folder, base+'/'+Path(source).name)
        if current and not historical:
            prior = safe_path(folder, current['path'])
            if not prior.is_file() or digest(prior) != current['sha256']:
                raise ArchiveError('La entrega vigente fue editada o no está disponible; conservar edición y revisar antes de sustituirla.')
        copied, checksum = copy_version(source, target, sha256)
        entry = dict(path=str(copied.relative_to(folder)), sha256=checksum, rank=rank,
                     job=job['id'], revision=revision, freshness='current')
        if historical:
            if entry not in product['history']:product['history'].append(entry)
        elif current != entry:
            if current and current['path'] != entry['path']:product['history'].append(current)
            product['current'] = entry
        atomic_json(ledger, data)
        pending = []
        for old in product['history']:
            if not old['path'].startswith(READING_FOLDER+'/'):
                continue
            prior = safe_path(folder, old['path'])
            destination = safe_path(folder, CONTROL_FOLDER+'/Archivo anterior/Entregas/'+slot+'/'+prior.name)
            if product['current'] and old['path'] == product['current']['path']:
                continue
            if not prior.is_file():
                # Recuperar rename completado justo antes de persistir el índice.
                matches=[p for p in destination.parent.glob(prior.stem+'*'+prior.suffix)
                         if p.is_file() and not p.is_symlink() and digest(p)==old['sha256']]
                if len(matches)==1:
                    old['path']=str(matches[0].relative_to(folder));atomic_json(ledger,data);continue
            if not prior.is_file() or digest(prior) != old['sha256']:
                pending.append('Versión anterior modificada/ausente; retirada pendiente.');continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            version = 1
            while True:
                try:
                    publish_without_replace(prior, destination)
                    break
                except FileExistsError:
                    version += 1
                    destination = destination.with_name(prior.stem+' - v'+str(version)+prior.suffix)
            if digest(destination) != old['sha256']:
                raise ArchiveError('No se pudo verificar la versión retirada.')
            old['path'] = str(destination.relative_to(folder))
            # Persistir después de cada traslado para limitar la recuperación.
            atomic_json(ledger, data)
        atomic_json(ledger, data)
        return copied, checksum, pending


def mark_freshness(folder,slot,job_id,status):
    """Exportar vigencia mínima para lectores del Air; no incluye prosa ni sesiones."""
    if status not in ('stale','modified'):return
    folder=Path(folder)
    ledger=safe_path(folder,CONTROL_FOLDER+'/Entregas vigentes.json')
    if not ledger.is_file():return
    lock=safe_path(folder,CONTROL_FOLDER+'/.entregas.lock')
    with lock.open('a+b') as owner:
        fcntl.flock(owner.fileno(),fcntl.LOCK_EX)
        data=json.loads(ledger.read_text())
        current=data.get('products',{}).get(slot,{}).get('current')
        if current and current.get('job')==job_id and current.get('freshness')!=status:
            current['freshness']=status;atomic_json(ledger,data)
