"""Regresiones ficticias: bytes → estado → cierre → reanudación."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_regression_workflow import WorkflowTests
from test_access import RUT,DAY,Fake
import laboratorios_download as labs

class IntegrityClosureTests(unittest.TestCase):
    setUp=WorkflowTests.setUp
    tearDown=WorkflowTests.tearDown
    queue=WorkflowTests.queue
    request=WorkflowTests.request
    def complete_job(self):
        q=self.queue();created=q.new_job(self.request());job=q.jobs[created['id']];job['as_of']=DAY.isoformat()
        work=Path(job['work_output']);summary=labs.run_batch([RUT],'eloisa,rayen','6m',DAY,work,{'eloisa':Fake(),'rayen':Fake(source='rayen')},mmrad_mode='both')
        job.update(status='complete',checkpoint=summary['checkpoint'],attempted=True)
        q._refresh(job);q._reconcile(job);q._receipt(job);q._persist()
        return q,job,summary
    def test_inactive_source_missing_files_becomes_partial_on_resume(self):
        first=labs.run_batch([RUT],'eloisa,rayen','6m',DAY,self.output,{'eloisa':Fake(),'rayen':Fake(source='rayen')})
        for p in first['results'][0]['files']:Path(p).unlink()
        for p in (Path(first['checkpoint']).parent/'originales'/RUT/'eloisa').glob('*.pdf'):p.unlink()
        again=labs.run_batch([RUT],'eloisa,rayen','6m',DAY,self.output,{'rayen':Fake(source='rayen')},resume=first['checkpoint'],retry_sources='rayen')
        self.assertEqual(again['results'][0]['status'],'partial')
        self.assertEqual(again['results'][1]['status'],'complete')
        self.assertIn('[~] 3.',again['receipts'][0]['text'])
    def test_complete_job_rechecks_modified_file_and_keeps_original(self):
        q,job,summary=self.complete_job();bad=Path(summary['results'][0]['files'][0]);bad.write_bytes(b'modified')
        state=q.status(job['id'])
        self.assertEqual(state['status'],'attention');self.assertNotEqual(state['source_states']['eloisa'],'complete')
        self.assertEqual(state['source_states']['rayen'],'complete')
        self.assertNotIn(bad.name,[f['name'] for f in state['files']])
        self.assertTrue(any(f['source']=='eloisa' for f in state['files']))
        line=next(l for l in state['receipts'][0]['text'].splitlines() if '3. Eloísa' in l)
        self.assertIn('[~]',line);self.assertIn('1 archivo(s) verificado(s)',line)
        q.retry(job['id']);self.assertEqual(job['pending_sources'],['eloisa'])
    def test_restart_audits_completed_jobs_without_redownloading(self):
        q,job,summary=self.complete_job();ident=job['id']
        q.close();self.launchers.remove(q)
        for p in summary['results'][0]['files']:Path(p).unlink()
        for p in (Path(summary['checkpoint']).parent/'originales'/RUT/'eloisa').glob('*.pdf'):p.unlink()
        restored=self.queue();self.assertEqual(restored.history()[0]['status'],'attention')
        state=restored.status(ident);self.assertEqual(state['source_states']['rayen'],'complete')
        self.assertIn('[~] 3.',state['receipts'][0]['text'])
        self.assertEqual(restored.jobs[ident]['pending_sources'],['eloisa'])
    def test_list_only_is_completed_without_claiming_download(self):
        result=labs.run_batch([RUT],'eloisa','6m',DAY,self.output,{'eloisa':Fake()},list_only=True)
        self.assertIn('[X] 3. Eloísa Ambulatorio — listado completado',result['receipts'][0]['text'])
        self.assertIn('sin descarga solicitada',result['receipts'][0]['text'])
    def test_progress_does_not_resign_modified_verified_pdf(self):
        first=labs.run_batch([RUT],'eloisa','6m',DAY,self.output,{'eloisa':Fake()})
        row=first['results'][0];path=Path(row['files'][0]);path.write_bytes(path.read_bytes()+b'changed')
        data=labs.read_progress(first['checkpoint']);progress=labs.Progress(self.output,data['request'],resume=first['checkpoint']);progress.state=data
        changed=progress.update(row)
        self.assertEqual(changed['status'],'partial');self.assertNotIn(str(path),changed['files'])
        self.assertEqual(len(changed['files']),len(row['files'])-1)
    def test_integrity_cache_detects_same_size_change_with_restored_mtime(self):
        import os
        q,job,summary=self.complete_job();q.status(job['id'])
        path=Path(summary['results'][0]['files'][0]);stat=path.stat();content=path.read_bytes();path.write_bytes(content.replace(b'PDF',b'BAD',1));os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        self.assertEqual(q.status(job['id'])['status'],'attention')
    def test_removed_work_folder_does_not_leave_complete_history(self):
        import shutil
        q,job,summary=self.complete_job();ident=job['id'];q.close();self.launchers.remove(q)
        shutil.rmtree(job['work_output'])
        restored=self.queue();self.assertEqual(restored.history()[0]['status'],'attention')
        state=restored.status(ident);self.assertEqual(state['files'],[])
        self.assertIn('[~] 3.',state['receipts'][0]['text'])
    def test_unchanged_completed_job_remains_complete(self):
        q,job,summary=self.complete_job();before=q.status(job['id']);after=q.status(job['id'])
        self.assertEqual(after['status'],'complete');self.assertEqual(before['receipts'],after['receipts']);self.assertEqual(len(after['files']),4)

del WorkflowTests
