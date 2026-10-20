import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import laboratorios_download as labs
from clinical_jobs import PersistentLauncher
from local_launcher import SERVICES
from test_regression_workflow import Keychain
from test_access import RUT, DAY, exam, pdf

class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.mm = labs.load_backend('mmrad')
    def test_cardio_names_and_noncardiac_ultrasounds(self):
        for name in ('Ecocardiografía Doppler', 'ECOCARDIOGRAMA', 'Ecocardiograma de estrés',
                     'ECHO CARDIOGRAPHY', 'ECO TT', 'ECOTT', 'ETT', 'ECOCARDIO FETAL', 'Doppler cardíaco'):
            with self.subTest(name=name):
                self.assertTrue(self.mm.is_echocardiography({'exam_name':name}))
                self.assertIsNotNone(self.mm.image_exclusion({'exam_name':name,'modality':'US'}))
        for name in ('Ecografía abdominal', 'Doppler carotídeo', 'Ecografía obstétrica', 'Doppler venoso de extremidades'):
            self.assertIsNone(self.mm.image_exclusion({'exam_name':name,'modality':'US'}))
        self.assertFalse(self.mm.is_echocardiography({'exam_name':'Ecografía abdominal','name':'Ett Cardio'}))
    def test_disallowed_types_never_open_viewer(self):
        class Raw:
            def search(self,*a,**kw):
                return [dict(exam(),id='1',modality='US',exam_name='Ecocardiografía'),
                        dict(exam(),id='2',modality='US',exam_name='Ecografía abdominal'),
                        dict(exam(),id='3',modality='CR',exam_name='Tórax')]
            def image_instances(self,e):raise AssertionError('No debe abrirse el visor')
        with tempfile.TemporaryDirectory() as out:
            result=labs.collect_mmrad_images(Raw(),RUT,'6m',DAY,Path(out),list_only=True,image_types=['radiographs'])
            self.assertEqual([e['id'] for e in result['folios']],['3'])
            self.assertEqual(len(result['excluded_images']),2)
    def test_only_selected_noncardiac_studies_download_images(self):
        opened=[];downloaded=[]
        class Raw:
            def search(self,*a,**kw):
                return [dict(exam(),id='1',modality='US',exam_name='Ecocardiografía'),
                        dict(exam(),id='2',modality='US',exam_name='Ecografía abdominal'),
                        dict(exam(),id='3',modality='CR',exam_name='Tórax')]
            def image_instances(self,e):
                opened.append(e['id'])
                return 'https://fixture.test',[dict(study_uid=e['id'],series_uid='1',sop_uid='1')]
            def download_dicom(self,viewer,item):
                downloaded.append(item['study_uid']);return b'fixture-dicom'
        real_load=labs.load_backend
        with tempfile.TemporaryDirectory() as out,patch.object(labs,'load_backend',side_effect=lambda name:self.mm if name=='mmrad' else real_load(name)),patch.object(self.mm,'render_image_pdf',return_value=pdf()),patch.object(labs,'validate_pdf') as validation:
            validation.return_value.pages=[1]
            result=labs.collect_mmrad_images(Raw(),RUT,'6m',DAY,Path(out),image_types=['ultrasounds'])
            self.assertEqual(opened,['2']);self.assertEqual(downloaded,['2'])
            self.assertEqual(result['status'],'complete');self.assertEqual(len(result['files']),1)
            self.assertEqual(len(result['excluded_images']),2)

    def test_metadata_cardio_rejected_before_any_dicom(self):
        client=self.mm.MMRAD()
        row=dict(exam(),modality='US',exam_name='Ecografía',dicom_url=self.mm.BASE+'/UtilServlet?a=3')
        metadata={'studyInstanceUid':'1.2','seriesList':[{'seriesDescription':'ECOCARDIOGRAMA'}]}
        with patch.object(client,'request',return_value='<html>'),patch.object(self.mm,'viewer_from_html',return_value=(self.mm.VIEWER_BASE+'/?x','1.2')),patch.object(client,'viewer_metadata',return_value=metadata),patch.object(client,'download_dicom') as download:
            with self.assertRaises(self.mm.ExcludedStudyImages):client.image_instances(row)
            download.assert_not_called()
    def test_latest_expands_past_echo_and_unselected_modality(self):
        client=self.mm.MMRAD();client.search_action=self.mm.PANEL;client.image_types=('radiographs',)
        rows=[[dict(exam(),id='1',modality='US',exam_name='Ecocardiografía')],
              [dict(exam(),id='2',modality='US',exam_name='Ecografía renal')],
              [dict(exam(),id='3',modality='CR',exam_name='Radiografía de tórax')]]
        with patch.object(client,'request',return_value='<table>') as request,patch.object(self.mm,'parse_exams',side_effect=rows):
            result=client.search(RUT,'latest',DAY,images_only=True)
            self.assertEqual(request.call_count,3);self.assertEqual(result[0]['id'],'3')
    def test_echo_pdf_report_is_still_eligible(self):
        client=self.mm.MMRAD()
        row=dict(exam(),modality='US',exam_name='Ecocardiografía',pdf_url=self.mm.BASE+'/informePDF/7')
        content=pdf()
        with patch.object(client,'request',return_value=content) as request:
            self.assertEqual(client.download(row),content);request.assert_called_once()
    def test_selection_survives_queue_restart(self):
        with tempfile.TemporaryDirectory() as out:
            def queue():return PersistentLauncher(Path(out),sys.executable,Keychain(),Path(__file__),labs,SERVICES,archive_root=Path(out)/'drive',autostart=False)
            q=queue()
            job=q.new_job(dict(ruts=[RUT],source='mmrad',period='6m',schema=2,mmradMode='images',mmradImageTypes=['radiographs']))
            q.close();q=queue()
            try:self.assertEqual(q.jobs[job['id']]['mmrad_image_types'],['radiographs'])
            finally:q.close()
    def test_empty_or_unknown_image_selection_rejected(self):
        with tempfile.TemporaryDirectory() as out:
            q=PersistentLauncher(Path(out),sys.executable,Keychain(),Path(__file__),labs,SERVICES,autostart=False)
            try:
                for types in ([],['CT'],False,{'ultrasounds':True}):
                    with self.subTest(types=types),self.assertRaises(ValueError):
                        q.new_job(dict(ruts=[RUT],source='mmrad',period='6m',mmradMode='images',mmradImageTypes=types))
                result=q.new_job(dict(ruts=[RUT],source='mmrad',period='6m',mmradMode='reports',mmradImageTypes=[]))
                self.assertIn(result['id'],q.jobs)
            finally:q.close()
    def test_changed_image_selection_cannot_reuse_another_request(self):
        class Raw:
            def search(self,*a,**kw):return []
        with tempfile.TemporaryDirectory() as out:
            first=labs.run_batch([RUT],'mmrad','6m',DAY,out,{'mmrad':Raw()},mmrad_mode='images',mmrad_image_types=['radiographs'])
            self.assertEqual(labs.read_progress(first['checkpoint'])['request']['mmrad_image_types'],['radiographs'])
            with self.assertRaises(labs.LabsError):
                labs.run_batch([RUT],'mmrad','6m',DAY,out,{'mmrad':Raw()},mmrad_mode='images',mmrad_image_types=['ultrasounds'],resume=first['checkpoint'])
            same=labs.run_batch([RUT],'mmrad','6m',DAY,out,{'mmrad':Raw()},mmrad_mode='images',mmrad_image_types=['radiographs'],resume=first['checkpoint'])
            self.assertEqual(same['results'][0]['status'],'empty')
if __name__=='__main__':unittest.main()
