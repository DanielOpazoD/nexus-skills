"""Portable contract and calendar boundaries, with synthetic identities only."""
import json,subprocess,sys,tempfile,unittest
from datetime import date,datetime,timedelta
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laboratorios_download as labs
from portable_request import parse,download_args
from test_access import Fake,RUT,exam

class PortableRequestTests(unittest.TestCase):
    def packet(self):
        script=Path(__file__).resolve().parents[2]/'assets/request_packet.js'
        node="const p=require(process.argv[1]);console.log(p.prompt(p.build(JSON.parse(process.argv[2]),new Date('2026-10-20T01:00:00Z'),'a'.repeat(32))));"
        req=dict(schema=2,ruts=[RUT],source='eloisa,rayen,mmrad',period='3m',sourcePeriods={'rayen':'10y'},deliveryModel='documents',eloisaScope='todos',mmradMode='images',mmradImageTypes=['radiographs'],merge=False,patientMerge=True,credentials={'password':'must-not-export'})
        text=subprocess.check_output(['node','-e',node,str(script),json.dumps(req)],text=True)
        self.assertNotIn('must-not-export',text)
        self.assertIn('19-10-2026',text)
        return parse(text)
    def test_browser_packet_to_python_keeps_complete_request(self):
        packet=self.packet();args=download_args(packet)
        self.assertEqual(packet['asOf'],'2026-10-19')
        self.assertEqual(packet['request']['deliveryModel'],'documents')
        for flag,value in {'--period':'3m','--source-periods':'{"rayen": "10y"}','--as-of':'2026-10-19','--source':'eloisa,rayen,mmrad','--mmrad-mode':'images','--mmrad-image-types':'radiographs','--eloisa-scope':'todos'}.items():
            self.assertEqual(args[args.index(flag)+1],value)
        self.assertIn('--patient-merge',args);self.assertNotIn('--merge',args)
    def test_mail_v3_account_period_and_legacy_v2(self):
        packet=self.packet();packet['request'].update(source='email',sourceContent={},sourcePeriods={'email':'10y'})
        decoded=parse(json.dumps(packet));args=download_args(decoded)
        self.assertEqual(decoded['version'],4);self.assertEqual(args[args.index('--email-account')+1],'daniel.opazo@hospitalhangaroa.cl')
        packet['version']=2;packet['request'].pop('emailAccount')
        with self.assertRaises(ValueError):parse(json.dumps(packet))
        packet['request'].update(source='rayen',sourcePeriods={})
        self.assertEqual(parse(json.dumps(packet))['version'],2)

    def test_modified_or_ambiguous_requests_rejected(self):
        p=self.packet()
        for key,value in [('period','20y'),('sourcePeriods',{'his':'10y'}),('ruts',['11111111-2']),('deliveryModel','inventado'),('merge','yes'),('mmradImageTypes',[])]:
            q=json.loads(json.dumps(p));q['request'][key]=value
            with self.subTest(key=key),self.assertRaises((ValueError,labs.LabsError)):parse(json.dumps(q))
        q=dict(p,credentials={})
        with self.assertRaises(ValueError):parse(json.dumps(q))
        with self.assertRaises(ValueError):parse('{"kind":"one","kind":"two"}')
        p['asOf']='2026-02-30'
        with self.assertRaises(ValueError):parse(json.dumps(p))
    def test_month_end_and_decade_bounds_in_both_labs(self):
        for source in ('syslab','exalab'):
            mod=labs.load_backend(source)
            for period,today,cutoff in [('3m',date(2024,5,31),date(2024,2,29)),('10y',date(2024,2,29),date(2014,2,28))]:
                days=[cutoff-timedelta(days=1),cutoff,today,today+timedelta(days=1)]
                rows=[dict(exam(str(i)),datetime=datetime.combine(day,datetime.min.time())) for i,day in enumerate(days)]
                with self.subTest(source=source,period=period):
                    self.assertEqual([r['id'] for r in mod.select_exams(rows,period,today)],['2','1'])
    def test_api_date_windows_for_eloisa_rayen_mmrad(self):
        today=date(2024,2,29)
        for period,start in [('3m',date(2023,11,29)),('10y',date(2014,2,28))]:
            client=Mock();client.search.return_value=[]
            adapter=labs.Adapter('eloisa',client);adapter.today=today;adapter.period=period;adapter.bounded_dates=True;adapter.search(RUT)
            client.search.assert_called_once_with(RUT,today=today,since=start)
            rayen=labs.load_backend('rayen').Rayen.__new__(labs.load_backend('rayen').Rayen)
            rayen.client=Mock();rayen.client.episodes.return_value=([],[]);rayen.search(RUT,period,today)
            rayen.client.episodes.assert_called_once_with(RUT,start,today)
            self.assertEqual(labs.load_backend('mmrad').date_filters(period,today),(start.strftime('%d/%m/%Y'),'29/02/2024'))
    def test_packet_periods_drive_real_filter_and_checkpoint(self):
        packet=self.packet();req=packet['request']
        class History(Fake):
            def search(self,rut):return [dict(exam(),datetime=datetime(2018,10,19))]
        with tempfile.TemporaryDirectory() as temp:
            result=labs.run_batch(req['ruts'],'eloisa,rayen',req['period'],date.fromisoformat(packet['asOf']),Path(temp),{'eloisa':History(),'rayen':History()},list_only=True,source_periods=req['sourcePeriods'])
            rows={r['source']:r for r in result['results']}
            self.assertEqual(len(rows['rayen']['folios']),1);self.assertEqual(rows['eloisa']['folios'],[])
            checkpoint=json.loads(Path(result['checkpoint']).read_text())
            self.assertEqual(checkpoint['request']['as_of'],packet['asOf'])
            self.assertEqual(checkpoint['request']['source_periods'],{'rayen':'10y'})

if __name__=='__main__':unittest.main()
