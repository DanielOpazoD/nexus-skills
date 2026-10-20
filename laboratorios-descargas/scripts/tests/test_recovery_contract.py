"""Un avance sólo puede certificar la solicitud completa que lo originó."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_regression_workflow import WorkflowTests
from test_access import RUT,DAY,Fake
import laboratorios_download as labs

class RecoveryContractTests(unittest.TestCase):
    setUp=WorkflowTests.setUp
    tearDown=WorkflowTests.tearDown
    queue=WorkflowTests.queue
    request=WorkflowTests.request
    def create(self,**extra):
        q=self.queue(output=self.root/('case-'+str(len(self.launchers))));ident=q.new_job(self.request('eloisa',**extra))['id'];job=q.jobs[ident];job['as_of']=DAY.isoformat()
        return q,job,Path(job['work_output'])
    def test_incompatible_checkpoint_is_not_adopted_or_reported_complete(self):
        for change in ({'eloisa_scope':'todos'},{'merge':True},{'patient_merge':True},{'list_only':True}):
            for direct_pointer in (False,True):
                with self.subTest(change=change,pointer=direct_pointer):
                    q,job,work=self.create()
                    summary=labs.run_batch([RUT],'eloisa','6m',DAY,work,{'eloisa':Fake()},**change)
                    if direct_pointer:job['checkpoint']=summary['checkpoint']
                    job.update(status='running',attempted=True)
                    q._refresh(job);q._reconcile(job)
                    self.assertNotEqual(job['source_states']['eloisa'],'complete')
                    self.assertFalse(job['files'])
                    self.assertTrue(Path(summary['checkpoint']).exists())
    def test_altered_summary_cannot_override_matching_checkpoint(self):
        q,job,work=self.create();summary=labs.run_batch([RUT],'eloisa','6m',DAY,work,{'eloisa':Fake()})
        altered=copy.deepcopy(summary);altered['period']='10y';altered['results'][0].update(status='empty',files=[],file_manifest=[],folios=[])
        result=work/'resumen-fixture.json';result.write_text(json.dumps(altered))
        job.update(checkpoint=summary['checkpoint'],result_path=str(result))
        q._refresh(job);q._reconcile(job)
        self.assertTrue(job['files']);self.assertEqual(job['summary'][0]['status'],'complete')
    def test_conflicting_duplicate_rows_do_not_certify_source(self):
        q,job,work=self.create();summary=labs.run_batch([RUT],'eloisa','6m',DAY,work,{'eloisa':Fake()})
        path=Path(summary['checkpoint']);saved=json.loads(path.read_text())
        saved['results'].append(dict(saved['results'][0],status='error',errors=['Consulta incompleta']))
        path.write_text(json.dumps(saved));job['checkpoint']=str(path)
        q._refresh(job);q._reconcile(job)
        self.assertNotEqual(job['source_states']['eloisa'],'complete')
        self.assertTrue(job['files'],'Conservar documentos verificados del grupo duplicado')
        from clinical_receipt import text
        summary['results']=saved['results']
        self.assertIn('[~] 3.',text(summary,RUT,work))
        q._receipt(job)
        self.assertIn('[~] 3.',job['receipts'][0]['text'])
    def test_malformed_row_does_not_hide_other_source(self):
        q=self.queue();ident=q.new_job(self.request('eloisa,rayen'))['id'];job=q.jobs[ident];job['as_of']=DAY.isoformat();work=Path(job['work_output'])
        summary=labs.run_batch([RUT],'eloisa,rayen','6m',DAY,work,{'eloisa':Fake(),'rayen':Fake(source='rayen')})
        path=Path(summary['checkpoint']);saved=json.loads(path.read_text());saved['results'][0]['file_manifest']=[None];path.write_text(json.dumps(saved));job['checkpoint']=str(path)
        q._refresh(job);q._reconcile(job)
        self.assertEqual(job['source_states']['rayen'],'complete')
        self.assertNotEqual(job['source_states']['eloisa'],'complete')
        self.assertTrue(any(f['source']=='rayen' for f in job['files']))
    def test_resume_with_damaged_manifest_preserves_other_source(self):
        first=labs.run_batch([RUT],'eloisa,rayen','6m',DAY,self.output,{'eloisa':Fake(),'rayen':Fake(source='rayen')})
        path=Path(first['checkpoint']);saved=json.loads(path.read_text());saved['results'][0]['file_manifest']=[None]
        path.write_text(json.dumps(saved))
        resumed=labs.run_batch([RUT],'eloisa,rayen','6m',DAY,self.output,{'eloisa':Fake(fail=True)},resume=path,retry_sources='eloisa')
        self.assertEqual(resumed['results'][0]['status'],'partial')
        self.assertTrue(resumed['results'][0]['files'])
        self.assertEqual(resumed['results'][1]['status'],'complete')
        self.assertEqual(resumed['results'][1]['files'],first['results'][1]['files'])
        self.assertIn('[~] 3.',resumed['receipts'][0]['text'])
        self.assertIn('[X] 5.',resumed['receipts'][0]['text'])

    def test_recovery_ignores_unrequested_patient_and_source(self):
        q,job,work=self.create();summary=labs.run_batch([RUT],'eloisa','6m',DAY,work,{'eloisa':Fake()})
        path=Path(summary['checkpoint']);saved=json.loads(path.read_text());row=saved['results'][0]
        saved['results']+=[dict(row,source='his'),dict(row,rut='22222222-2')]
        path.write_text(json.dumps(saved));job['checkpoint']=str(path)
        q._refresh(job);q._reconcile(job);q._receipt(job)
        self.assertEqual([(r['rut'],r['source']) for r in job['summary']],[(RUT,'eloisa')])
        self.assertTrue(all(f['source']=='eloisa' and f['rut']==RUT for f in job['files']))
        self.assertIn('[ ] 4. HIS — no solicitada',job['receipts'][0]['text'])

    def test_future_checkpoint_version_rejected_without_modification(self):
        q,job,work=self.create();summary=labs.run_batch([RUT],'eloisa','6m',DAY,work,{'eloisa':Fake()})
        path=Path(summary['checkpoint']);saved=json.loads(path.read_text());saved['version']=99;path.write_text(json.dumps(saved));before=path.read_bytes();job['checkpoint']=str(path)
        q._refresh(job);q._reconcile(job)
        self.assertNotEqual(job['source_states']['eloisa'],'complete');self.assertEqual(path.read_bytes(),before)

del WorkflowTests
if __name__=='__main__':unittest.main()
