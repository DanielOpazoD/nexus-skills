"""Contrato solicitud → descarga parcial → reanudación → modelo de entrega."""
import json,sys,tempfile,unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laboratorios_download as labs
from clinical_delivery import models,selection,handoff
from clinical_jobs import PersistentLauncher
from local_launcher import SERVICES
from test_access import Fake,RUT,DAY,exam
from test_regression_workflow import Keychain,Cloud,wait_for

class DeliveryPeriodTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.queues=[]
    def tearDown(self):
        for q in self.queues:q.close()
        self.temp.cleanup()
    def queue(self,auto=False):
        q=PersistentLauncher(self.root/'work',sys.executable,Keychain(),Path(__file__).with_name('fake_download.py'),labs,SERVICES,self.root/'drive',Cloud(),auto)
        self.queues.append(q);return q
    def request(self,**kw):
        return dict(ruts=[RUT],source='eloisa,rayen',period='6m',schema=2,**kw)
    def test_model_catalog_and_invalid(self):
        self.assertEqual(len(models()),7)
        for model in models():
            if model['id']!='custom':self.assertEqual(selection(model['id']),model)
        q=self.queue()
        for invalid in ('otro','telemedicina',None,[],{'id':'epicrisis'}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):q.new_job(self.request(deliveryModel=invalid))
        self.assertEqual(q.history(),[])
    def test_default_and_models_survive_restart(self):
        q=self.queue();default=q.new_job(self.request());self.assertEqual(q.status(default['id'])['delivery']['status'],'not_requested')
        for model in [m for m in models()[1:] if m['id']!='custom']:q.new_job(self.request(deliveryModel=model['id'],sourcePeriods={'eloisa':'2y'}))
        q.close();self.queues.remove(q);restored=self.queue()
        self.assertEqual(len(restored.history()),6)
        for row in restored.history():
            status=restored.status(row['id'])
            if row['id']==default['id']:continue
            self.assertEqual(status['delivery']['status'],'codex_pending' if status['delivery'].get('template_status')=='available' else 'template_pending')
            self.assertEqual(status['source_periods'],{'eloisa':'2y'})
    def test_baseline_summary_is_required_with_documents_and_an_additional_model(self):
        q=self.queue()
        for model in ('documents','telemedicina-reumatologia'):
            request=q.new_job(self.request(deliveryModel=model))
            delivery=q.delivery_request(request['id'])
            self.assertEqual(delivery['delivery']['id'],model)
            self.assertEqual(delivery['baseline_summary']['skill'],'resumen-antecedentes')
            self.assertTrue(delivery['baseline_summary']['required'])
            self.assertEqual(delivery['baseline_summary']['mode'],'codex')
            self.assertRegex(delivery['baseline_summary']['filename'],r'^\d{2}-\d{2}-\d{4} Resumen antecedentes\.txt$')
            self.assertEqual(delivery['files'],0,'Copiar un encargo no acredita redacción ni descarga.')
    def test_invalid_periods_and_unselected_source(self):
        q=self.queue()
        for invalid in ([], 'all',{'syslab':'1y'},{'eloisa':'20y'},{'eloisa':None}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):q.new_job(self.request(sourcePeriods=invalid))
        result=q.new_job(self.request(sourcePeriods={'eloisa':'6m'}))
        self.assertEqual(q.status(result['id'])['source_periods'],{})
    def test_each_source_filters_its_own_time_window(self):
        class Old(Fake):
            def search(self,rut):return [dict(exam(),datetime=datetime(2025,10,15))]
        summary=labs.run_batch([RUT],'eloisa,rayen','30d',DAY,self.root/'batch',{'eloisa':Old(),'rayen':Old()},list_only=True,source_periods={'eloisa':'2y'})
        rows={r['source']:r for r in summary['results']}
        self.assertEqual([f['id'] for f in rows['eloisa']['folios']],['1']);self.assertEqual(rows['rayen']['folios'],[])
        self.assertEqual(rows['eloisa']['period'],'2y');self.assertEqual(rows['rayen']['period'],'30d')
        with self.assertRaises(labs.LabsError):
            labs.run_batch([RUT],'eloisa,rayen','30d',DAY,self.root/'batch',{},list_only=True,resume=summary['checkpoint'],source_periods={'eloisa':'1y'})
    def test_mmrad_report_and_image_use_same_override(self):
        def row(source):return {'rut':RUT,'source':source,'status':'empty','folios':[],'files':[],'errors':[]}
        with patch.object(labs,'collect_group',return_value=row('mmrad')) as reports,patch.object(labs,'collect_mmrad_images',return_value=row('mmrad_images')) as images:
            labs.run_batch([RUT],'mmrad','30d',DAY,self.root/'images',{'mmrad':Fake()},mmrad_mode='both',source_periods={'mmrad':'5y'})
        self.assertEqual(reports.call_args.args[3],'5y');self.assertEqual(images.call_args.args[2],'5y')
    def test_partial_download_handoff_resume_and_restart(self):
        q=self.queue(True);req=q.new_job(self.request(deliveryModel='telemedicina-gastroenterologia',sourcePeriods={'eloisa':'30d','rayen':'5y'},requestId='a'*32,asOf=DAY.isoformat()))
        q.provide_sessions({**req,'eloisa':{'access_token':'fixture-secret'}})
        status=wait_for(lambda:(v if (v:=q.status(req['id']))['status']=='attention' and v['files'] else None))
        before={f['sha256'] for f in status['files']}
        self.assertEqual(status['delivery']['status'],'template_pending')
        cp=json.loads(Path(q.jobs[req['id']]['checkpoint']).read_text())
        self.assertEqual(cp['request']['source_periods'],{'eloisa':'30d','rayen':'5y'})
        draft=q.delivery_request(req['id']);self.assertGreater(draft['files'],0)
        self.assertIn('Gastroenterología',draft['prompt']);self.assertIn('El TXT basal no espera esa plantilla',draft['prompt'])
        self.assertIn(DAY.strftime('%d-%m-%Y'),draft['prompt']);self.assertNotIn('fixture-secret',draft['prompt'])
        q.provide_sessions({**req,'rayen':{'token':'fixture','facilityId':77}})
        complete=wait_for(lambda:(v if (v:=q.status(req['id']))['status']=='complete' else None))
        self.assertTrue(before.issubset({f['sha256'] for f in complete['files']}))
        self.assertEqual(complete['delivery']['status'],'template_pending')
        q.close();self.queues.remove(q);restored=self.queue()
        self.assertEqual(restored.status(req['id'])['delivery']['id'],'telemedicina-gastroenterologia')
    def test_handoff_rechecks_hash_patient_and_boundary(self):
        q=self.queue();req=q.new_job(self.request(deliveryModel='epicrisis',requestId='a'*32,asOf=DAY.isoformat()))
        job=q.jobs[req['id']];summary=labs.run_batch([RUT],'eloisa,rayen','6m',DAY,job['work_output'],{'eloisa':Fake()})
        job['checkpoint']=summary['checkpoint'];q._refresh(job)
        original=Path(job['files'][0]['path']);original.write_bytes(original.read_bytes()+b'changed')
        first=handoff(job,q.output);self.assertEqual(first['files'],len(job['files'])-1);self.assertGreater(first['excluded'],0)
        job['files'][0]['rut']='22222222-2';second=handoff(job,q.output);self.assertEqual(second['files'],len(job['files'])-1)
        job['files'][0]['path']=str(self.root/'outside.pdf');third=handoff(job,q.output);self.assertEqual(third['files'],len(job['files'])-1)
    def test_real_cli_passes_override_and_resumes_same_request(self):
        module=labs.load_backend('eloisa');original_loader=labs.load_backend
        class EmptyEloisa:
            def __init__(self,*a,**kw):pass
            def search(self,*a,**kw):return []
        args=['--ruts',RUT,'--source','eloisa,rayen','--ready-sources','eloisa','--period','6m','--source-periods','{"eloisa":"30d"}','--output',str(self.root/'cli')]
        with patch.object(module,'Eloisa',EmptyEloisa),patch.object(labs,'load_backend',side_effect=lambda name:module if name=='eloisa' else original_loader(name)):
            self.assertEqual(labs.main(args,secrets={'eloisa':{'access_token':'fixture'}}),1)
            summary=json.loads(next((self.root/'cli').glob('resumen_*.json')).read_text())
            self.assertEqual(summary['source_periods'],{'eloisa':'30d'})
            self.assertEqual(labs.main(args+['--resume',summary['checkpoint']],secrets={'eloisa':{'access_token':'fixture'}}),1)

    def test_legacy_checkpoint_accepts_equivalent_common_period(self):
        first=labs.run_batch([RUT],'eloisa','6m',DAY,self.root/'legacy',{'eloisa':Fake()})
        resumed=labs.run_batch([RUT],'eloisa','6m',DAY,self.root/'legacy',{},resume=first['checkpoint'],source_periods={'eloisa':'6m'})
        self.assertEqual(resumed['source_periods'],{})

if __name__=='__main__':unittest.main()
