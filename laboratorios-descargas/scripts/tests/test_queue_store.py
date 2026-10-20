"""Daños y versiones de la cola, exclusivamente con identidades ficticias."""
import copy
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_regression_workflow import WorkflowTests, wait_for
from clinical_store import QueueStore

class QueueStoreTests(unittest.TestCase):
    setUp = WorkflowTests.setUp
    tearDown = WorkflowTests.tearDown
    queue = WorkflowTests.queue
    request = WorkflowTests.request

    def close(self, queue):
        queue.close()
        self.launchers.remove(queue)

    def test_bad_job_is_quarantined_and_good_job_survives_two_restarts(self):
        q = self.queue()
        bad = q.new_job(self.request('eloisa'))['id']
        good = q.new_job(self.request('rayen'))['id']
        self.close(q)
        data = json.loads(q.store.read_text())
        del data['jobs'][bad]['period']
        q.store.write_text(json.dumps(data))
        original = q.store.read_bytes()
        restored = self.queue()
        self.assertEqual(list(restored.jobs), [good])
        self.assertEqual(len(restored.quarantined), 1)
        self.assertEqual(restored.quarantined[0]['id'], bad)
        backup = Path(restored.quarantined[0]['backup'])
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.close(restored)
        again = self.queue()
        self.assertEqual(list(again.jobs), [good])
        self.assertEqual(len(again.quarantined), 1)
        self.assertEqual(again.status(good)['status'], 'interrupted')

    def test_version_one_migrates_with_exact_backup(self):
        q = self.queue()
        ident = q.new_job(self.request())['id']
        self.close(q)
        data = json.loads(q.store.read_text())
        data['version'] = 1
        data.pop('quarantined')
        q.store.write_text(json.dumps(data))
        original = q.store.read_bytes()
        restored = self.queue()
        self.assertIn(ident, restored.jobs)
        self.assertEqual(json.loads(q.store.read_text())['version'], 2)
        self.assertIn(original, [p.read_bytes() for p in (q.store.parent/'recuperacion').glob('*.json')])

    def test_unknown_root_version_and_malformed_json_preserved_and_lock_released(self):
        q = self.queue()
        self.close(q)
        for raw in (b'{', b'{"version":99,"jobs":{}}', b'{"version":true,"jobs":{}}'):
            q.store.write_bytes(raw)
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, 'cola guardada'):
                    self.queue()
                self.assertEqual(q.store.read_bytes(), raw)

    def test_invalid_scope_path_state_and_types_quarantined_individually(self):
        q = self.queue()
        ident = q.new_job(self.request())['id']
        saved = copy.deepcopy(q.jobs[ident])
        self.close(q)
        changes = ({'work_output':'/private/tmp/outside'}, {'ruts':['22222222-2']},
                   {'status': 'invented'}, {'merge':'false'}, {'as_of':'2026-02-31'},
                   {'pending_sources':['syslab']}, {'source_states':[]})
        # A valid different RUT alone is a new scope; test an invalid checksum instead.
        changes = [dict(change, ruts=['11111111-2']) if 'ruts' in change else change for change in changes]
        for change in changes:
            with self.subTest(change=change):
                q.store.write_text(json.dumps({'version':2,'jobs':{ident:dict(saved,**change)},'quarantined':[]}))
                snapshot = QueueStore(q.store, q.output).load()
                self.assertEqual(snapshot.jobs, {})
                self.assertEqual(len(snapshot.quarantined), 1)

    def test_worker_preparation_failure_does_not_stop_next_job(self):
        q = self.queue()
        bad = q.new_job(self.request('eloisa'))['id']
        good = q.new_job(self.request('rayen'))['id']
        original = q._ready
        def ready(job):
            if job['id'] == bad:
                raise ValueError('synthetic')
            return original(job)
        with patch.object(q, '_ready', side_effect=ready):
            q.thread = threading.Thread(target=q._loop, daemon=True)
            q.thread.start()
            wait_for(lambda: q.jobs[good]['status'] == 'waiting')
            self.assertEqual(q.jobs[bad]['status'], 'attention')
            self.assertTrue(q.thread.is_alive())


del WorkflowTests
if __name__ == '__main__':
    unittest.main()
