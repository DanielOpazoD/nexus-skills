"""Proceso de integración sin red. Comparte el motor y los PDF ficticios reales."""
import argparse,json,sys,time
from datetime import date,datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laboratorios_download as labs
from test_access import Fake,exam,pdf
p=argparse.ArgumentParser();p.add_argument('--source');p.add_argument('--email-account',default='daniel.opazo@hospitalhangaroa.cl');p.add_argument('--ready-sources');p.add_argument('--ruts',nargs='+');p.add_argument('--period');p.add_argument('--as-of');p.add_argument('--output');p.add_argument('--resume');p.add_argument('--retry-sources');p.add_argument('--eloisa-scope');p.add_argument('--mmrad-mode');p.add_argument('--merge',action='store_true');p.add_argument('--patient-merge',action='store_true');p.add_argument('--session-stdin',action='store_true');p.add_argument('--source-content',default='{}');p.add_argument('--source-periods',default='{}');p.add_argument('--mmrad-image-types',default='radiographs,ultrasounds');p.add_argument('--cache-dir');a=p.parse_args()
secrets=json.load(sys.stdin)
class Fixture(Fake):
    def search(self,rut):
        self.rut=rut
        if self.source=='rayen' and secrets[self.source].get('token')=='slow':return [exam('1'),dict(exam('2'),datetime=datetime(2026,10,14))]
        return [exam()]
    def download(self,e):
        if e['id']=='2':time.sleep(60)
        return pdf(self.source,e['id'])
clients={s:Fixture(source=s) for s in secrets}
try:
    summary=labs.run_batch(a.ruts,a.source,a.period,date.fromisoformat(a.as_of or labs.read_progress(a.resume)['request']['as_of']),a.output,clients,
        merge=a.merge,patient_merge=a.patient_merge,eloisa_scope=a.eloisa_scope,mmrad_mode=a.mmrad_mode,resume=a.resume,retry_sources=a.retry_sources,source_content=json.loads(a.source_content),source_periods=json.loads(a.source_periods),mmrad_image_types=a.mmrad_image_types,email_account=a.email_account)
    path=Path(a.output)/'resumen-fixture.json';path.write_text(json.dumps(summary));print('Resumen: '+str(path),flush=True)
except KeyboardInterrupt:sys.exit(130)
