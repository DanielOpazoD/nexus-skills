"""Servicio simulado y transporte ficticio; nunca instala un LaunchAgent en CI."""
import hashlib,json,os,plistlib,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from clinical_presence import heartbeat,project
from drive_inbox import DriveInbox
import service_manager as service
import test_drive_inbox as fixtures


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.skill=self.home/'skill con espacios'
        self.skill.mkdir();(self.skill/'requirements.lock').write_text('lock ficticio')
        digest=hashlib.sha256((self.skill/'requirements.lock').read_bytes()).hexdigest()
        self.runtime=self.home/'Library/Application Support/HHR Clinical/runtime'/digest[:16]
        (self.runtime/'bin').mkdir(parents=True);self.python=self.runtime/'bin/python3'
        self.python.write_text('test');self.python.chmod(0o700)
        (self.runtime/'runtime.ok').write_text(json.dumps(dict(lock_sha256=digest)))
        self.calls=[]
        def runner(args,**kwargs):
            self.calls.append(args);return SimpleNamespace(returncode=1 if args[1]=='print' else 0)
        self.svc=service.Service(self.home,self.skill,runner)
    def tearDown(self):self.temp.cleanup()
    def test_install_uses_absolute_argv_without_shell_and_preserves_user_permissions(self):
        with patch('service_manager.port_busy',return_value=False):self.svc.install()
        config=plistlib.loads(self.svc.path.read_bytes())
        self.assertEqual(config['ProgramArguments'],[str(self.python),str(self.skill.resolve()/'scripts/local_launcher.py'),'--no-browser'])
        self.assertTrue(config['KeepAlive']);self.assertEqual(config['Umask'],0o077)
        self.assertEqual(self.svc.path.stat().st_mode&0o777,0o600)
        self.assertEqual(self.calls[-1][1],'bootstrap');self.assertNotIn('sudo',str(self.calls))
    def test_busy_port_and_unverified_runtime_leave_no_agent(self):
        with patch('service_manager.port_busy',return_value=True),self.assertRaises(ValueError):self.svc.install()
        self.assertFalse(self.svc.path.exists())
        (self.runtime/'runtime.ok').write_text('{}')
        with self.assertRaises(ValueError):service.runtime(self.skill,self.home)
    def test_service_stop_only_targets_its_own_user_label(self):
        self.svc.runner=lambda args,**kw:(self.calls.append(args) or SimpleNamespace(returncode=0))
        self.svc.stop();self.assertEqual(self.calls[-1],['/bin/launchctl','bootout',self.svc.target])


class TransportTests(unittest.TestCase):
    def test_heartbeat_has_a_deadline_and_no_identifiers(self):
        now=datetime(2026,10,20,tzinfo=timezone.utc);status=heartbeat('test',clock=now)
        self.assertEqual(datetime.fromisoformat(status['expiresAt'])-now,timedelta(seconds=90))
        self.assertEqual(heartbeat('test',running=False,clock=now)['expiresAt'],now.isoformat())
        self.assertEqual(heartbeat('test',accepting=False)['status'],'attention')
    def job(self):
        return dict(ruts=['11111111-1'],selected=['eloisa','exalab'],source_states={'eloisa':'complete','exalab':'needs_session'},
                    status='attention',files=[{'path':'private'}],archive={'status':'partial','sync':'pending'})
    def test_partial_documents_summary_and_sync_remain_distinct(self):
        job=self.job();state=project(job,[]);self.assertEqual(state['status'],'documents_partial')
        self.assertEqual(state['sourceCounts'],dict(completed=1,pending=1,total=2))
        ready=project(job,[dict(kind='antecedentes',status='archived')])
        self.assertEqual(ready['status'],'summary_ready');self.assertEqual(ready['archive']['sync'],'pending')
        self.assertNotIn('11111111',json.dumps(ready));self.assertNotIn('private',json.dumps(ready))
        job['cancel_requested']=True;self.assertEqual(project(job,[])['status'],'cancelled')
    def test_drive_mount_after_start_is_recovered_without_restart(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'drive'/'_Solicitudes Nexo';inbox=DriveInbox(fixtures.FakeQueue(),path,interval=.02)
            self.assertEqual(inbox.scan_once(),0);self.assertFalse(path.exists())
            path.parent.mkdir();inbox.scan_once();self.assertTrue((path/'worker.json').exists())
            inbox.close();self.assertEqual(json.loads((path/'worker.json').read_text())['status'],'stopped')
    def test_progress_is_refreshed_for_already_imported_request_without_reimport(self):
        fixture=fixtures.DriveInboxTests();fixture.setUp()
        try:
            fixture.queue.transport_status=lambda ident:dict(status='documents_partial',fileCount=1)
            packet=fixture.packet();digest=fixture.place(packet);fixture.inbox.scan_once()
            path=fixture.inbox.root/'acuses'/('progreso-'+packet['id']+'.json')
            self.assertEqual(json.loads(path.read_text())['sha256'],digest)
            fixture.queue.transport_status=lambda ident:dict(status='summary_ready',fileCount=2)
            fixture.inbox._last_status=0;self.assertEqual(fixture.inbox.scan_once(),0)
            self.assertEqual(json.loads(path.read_text())['status'],'summary_ready');self.assertEqual(len(fixture.queue.requests),1)
        finally:fixture.tearDown()
    def test_linked_receipt_directory_cannot_redirect_writes(self):
        fixture=fixtures.DriveInboxTests();fixture.setUp()
        try:
            outside=fixture.root/'outside';outside.mkdir();(fixture.inbox.root/'acuses').symlink_to(outside)
            fixture.place(fixture.packet());fixture.inbox.scan_once();self.assertEqual(list(outside.iterdir()),[])
        finally:fixture.tearDown()

if __name__=='__main__':unittest.main()
