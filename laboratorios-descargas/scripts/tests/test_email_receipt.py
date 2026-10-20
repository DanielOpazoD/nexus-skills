"""Synthetic email → import → receipt → patient archive; no network or mail access."""
import copy,hashlib,json,sys,tempfile,unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laboratorios_download as labs
import clinical_email as mail
import clinical_receipt as receipt
from clinical_archive import PatientArchive
from clinical_jobs import PersistentLauncher
from local_launcher import SERVICES
from portable_request import parse,download_args
from test_access import RUT,DAY,Fake
from test_regression_workflow import Keychain,Cloud,wait_for

class EmailReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.out=self.root/'work';self.drive=self.root/'drive';self.drive.mkdir();self.queues=[]
    def tearDown(self):
        for q in self.queues:q.close()
        self.tmp.cleanup()
    def evidence(self,output=None,as_of=DAY.isoformat()):
        output=output or self.out;folder=output/RUT/'email';folder.mkdir(parents=True,exist_ok=True)
        data=dict(version=1,rut=RUT,period='6m',as_of=as_of,account=mail.DEFAULT_ACCOUNT,status='complete',patient_name='Paciente Ficticio',patient_name_verified=True,
            queries=[dict(query=mail.plan(RUT,'6m',as_of)['queries'][0],message_ids=['abcdef1234567890'],complete=True,next_page_token=None)],
            messages=[dict(id='abcdef1234567890',decision='include',identity_verified=True,identity_basis='RUT explícito del paciente en cuerpo y documento ficticios.',received_at=as_of+'T12:00:00-05:00',attachments_reviewed=True)],files=[],pending=[])
        for name in ['Mensaje - 19-10-2026.txt','Adjunto - 19-10-2026.txt']:
            p=folder/name;p.write_text('EVIDENCIA FICTICIA\nPaciente: Paciente Ficticio\nRUT: '+RUT)
            data['files'].append(dict(path=name,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),message_id='abcdef1234567890',identity_verified=True))
        self.save(data,output);return data
    def save(self,data,output=None):
        ((output or self.out)/RUT/'email'/'resultado-correo.json').write_text(json.dumps(data))
    def queue(self,auto=False):
        q=PersistentLauncher(self.out,sys.executable,Keychain(),Path(__file__).with_name('fake_download.py'),labs,SERVICES,self.drive,Cloud(),auto)
        self.queues.append(q);return q
    def test_query_scope_timezone_and_calendar(self):
        p=mail.plan(RUT,'3m','2024-05-31');self.assertEqual(p['start'],'2024-02-29')
        self.assertIn('"11.111.111-1"',p['queries'][0]);self.assertIn('after:',p['queries'][0]);self.assertNotIn('after:2024',p['queries'][0])
        self.assertEqual(mail.plan(RUT,'10y','2024-02-29')['start'],'2014-02-28')
        with self.assertRaises(ValueError):mail.plan(RUT,'6m',DAY.isoformat(),name='Paciente " OR from:')
    def test_wrong_account_rut_or_period_cannot_import(self):
        data=self.evidence()
        for field,value in [('account','other@example.org'),('rut','22222222-2'),('period','1y')]:
            bad=copy.deepcopy(data);bad[field]=value;self.save(bad)
            with self.subTest(field=field),self.assertRaises(ValueError):mail.load_result(self.out,RUT,'6m',DAY.isoformat())
    def test_missing_identity_does_not_enter_patient_evidence(self):
        data=self.evidence();data['messages'][0]['identity_verified']=False;self.save(data)
        row=mail.load_result(self.out,RUT,'6m',DAY.isoformat());self.assertEqual(row['status'],'partial');self.assertEqual(row['files'],[])
    def test_unread_page_or_attachment_cannot_claim_completion(self):
        good=self.evidence()
        for change in ('page','unread','attachment'):
            d=copy.deepcopy(good)
            if change=='page':d['queries'][0].update(next_page_token='more')
            if change=='unread':d['queries'][0]['message_ids'].append('bbbbbbbbbbbbbbbb')
            if change=='attachment':d['messages'][0]['attachments_reviewed']=False
            self.save(d);row=mail.load_result(self.out,RUT,'6m',DAY.isoformat());self.assertEqual(row['status'],'partial');self.assertEqual(len(row['files']),2)
    def test_one_modified_attachment_preserves_other_verified_file(self):
        data=self.evidence();(self.out/RUT/'email'/data['files'][1]['path']).write_text('MODIFICADO')
        row=mail.load_result(self.out,RUT,'6m',DAY.isoformat());self.assertEqual(row['status'],'partial');self.assertEqual(len(row['files']),1)
    def test_empty_is_distinct_from_not_queried(self):
        d=self.evidence();d.update(status='empty',messages=[],files=[]);d['queries'][0]['message_ids']=[];self.save(d)
        summary=labs.run_batch([RUT],'email','6m',DAY,self.out,{})
        self.assertIn('[X] 7. Correo institucional — sin registros',summary['receipts'][0]['text'])
        (self.out/RUT/'email'/'resultado-correo.json').unlink()
        retry=labs.run_batch([RUT],'email','6m',DAY,self.out,{},resume=summary['checkpoint'])
        self.assertIn('[ ] 7. Correo institucional — pendiente',retry['receipts'][0]['text'])
    def test_failed_update_retains_mail_and_marks_partial(self):
        self.evidence();first=labs.run_batch([RUT],'email','6m',DAY,self.out,{})
        (self.out/RUT/'email'/'resultado-correo.json').unlink()
        again=labs.run_batch([RUT],'email','6m',DAY,self.out,{},resume=first['checkpoint'])
        self.assertEqual(len(again['results'][0]['files']),2);self.assertIn('[~] 7.',again['receipts'][0]['text']);self.assertIn('obtenido previamente',again['receipts'][0]['text'])
    def test_receipt_end_to_end_partial_sources_and_archive(self):
        self.evidence();summary=labs.run_batch([RUT],'eloisa,email,his','6m',DAY,self.out,{'eloisa':Fake()},source_periods={'his':'3m'})
        text=summary['receipts'][0]['text'];self.assertIn('[X] 3.',text);self.assertIn('[ ] 4.',text);self.assertIn('[X] 7.',text);self.assertIn('19-07-2026',text);self.assertNotIn('2026-10-',text)
        result=PatientArchive(self.out,self.drive,Cloud()).archive(summary)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['sync'],'confirmed')
        self.assertTrue(any('/Correo/' in x['path'] for x in result['files']));self.assertTrue(any('Resumen de fuentes' in x['path'] for x in result['files']))
        summary['results'][0]['files'] and Path(summary['results'][0]['files'][0]).write_bytes(b'changed')
        self.assertIn('[~] 3.',receipt.text(summary,RUT,self.out))
    def test_missing_mmrad_product_is_partial(self):
        summary=dict(source='mmrad',period='6m',as_of=DAY.isoformat(),mmrad_mode='both',results=[dict(rut=RUT,source='mmrad',status='empty',files=[],errors=[])])
        self.assertIn('[~] 6.',receipt.text(summary,RUT,self.out))
    def test_queue_mail_only_no_credentials_restart_cancel_and_txt(self):
        q=self.queue();job=q.new_job(dict(ruts=[RUT],source='email',period='6m',schema=2))
        state=q.status(job['id']);self.assertEqual(job['need'],[]);self.assertEqual(q._ready(q.jobs[job['id']]),['email']);self.assertEqual(state['source_states']['email'],'needs_codex')
        self.assertTrue(Path(state['receipts'][0]['path']).exists());self.assertIn(mail.DEFAULT_ACCOUNT,q.mail_request(job['id'])['prompt'])
        q.cancel(job['id']);self.assertIn('cancelada',q.status(job['id'])['receipts'][0]['text']);q.close();self.queues.remove(q)
        restored=self.queue();self.assertEqual(restored.status(job['id'])['status'],'cancelled');self.assertTrue(restored.status(job['id'])['receipts'])
        self.assertTrue(any('Cierres pendientes' in x['path'] for x in restored.status(job['id'])['archive']['files']))
    def test_worker_import_retry_and_receipt_persist(self):
        q=self.queue(True);job=q.new_job(dict(ruts=[RUT],source='email,his',period='6m',schema=2))
        wait_for(lambda:q.status(job['id'])['status']=='attention')
        current=q.jobs[job['id']];self.evidence(Path(current['work_output']),current['as_of']);q.retry(job['id'])
        state=wait_for(lambda:(v if (v:=q.status(job['id']))['source_states']['email']=='complete' and v['archive']['files'] else None))
        self.assertNotEqual(state['source_states']['his'],'complete');self.assertEqual(len(state['files']),2)
        wait_for(lambda:'[X] 7.' in q.status(job['id'])['receipts'][0]['text'])
    def test_cli_interruption_keeps_closure_with_obtained_documents(self):
        class Stop:
            def search(self,*args,**kwargs):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):labs.run_batch([RUT],'eloisa,his','6m',DAY,self.out,{'eloisa':Fake(),'his':Stop()})
        saved=list((self.out/RUT).glob('Resumen de fuentes*.txt'));self.assertEqual(len(saved),1)
        value=saved[0].read_text();self.assertIn('cancelada',value);self.assertIn('[X] 3.',value);self.assertIn('[ ] 4.',value)
    def test_email_text_is_available_for_optional_delivery(self):
        from clinical_delivery import handoff,selection
        d=self.evidence();summary=labs.run_batch([RUT],'email','6m',DAY,self.out,{})
        row=summary['results'][0]
        job=dict(id='fixture',delivery=selection('custom','Resume lo verificado'),files=[dict(m,rut=RUT,source='email') for m in row['file_manifest']],summary=summary['results'],work_output=str(self.out),ruts=[RUT],as_of=DAY.isoformat(),period='6m',selected=['email'],source_states={'email':'complete'},receipts=summary['receipts'])
        result=handoff(job,self.out);self.assertEqual(result['files'],2);self.assertEqual(result['excluded'],0);self.assertIn('cierres_txt',result['prompt'])
        Path(row['files'][0]).write_text('modified');self.assertEqual(handoff(job,self.out)['files'],1)

    def test_legacy_all_never_silently_adds_mail(self):
        self.assertNotIn('email',labs.selected_sources('all'));self.assertIn('email',labs.selected_sources('eloisa,email'))

if __name__=='__main__':unittest.main()
