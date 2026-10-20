"""Idempotencia durable sin consultar portales ni usar sesiones reales."""
import copy,json,sys,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_regression_workflow import WorkflowTests

class RequestIdentityTests(unittest.TestCase):
    setUp=WorkflowTests.setUp
    tearDown=WorkflowTests.tearDown
    queue=WorkflowTests.queue
    def request(self, **extra):
        value=dict(schema=2,ruts=['11111111-1'],source='eloisa',period='6m',requestId='a'*32,asOf='2026-10-19')
        value.update(extra)
        return value
    def test_same_id_returns_existing_without_credentials_and_survives_restart(self):
        q=self.queue();first=q.new_job(self.request())
        with patch.object(q,'credentials',side_effect=AssertionError('No debe leer credenciales')):
            again=q.new_job(self.request(credentials={'syslab':{'username':'unused','password':'secret'}}))
        self.assertEqual(first['id'],again['id']);self.assertTrue(again['reused']);self.assertEqual(len(q.jobs),1)
        q.close();self.launchers.remove(q);restored=self.queue();again=restored.new_job(self.request())
        self.assertEqual(first['id'],again['id']);self.assertEqual(restored.jobs[first['id']]['as_of'],'2026-10-19')
        self.assertNotIn('secret',restored.store.read_text())
    def test_concurrent_replays_create_one_job(self):
        q=self.queue()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:q.new_job(self.request()),range(16)))
        self.assertEqual(len({r['id'] for r in results}),1)
        self.assertEqual(sum(not r['reused'] for r in results),1)
    def test_same_id_changed_scope_rejected_new_id_allowed(self):
        q=self.queue();first=q.new_job(self.request())
        for change in ({'period':'10y'},{'ruts':['22222222-2']},{'sourceContent':{'eloisa':['attachments']}},{'asOf':'2026-10-20'}):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'otro contenido'):
                q.new_job(self.request(**change))
        second=q.new_job(self.request(requestId='b'*32))
        self.assertNotEqual(first['id'],second['id']);self.assertEqual(len(q.jobs),2)
    def test_cancelled_order_replay_does_not_restart_or_request_sessions(self):
        q=self.queue();created=q.new_job(self.request());q.cancel(created['id'])
        again=q.new_job(self.request());self.assertTrue(again['reused']);self.assertEqual(again['need'],[])
        self.assertEqual(q.jobs[created['id']]['status'],'cancelled')
    def test_persistence_failure_does_not_leave_runnable_job(self):
        q=self.queue()
        with patch.object(q.repository,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):q.new_job(self.request())
        self.assertEqual(q.jobs,{});self.assertEqual(q.payloads,{})
        self.assertFalse(q.new_job(self.request())['reused'])
    def test_damaged_request_id_reserved_after_quarantine(self):
        q=self.queue();created=q.new_job(self.request());q.close();self.launchers.remove(q)
        data=json.loads(q.store.read_text());del data['jobs'][created['id']]['period'];q.store.write_text(json.dumps(data))
        restored=self.queue()
        with self.assertRaisesRegex(ValueError,'apartado'):restored.new_job(self.request())
    def test_persisted_request_changed_is_quarantined(self):
        q=self.queue();created=q.new_job(self.request());q.close();self.launchers.remove(q)
        data=json.loads(q.store.read_text());data['jobs'][created['id']]['period']='10y';q.store.write_text(json.dumps(data))
        restored=self.queue();self.assertEqual(restored.jobs,{});self.assertEqual(len(restored.quarantined),1)
    def test_http_portable_import_round_trip_preserves_id_and_date(self):
        import io
        from types import SimpleNamespace
        from local_launcher import Handler
        from test_request_contract import RequestContractTests
        q=self.queue();packet=RequestContractTests().packet({})
        packet['asOf']='2025-06-30'
        def post(body):
            raw=json.dumps(body).encode();handler=Handler.__new__(Handler)
            handler.server=SimpleNamespace(server_port=8765,launcher=q)
            handler.path='/api/import';handler.rfile=io.BytesIO(raw)
            handler.headers={'Host':'127.0.0.1:8765','Origin':'http://127.0.0.1:8765','Content-Length':str(len(raw))}
            response=[];handler.send_json=lambda status,data:response.append((status,data))
            handler.do_POST();return response[0]
        status,first=post(packet);self.assertEqual(status,200)
        self.assertEqual(q.jobs[first['id']]['as_of'],'2025-06-30')
        self.assertEqual(post(packet)[1]['id'],first['id'])
        packet['request']['period']='10y'
        self.assertEqual(post(packet)[0],400);self.assertEqual(len(q.jobs),1)

    def test_legacy_requests_without_id_still_allow_explicit_new_orders(self):
        q=self.queue();req=self.request();req.pop('requestId');req.pop('asOf')
        self.assertNotEqual(q.new_job(req)['id'],q.new_job(req)['id'])

del WorkflowTests
if __name__=='__main__':unittest.main()
