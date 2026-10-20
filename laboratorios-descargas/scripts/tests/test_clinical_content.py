"""Patient-safe content projection, partial hospital flow and portable delivery contract."""
import copy,json,sys,tempfile,unittest
from datetime import date,datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.parse import parse_qs,urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laboratorios_download as labs
from clinical_content import normalize_source_content
from clinical_delivery import selection,handoff
from portable_request import parse,download_args
from test_access import RUT,DAY,Fake,pdf
import test_delivery_periods as delivery_tests
from test_regression_workflow import wait_for
import test_portable_request as portable_tests
from pypdf import PdfReader

class ContentTests(unittest.TestCase):
    def setUp(self):
        self.e=labs.load_backend('eloisa');self.r=labs.load_backend('rayen')
    def visit(self,profession='Médico'):
        return {'Id':1,'RutPaciente':RUT,'Fecha':'20261015 120000','TipoDeAtencion':'Control',
            'FuncionariosPrestadores':[{'NombreInstrumento':profession}],
            'Anamnesis':[{'HistoriaEnfermedadActual':'EVOLUCION_SECRETA'}],
            'Recetas':[{'Descripcion':'RECETA_FICTICIA'}],
            'SolicitudesInterconsulta':[{'Descripcion':'DERIVACION_FICTICIA'}]}
    def client(self,content,rows):
        client=self.e.Eloisa({'access_token':'fixture'},content=content)
        client.request=Mock(side_effect=[{'Rut':RUT,'Id':88,'NombreFormateado':'Paciente Ficticio'},rows])
        return client
    def test_default_medical_plus_prescriptions_and_referrals_independent_of_profession(self):
        rows=[self.visit(),dict(self.visit('Enfermera'),Id=2)]
        client=self.client(['medical','prescriptions','referrals'],rows)
        found=client.search(RUT,date(2026,10,19),date(2026,1,1))
        self.assertEqual(len(found),2);self.assertIn('Anamnesis',found[0]['raw']);self.assertNotIn('Anamnesis',found[1]['raw'])
        text=' '.join(p.extract_text() for p in PdfReader(BytesIO(client.download(found[1]))).pages)
        self.assertNotIn('EVOLUCION_SECRETA',text);self.assertIn('RECETA_FICTICIA',text);self.assertIn('DERIVACION_FICTICIA',text)
        self.assertIn('Anamnesis',rows[1]) # Never mutate upstream data.
    def test_other_only_and_structured_categories_do_not_leak(self):
        client=self.client(['other'],[self.visit(),dict(self.visit('Enfermera'),Id=2)])
        found=client.search(RUT,date(2026,10,19),date(2026,1,1));self.assertEqual([r['id'] for r in found],['2'])
        self.assertNotIn('Recetas',found[0]['raw']);self.assertNotIn('SolicitudesInterconsulta',found[0]['raw'])
    def test_unknown_profession_pending_and_identity_checked_even_excluded(self):
        c=self.client(['medical'],[self.visit('Sin dato')]);self.assertEqual(c.search(RUT,DAY,date(2026,1,1)),[]);self.assertTrue(c.pending_records)
        mixed=self.visit();mixed['FuncionariosPrestadores'].append({'NombreInstrumento':'Enfermera'})
        c=self.client(['medical'],[mixed]);self.assertEqual(c.search(RUT,DAY,date(2026,1,1)),[]);self.assertTrue(c.pending_records)
        c=self.client(['medical'],[dict(self.visit('Enfermera'),RutPaciente='22222222-2')])
        with self.assertRaises(self.e.EloisaError):c.search(RUT,DAY,date(2026,1,1))
    def test_validation_and_resume_reject_changed_contents(self):
        for v in ([],{'his':['medical']},{'eloisa':[]},{'eloisa':['unknown']},{'eloisa':['medical','medical']}):
            with self.assertRaises(ValueError):normalize_source_content(v,['eloisa'])
        with tempfile.TemporaryDirectory() as tmp:
            first=labs.run_batch([RUT],'eloisa','6m',DAY,tmp,{'eloisa':Fake()},source_content={'eloisa':['medical']})
            with self.assertRaises(labs.LabsError):labs.run_batch([RUT],'eloisa','6m',DAY,tmp,{},resume=first['checkpoint'],source_content={'eloisa':['other']})
    def row(self):
        return dict(encounterId=1,patientId=9,facilityId=77,patientIdentifierTypeId=2,patientIdentifier=RUT,patientName='Paciente Ficticio',startPeriod='2026-10-01T12:00:00Z',endPeriod='2026-10-15T12:00:00Z')
    def test_history_contract_only_own_run_and_overlapping_episode(self):
        requests=[]
        row=self.row();row['startPeriod']='2025-01-01T12:00:00Z';row['endPeriod']=None
        def transport(req):requests.append(req);return json.dumps([row]).encode()
        client=self.r.module.Client({'token':'fixture','facilityId':77},transport=transport)
        found,pending=client.episodes(RUT,date(2026,10,1),DAY,history=True)
        self.assertEqual(len(found),1);self.assertFalse(pending)
        parsed=urlsplit(requests[0].full_url);q=parse_qs(parsed.query)
        self.assertEqual(parsed.path,'/api/inpatientReport/getEncounterHistoryReport');self.assertEqual(q['prefferedPeridentId'],['2'])
        url=self.r.history_viewer_url(row,DAY);params=json.loads(parse_qs(urlsplit(url).query)['params'][0])
        self.assertEqual(params['enc_id'],'1');self.assertNotIn('fixture',url)
        row['patientIdentifierTypeId']=4
        with self.assertRaises(self.r.module.ReportError):client.episodes(RUT,date(2026,10,1),DAY,history=True)
    def test_full_record_is_pending_preserves_epicrisis_and_partial_failure(self):
        for record_fails in (False,True):
            client=self.r.Rayen({'token':'fixture','facilityId':77},content=['epicrisis','record'])
            def episodes(rut,start,end,history=False):
                if history and record_fails:raise self.r.module.SourceUnavailable('Fuente temporalmente indisponible')
                return [self.row()],[]
            client.client.episodes=episodes;client.client.pdf=lambda row:pdf('rayen','1')
            with tempfile.TemporaryDirectory() as tmp:
                result=labs.run_batch([RUT],'rayen','6m',DAY,tmp,{'rayen':labs.Adapter('rayen',client)},source_content={'rayen':['epicrisis','record']})['results'][0]
                self.assertEqual(result['status'],'partial',result);self.assertEqual(len(result['files']),2)
                self.assertIn(result['reading_pdf'],result['files'])
                self.assertEqual(result['unavailable_records'][0]['report_type'],'record')
                if not record_fails:self.assertIn('viewer_url',result['unavailable_records'][0])
    def test_record_only_does_not_download_unrequested_epicrisis(self):
        client=self.r.Rayen({'token':'fixture','facilityId':77},content=['record'])
        client.client.episodes=Mock(return_value=([self.row()],[]));client.client.pdf=Mock()
        self.assertEqual(client.search(RUT,'6m',DAY),[]);self.assertTrue(client.pending_records);client.client.pdf.assert_not_called()
        self.assertTrue(client.client.episodes.call_args.kwargs['history'])
    def test_v2_free_output_and_v1_compatibility(self):
        packet=portable_tests.PortableRequestTests().packet();packet['request'].update(sourceContent={'eloisa':['prescriptions'],'rayen':['record']},deliveryModel='custom',deliveryInstructions='Lista breve\ncon fuentes y fechas.')
        checked=parse(json.dumps(packet));self.assertIn('--source-content',download_args(checked));self.assertEqual(checked['request']['deliveryInstructions'],'Lista breve\ncon fuentes y fechas.')
        with self.assertRaises(ValueError):selection('custom',' ')
        with self.assertRaises(ValueError):selection('custom','x'*2001)
        legacy=copy.deepcopy(packet);legacy['version']=1;legacy['request'].pop('emailAccount',None);legacy['request'].pop('sourceContent');legacy['request'].pop('deliveryInstructions');legacy['request']['deliveryModel']='documents'
        self.assertEqual(parse(json.dumps(legacy))['version'],1)

