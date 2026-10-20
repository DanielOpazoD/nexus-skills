"""Invariantes de estado y fronteras entre contrato, recuperación y ejecución."""
import copy
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clinical_state import JOB_STATES, transition
from clinical_recovery import recover, reconcile_sources
from clinical_domain import normalize_ruts
from test_regression_workflow import WorkflowTests
from test_access import Fake, RUT, DAY
import laboratorios_download as labs


class StateBoundaryTests(unittest.TestCase):
    setUp = WorkflowTests.setUp
    tearDown = WorkflowTests.tearDown
    queue = WorkflowTests.queue
    request = WorkflowTests.request

    def test_input_contract_does_not_import_download_engine(self):
        code = "import clinical_request,sys; clinical_request.validate_request(dict(ruts=['11111111-1'],source='eloisa',period='6m'),local=True); assert 'laboratorios_download' not in sys.modules; assert not any(m.startswith('labs_') for m in sys.modules)"
        subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], check=True)

    def test_rut_contract_matches_existing_client(self):
        backend = labs.load_backend('exalab')
        for body in ('11111111', '22222222', '12345678', '10000000', '99999999', '1234567'):
            for digit in '0123456789K':
                value = body + '-' + digit
                try:
                    old = backend.normalize_rut(value)
                except backend.ExalabError:
                    with self.assertRaises(labs.LabsError):
                        normalize_ruts([value])
                else:
                    self.assertEqual(normalize_ruts([value, value]), [old])
        self.assertEqual(normalize_ruts(['11.111.111-1']), [RUT])

    def test_cancel_requires_explicit_retry_and_blocks_early_dispatch(self):
        for state in JOB_STATES:
            stopped = transition(state, 'cancel')
            self.assertEqual(stopped, 'cancelled')
            self.assertEqual(transition(stopped, 'credentials', cancelled=True), stopped)
            self.assertEqual(transition(stopped, 'restart', cancelled=True), stopped)
            with self.assertRaises(ValueError):
                transition(stopped, 'dispatch', cancelled=True)
            with self.assertRaises(ValueError):
                transition(stopped, 'sessions', cancelled=True)
            self.assertEqual(transition(stopped, 'retry'), 'queued')
        with self.assertRaises(ValueError):
            transition('cancelling', 'retry')
        with self.assertRaises(ValueError):
            transition('complete', 'dispatch')

    def test_finish_respects_partial_results_shutdown_and_sessions(self):
        self.assertEqual(transition('running', 'finish', pending=False), 'complete')
        self.assertEqual(transition('running', 'finish', pending=True), 'attention')
        self.assertEqual(transition('running', 'finish', pending=True, ready=True), 'queued')
        self.assertEqual(transition('running', 'finish', stopping=True, ready=True), 'interrupted')
        self.assertEqual(transition('cancelling', 'finish', cancelled=True, ready=True), 'cancelled')

    def test_recovery_returns_snapshot_without_mutating_job(self):
        q = self.queue()
        job = q.jobs[q.new_job(self.request('eloisa,rayen'))['id']]
        job['as_of'] = DAY.isoformat()
        result = labs.run_batch([RUT], 'eloisa,rayen', '6m', DAY, Path(job['work_output']), {'eloisa': Fake()})
        job['checkpoint'] = result['checkpoint']
        before = copy.deepcopy(job)
        snapshot = recover(job, labs)
        self.assertEqual(job, before)
        self.assertTrue(snapshot.files)
        self.assertFalse(snapshot.failed)
        updated = dict(job, summary=snapshot.summary['results'])
        progress = reconcile_sources(updated)
        self.assertEqual(progress.pending, ['rayen'])
        self.assertEqual(progress.states['eloisa'], 'complete')

    def test_cancel_between_dispatch_and_process_creation_stays_cancelling(self):
        q = self.queue()
        job = q.jobs[q.new_job(self.request('eloisa'))['id']]
        job['status'] = 'running'
        with patch.object(q, '_archive'):
            q.cancel(job['id'])
        self.assertEqual(job['status'], 'cancelling')
        with self.assertRaises(ValueError):
            q.retry(job['id'])
        self.assertTrue(job['cancel_requested'])


del WorkflowTests
if __name__ == '__main__':
    unittest.main()
