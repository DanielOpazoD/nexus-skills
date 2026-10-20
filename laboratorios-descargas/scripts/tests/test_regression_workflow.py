import hashlib,json,sys,tempfile,time,unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laboratorios_download as labs
from clinical_archive import PatientArchive,DriveVerifier,ArchiveError,digest,copy_version
from clinical_jobs import PersistentLauncher
from local_launcher import SERVICES
from test_access import Fake,RUT,DAY,pdf,exam

class Keychain:
    def __init__(self):self.values={}
    def get(self,k):return self.values.get(k)
    def put(self,k,v):self.values[k]=v
class Cloud:
    """Modelo remoto explícito: no afirma sincronización real."""
    def verify(self,path,relative):return {'status':'confirmed','file_id':'fixture-'+digest(path)[:12]}
def wait_for(predicate,seconds=8):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        value=predicate()
        if value:return value
        time.sleep(.04)
    raise AssertionError('No se alcanzó el estado esperado')
class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.output=self.root/'local';self.drive=self.root/'drive';self.drive.mkdir();self.launchers=[]
    def tearDown(self):
        for queue in self.launchers:queue.close()
        self.temp.cleanup()
    def queue(self,auto=False,output=None):
        q=PersistentLauncher(output or self.output,sys.executable,Keychain(),Path(__file__).with_name('fake_download.py'),labs,SERVICES,self.drive,Cloud(),auto)
        self.launchers.append(q);return q
    def request(self,sources='eloisa,rayen',**extra):return dict(ruts=[RUT],source=sources,period='6m',schema=2,**extra)
    def download(self):return labs.run_batch([RUT],'eloisa','6m',DAY,self.output,{'eloisa':Fake()},patient_merge=True)
    def test_failed_resume_retains_prior_files_and_notice(self):
        first=self.download();prior=set(first['results'][0]['files'])
        retry=labs.run_batch([RUT],'eloisa','6m',DAY,self.output,{'eloisa':Fake(fail=True)},resume=first['checkpoint'],patient_merge=True)
        row=retry['results'][0];self.assertEqual(row['status'],'partial');self.assertTrue(prior.issubset(row['files']))
        self.assertEqual(row['notice'],'Documento obtenido previamente; actualización pendiente.')
        self.assertTrue(all(Path(p).is_file() for p in prior))
        self.assertEqual(retry['patient_pdfs'][0]['files'],first['patient_pdfs'][0]['files'])
        self.assertEqual(retry['patient_pdfs'][0]['freshness'],'update_pending')
    def test_modified_published_pdf_excluded_original_recovered(self):
        first=self.download();published=Path(first['results'][0]['files'][0]);published.write_bytes(pdf()+b'changed')
        retry=labs.run_batch([RUT],'eloisa','6m',DAY,self.output,{},resume=first['checkpoint'],patient_merge=True)
        self.assertNotIn(str(published),retry['results'][0]['files']);self.assertTrue(retry['results'][0]['files'])
    def test_archive_by_identity_and_homonyms(self):
        arch=PatientArchive(self.output,self.drive,Cloud());one=arch.folder(RUT,'Nombre Ficticio');two=arch.folder('22222222-2','Nombre Ficticio')
        self.assertEqual(two.name,'Nombre Ficticio (2)');self.assertNotEqual(one,two)
        again=PatientArchive(self.output/'another',self.drive,Cloud());self.assertEqual(again.folder(RUT,'Otro Nombre'),one)
    def test_unknown_homonym_blocks_merge(self):
        (self.drive/'Pacientes'/'Nombre Ficticio').mkdir(parents=True)
        with self.assertRaises(ArchiveError):PatientArchive(self.output,self.drive).folder(RUT,'Nombre Ficticio')
    def test_drive_missing_not_manufactured(self):
        missing=self.root/'not-mounted';result=PatientArchive(self.output,missing).archive(self.download())
        self.assertFalse(missing.exists());self.assertEqual(result['status'],'partial')
    def test_end_to_end_download_identity_archive_and_cloud(self):
        summary=self.download();result=PatientArchive(self.output,self.drive,Cloud()).archive(summary)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['sync'],'confirmed')
        names=[Path(f['path']).name for f in result['files']]
        self.assertIn('Identidad del paciente.txt',names);self.assertTrue(any(n.startswith('Estado de descargas') for n in names))
        self.assertTrue(all(digest(f['path'])==f['sha256'] for f in result['files']))
        self.assertTrue(any('Originales individuales' in f['path'] for f in result['files']))
    def test_copy_does_not_claim_cloud_without_connection(self):
        result=PatientArchive(self.output,self.drive).archive(self.download())
        self.assertTrue(result['files']);self.assertEqual(result['status'],'complete');self.assertEqual(result['sync'],'pending')
    def test_corrupt_original_does_not_cancel_other_documents(self):
        summary=self.download();next((Path(summary['checkpoint']).parent/'originales').rglob('*.pdf')).write_bytes(b'bad')
        result=PatientArchive(self.output,self.drive,Cloud()).archive(summary)
        self.assertEqual(result['status'],'partial');self.assertTrue(any(f['path'].endswith('.pdf') for f in result['files']))
    def test_versions_and_modified_source(self):
        src=self.root/'source.pdf';src.write_bytes(pdf());target=self.drive/'same.pdf';a,_=copy_version(src,target,digest(src));b,_=copy_version(src,target)
        self.assertEqual(a,b);old=digest(src);src.write_bytes(pdf()+b'\n')
        with self.assertRaises(ArchiveError):copy_version(src,target,old)
        c,_=copy_version(src,target);self.assertNotEqual(a,c);self.assertTrue(a.exists())
    def test_queue_accepts_multiple_and_missing_credential(self):
        q=self.queue();one=q.new_job(self.request('syslab,his'));two=q.new_job(self.request('eloisa'))
        self.assertNotEqual(one['id'],two['id']);self.assertEqual(len(q.history()),2)
        self.assertEqual(q.status(one['id'])['source_states']['syslab'],'needs_credentials')
    def test_partial_sessions_and_no_secrets_on_disk(self):
        q=self.queue();job=q.new_job(self.request('exalab,eloisa,rayen',credentials={'his':{'username':'test','password':'private-password'}}))
        response=q.provide_sessions({**job,'eloisa':{'access_token':'private-token'}})
        self.assertEqual(response['accepted'],['eloisa']);self.assertEqual(q._ready(q.jobs[job['id']]),['eloisa'])
        serialized=q.store.read_text()
        for secret in ('private-token','private-password',job['nonce'],'access_token'):self.assertNotIn(secret,serialized)
    def test_six_sources_and_legacy_five(self):
        q=self.queue();modern=q.new_job(self.request('all'));legacy=q.new_job(dict(ruts=[RUT],source='all',period='6m'))
        self.assertEqual(len(q.jobs[modern['id']]['selected']),6);self.assertEqual(len(q.jobs[legacy['id']]['selected']),5)
    def test_restart_new_nonce_preserves_history(self):
        q=self.queue();job=q.new_job(self.request());q.close();self.launchers.remove(q)
        restored=self.queue();self.assertEqual(len(restored.history()),1);self.assertNotEqual(restored.status(job['id'])['nonce'],job['nonce'])
        self.assertEqual(restored.status(job['id'])['status'],'interrupted')
        with self.assertRaises(ValueError):restored.provide_sessions({**job,'eloisa':{'access_token':'stale'}})
    def test_queue_real_process_partial_source_then_resume(self):
        q=self.queue(True);job=q.new_job(self.request('eloisa,his,rayen'))
        q.provide_sessions({**job,'eloisa':{'access_token':'fixture'}})
        status=wait_for(lambda:(v if (v:=q.status(job['id']))['status']=='attention' and v['files'] and v['archive'].get('files') else None))
        self.assertEqual(status['source_states']['eloisa'],'complete');self.assertEqual(status['archive']['sync'],'confirmed')
        q.provide_sessions({**job,'rayen':{'token':'fixture','facilityId':77}})
        status=wait_for(lambda:(v if (v:=q.status(job['id']))['source_states'].get('rayen')=='complete' else None))
        self.assertTrue(any(f['source']=='eloisa' for f in status['files']));self.assertTrue(any(f['source']=='rayen' for f in status['files']))
        self.assertNotEqual(status['source_states']['his'],'complete')
    def test_cancel_running_retains_checkpoint_documents_and_restart(self):
        q=self.queue(True);job=q.new_job(self.request('rayen'));q.provide_sessions({**job,'rayen':{'token':'slow','facilityId':77}})
        def first_saved():
            cp=q.jobs[job['id']].get('checkpoint')
            return cp and list((Path(cp).parent/'originales').rglob('*.pdf'))
        wait_for(first_saved);q.cancel(job['id'])
        status=wait_for(lambda:(v if (v:=q.status(job['id']))['status']=='cancelled' and v['files'] else None))
        self.assertTrue(status['files']);q.close();self.launchers.remove(q)
        restored=self.queue();self.assertEqual(restored.status(job['id'])['status'],'cancelled');self.assertTrue(restored.status(job['id'])['files'])
    def test_restart_only_incomplete_sources(self):
        q=self.queue();job=q.new_job(self.request());work=Path(q.jobs[job['id']]['work_output'])
        summary=labs.run_batch([RUT],'eloisa,rayen','6m',DAY,work,{'eloisa':Fake()},mmrad_mode='both')
        q.jobs[job['id']].update(status='running',checkpoint=summary['checkpoint']);q._persist();q.close();self.launchers.remove(q)
        restored=self.queue();self.assertEqual(restored.jobs[job['id']]['pending_sources'],['rayen'])
    def test_remote_verifier_requires_all_path_and_hash_checks(self):
        src=self.root/'document.pdf';src.write_bytes(pdf());calls=[]
        def remote(path,args):
            calls.append(args['q'])
            if len(calls)<3:return {'files':[{'id':str(len(calls)),'mimeType':'application/vnd.google-apps.folder'}]}
            return {'files':[{'id':'document','size':str(src.stat().st_size),'md5Checksum':digest(src,'md5')}]}
        result=DriveVerifier(transport=remote,root_id='root').verify(src,'Pacientes/Nombre/document.pdf')
        self.assertEqual(result['status'],'confirmed');self.assertIn("'root' in parents",calls[0]);self.assertIn("'2' in parents",calls[2])
        bad=lambda *a:{'files':[{'id':'document','size':str(src.stat().st_size),'md5Checksum':'wrong'}]}
        self.assertEqual(DriveVerifier(transport=bad).verify(src,'document.pdf')['status'],'pending')
    def test_two_patients_never_share_a_document(self):
        summary=labs.run_batch([RUT,'22222222-2'],'eloisa','6m',DAY,self.output,{'eloisa':Fake()})
        self.assertEqual(summary['results'][0]['status'],'complete')
        self.assertEqual(summary['results'][1]['files'],[])
        archived=PatientArchive(self.output,self.drive,Cloud()).archive(summary)
        folders=list((self.drive/'Pacientes').iterdir());self.assertEqual(len(folders),1)
        self.assertIn(RUT,(folders[0]/'Identidad del paciente.txt').read_text())
    def test_missing_checkpoint_pointer_is_recovered_after_restart(self):
        q=self.queue();job=q.new_job(self.request('eloisa'));work=Path(q.jobs[job['id']]['work_output'])
        q.jobs[job['id']]['as_of']=DAY.isoformat()
        summary=labs.run_batch([RUT],'eloisa','6m',DAY,work,{'eloisa':Fake()})
        q.jobs[job['id']]['status']='running';q._persist();q.close();self.launchers.remove(q)
        restored=self.queue();self.assertEqual(restored.jobs[job['id']]['checkpoint'],summary['checkpoint'])
        self.assertEqual(restored.status(job['id'])['status'],'complete')
    def test_available_sources_only_are_authenticated(self):
        source=labs.load_backend('eloisa')
        class Eloisa:
            def __init__(self,*a,**kw):pass
            def search(self,*a,**kw):return []
        original_loader=labs.load_backend
        def loader(name):
            if name=='mmrad':raise AssertionError('No debe autenticar MMRAD sin acceso disponible')
            return source if name=='eloisa' else original_loader(name)
        with patch.object(source,'Eloisa',Eloisa),patch.object(labs,'load_backend',side_effect=loader):
            code=labs.main(['--ruts',RUT,'--source','eloisa,mmrad','--ready-sources','eloisa','--period','6m','--output',str(self.output)],secrets={'eloisa':{'access_token':'fixture'}})
        self.assertEqual(code,1)
        result=json.loads(next(self.output.glob('resumen_*.json')).read_text())
        self.assertEqual(result['results'][0]['status'],'empty')
        self.assertIn('Acceso pendiente',result['results'][1]['errors'][0])
    def test_legacy_wrong_patient_checkpoint_not_archived(self):
        summary=labs.run_batch([RUT],'rayen','6m',DAY,self.output,{'rayen':Fake(source='rayen')})
        cp=Path(summary['checkpoint']);data=json.loads(cp.read_text());original=next((cp.parent/'originales').rglob('*.pdf'))
        import io
        from reportlab.pdfgen.canvas import Canvas
        out=io.BytesIO();c=Canvas(out);c.drawString(30,800,'Paciente Otro RUN: 22222222-2');c.drawString(30,780,'Medico RUN: 11111111-1');c.drawString(30,760,'Fecha Egreso: 15-10-2026');c.save();original.write_bytes(out.getvalue())
        data['reports'][RUT]['rayen']['1']['sha256']=digest(original);cp.write_text(json.dumps(data))
        result=PatientArchive(self.output,self.drive,Cloud()).archive(summary)
        self.assertEqual(result['status'],'partial');self.assertFalse(any('Originales individuales' in f['path'] for f in result['files']))
if __name__=='__main__':unittest.main()