class QueueContentTests(unittest.TestCase):
    setUp=delivery_tests.DeliveryPeriodTests.setUp
    tearDown=delivery_tests.DeliveryPeriodTests.tearDown
    queue=delivery_tests.DeliveryPeriodTests.queue
    request=delivery_tests.DeliveryPeriodTests.request
    # Reuse isolated queue helpers without inheriting unrelated test methods.
    def test_custom_content_survives_worker_and_restart(self):
        q=self.queue(True);job=q.new_job(self.request(sourceContent={'eloisa':['prescriptions']},deliveryModel='custom',deliveryInstructions='Una lista breve, con fechas.'))
        q.provide_sessions({**job,'eloisa':{'access_token':'fixture'}})
        status=wait_for(lambda:(v if (v:=q.status(job['id']))['status']=='attention' and v['files'] else None))
        self.assertEqual(status['source_content'],{'eloisa':['prescriptions']});self.assertEqual(status['delivery']['status'],'codex_pending')
        cp=json.loads(Path(q.jobs[job['id']]['checkpoint']).read_text());self.assertEqual(cp['request']['source_content'],{'eloisa':['prescriptions']})
        prompt=q.delivery_request(job['id'])['prompt'];self.assertIn('Una lista breve, con fechas.',prompt);self.assertNotIn('plantilla del usuario está pendiente',prompt)
        q.close();self.queues.remove(q);restored=self.queue();self.assertEqual(restored.status(job['id'])['delivery']['instructions'],'Una lista breve, con fechas.')
