"""Presencia y avance sin pacientes, rutas, sesiones ni texto clínico."""
from datetime import datetime, timezone, timedelta

HEARTBEAT_TTL = 90


def heartbeat(instance, *, running=True, accepting=True, clock=None):
    now = clock or datetime.now(timezone.utc)
    return dict(version=1, kind='nexo-worker-status', role='mac-mini', instance=instance,
                status='ready' if running and accepting else 'attention' if running else 'stopped',
                observedAt=now.isoformat(), expiresAt=(now+timedelta(seconds=HEARTBEAT_TTL if running else 0)).isoformat())


def project(job, products):
    """Una fuente completa no acredita redacción ni copia/sincronización."""
    completed=sum(job['source_states'].get(source)=='complete' for source in job['selected'])
    pending=len(job['selected'])-completed
    baseline=[row for row in products if row['kind']=='antecedentes']
    ready=sum(row['status']=='archived' for row in baseline)
    total=len(job['ruts'])
    files=len(job.get('files',[]))
    status=('cancelled' if job.get('cancel_requested') else
            'downloading' if job['status'] in ('running','cancelling') else
            'summary_ready' if ready==total and total else
            'documents_ready' if not pending else
            'documents_partial' if files else
            'attention' if job['status'] in ('attention','failed','waiting') else 'received')
    archive=job.get('archive',{})
    return dict(status=status, needsAttention=bool(pending and job['status'] not in ('queued','running')),
                sourceCounts=dict(completed=completed,pending=pending,total=len(job['selected'])),
                fileCount=files,summary=dict(ready=ready,total=total),
                archive=dict(copy=archive.get('status') if archive.get('status') in ('complete','partial') else 'pending',
                             sync='confirmed' if archive.get('sync')=='confirmed' else 'pending'))
