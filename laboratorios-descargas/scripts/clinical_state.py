"""Transiciones de trabajos: reglas puras, sin procesos, disco ni autenticación."""
from enum import Enum


class JobStatus(str, Enum):
    QUEUED = 'queued'
    RUNNING = 'running'
    WAITING = 'waiting'
    INTERRUPTED = 'interrupted'
    CANCELLING = 'cancelling'
    CANCELLED = 'cancelled'
    COMPLETE = 'complete'
    ATTENTION = 'attention'


JOB_STATES = frozenset(state.value for state in JobStatus)
SOURCE_STATES = JOB_STATES | {'needs_credentials', 'needs_session', 'needs_codex'}
ACTIVE = ('queued', 'running', 'waiting', 'interrupted', 'cancelling')


def transition(current, event, *, pending=True, cancelled=False, ready=False,
               stopping=False, has_process=False):
    """El reintento es explícito; recibir credenciales nunca revoca una cancelación."""
    current = JobStatus(current).value
    if event == 'cancel':
        return 'cancelling' if has_process else 'cancelled'
    if event == 'retry':
        if current in ('running', 'cancelling'):
            raise ValueError('Espera a que termine la ejecución o cancelación.')
        return 'queued' if pending else 'complete'
    if event == 'credentials':
        return 'queued' if not cancelled and current in ('waiting', 'interrupted') else current
    if event == 'sessions':
        if cancelled or current in ('cancelled', 'cancelling'):
            raise ValueError('Solicitud cancelada; reanuda explícitamente primero.')
        return current if current == 'running' else 'queued'
    if event == 'restart':
        if current in ('running', 'queued', 'interrupted', 'cancelling'):
            return 'cancelled' if cancelled else 'interrupted'
        return current
    if event == 'recovered':
        return 'cancelled' if cancelled else 'interrupted' if pending else 'complete'
    if event == 'review':
        return 'attention' if current == 'complete' and pending else current
    if event == 'failed':
        return 'cancelled' if cancelled else 'attention'
    if event in ('dispatch', 'wait'):
        if current not in ('queued', 'interrupted') or cancelled:
            raise ValueError('Trabajo no disponible para iniciar.')
        return 'running' if event == 'dispatch' else 'waiting'
    if event == 'finish':
        if current not in ('running', 'cancelling'):
            raise ValueError('El trabajo no estaba ejecutándose.')
        if cancelled:
            return 'cancelled'
        if stopping:
            return 'interrupted'
        if not pending:
            return 'complete'
        return 'queued' if ready else 'attention'
    raise ValueError('Transición desconocida.')
