"""Solicitudes inválidas no crean órdenes ni acceden a credenciales."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_regression_workflow import WorkflowTests
from test_access import RUT
import laboratorios_download as labs
from portable_request import parse
from clinical_request import decode_json

class RequestContractTests(unittest.TestCase):
    setUp=WorkflowTests.setUp
    tearDown=WorkflowTests.tearDown
    queue=WorkflowTests.queue
    request=WorkflowTests.request
    def test_local_rejects_ambiguous_options_before_side_effects(self):
        q=self.queue()
        invalid=[{'merge':'true'},{'patientMerge':1},{'remember':'yes'},
                 {'schema':True},{'schema':3},{'schema':'2'}, {'peroid':'10y'},
                 {'asOf':'2020-01-01'}, {'mmradImageTypes':'radiographs'},
                 {'mmradImageTypes':['radiographs','radiographs']}, {'sourceContent':None},
                 {'sourcePeriods':None}, {'credentials':[]}, {'credentials':{'unknown':{}}}]
        for extra in invalid:
            with self.subTest(extra=extra),patch.object(q.keychain,'get') as read,patch.object(q.keychain,'put') as write:
                before=q.store.read_bytes()
                request=self.request('syslab');request.update(extra)
                with self.assertRaises((ValueError,labs.LabsError)):q.new_job(request)
                self.assertEqual(q.jobs,{})
                self.assertEqual(q.store.read_bytes(),before)
                read.assert_not_called();write.assert_not_called()
    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        for text in ('{"merge":false,"merge":true}', '{"sourceContent":{"eloisa":[],"eloisa":["attachments"]}}', '{"schema":NaN}'):
            with self.subTest(text=text),self.assertRaises(ValueError):decode_json(text)

    def packet(self,req):
        return dict(kind='hhr-clinical-request',version=4,id='a'*32,target='mac-mini',timeZone='Pacific/Easter',asOf='2026-10-19',request=dict(schema=2,ruts=[RUT],source='eloisa',period='6m',sourcePeriods={},sourceContent={},deliveryModel='documents',deliveryInstructions='',emailAccount='daniel.opazo@hospitalhangaroa.cl',eloisaScope='medicos',mmradMode='reports',mmradImageTypes=[],merge=False,patientMerge=False,**req))
    def test_portable_rejects_null_and_duplicate_collections(self):
        for key,value in [('sourceContent',None),('sourcePeriods',None),('mmradImageTypes',['radiographs','radiographs'])]:
            packet=self.packet({});packet['request'][key]=value
            with self.subTest(key=key),self.assertRaises((ValueError,labs.LabsError)):parse(json.dumps(packet))
    def test_current_local_and_portable_selections_are_equivalent(self):
        packet=self.packet({});packet['request'].update(source='eloisa,mmrad',sourceContent={'eloisa':['attachments'],'mmrad':['ct_reports']},sourcePeriods={'eloisa':'3m'},mmradMode='both',mmradImageTypes=['radiographs'],merge=True,deliveryModel='custom',deliveryInstructions='  Resumen breve  ')
        req=parse(json.dumps(packet))['request'];q=self.queue();ident=q.new_job(copy.deepcopy(req))['id'];job=q.jobs[ident]
        for key,field in [('sourceContent','source_content'),('sourcePeriods','source_periods'),('merge','merge'),('patientMerge','patient_merge'),('mmradImageTypes','mmrad_image_types')]:self.assertEqual(job[field],req[key])
        self.assertEqual(job['delivery']['instructions'],'Resumen breve')

del WorkflowTests
if __name__=='__main__':unittest.main()
