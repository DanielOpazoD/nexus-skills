import io,json,sys,tempfile,unittest,time
from datetime import date,datetime
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request
from urllib.error import HTTPError,URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laboratorios_download as l
from clinical_transport import ReliableOpener,SourceUnavailable
from reportlab.pdfgen.canvas import Canvas
RUT='11111111-1';DAY=date(2026,10,19)
def pdf(source='eloisa',id='1'):
 out=io.BytesIO(); c=Canvas(out);c.drawString(30,800,'Paciente Ficticio RUN: '+RUT);c.drawString(30,780,'ID de atención: '+id);c.drawString(30,760,'Fecha egreso: 15/10/2026');c.save();return out.getvalue()
def exam(id='1'):
 return {'id':id,'datetime':datetime(2026,10,15),'rut':RUT,'name':'Paciente Ficticio','fingerprint':'fixture'}
class Fake:
 def __init__(self,events=None,source='eloisa',fail=False):self.events=events if events is not None else [];self.source=source;self.fail=fail;self.pending_records=[]
 def search(self,rut):
  self.events.append(self.source)
  if self.fail:raise SourceUnavailable('Temporal')
  return [exam()]
 def download(self,e):return pdf(self.source,e['id'])
class Tests(unittest.TestCase):
 def test_reading_copy_is_newest_first_and_named_by_included_dates(self):
  class Visits(Fake):
   def search(self,rut):
    return [dict(exam('1'),datetime=datetime(2026,3,12)),
            dict(exam('2'),datetime=datetime(2026,9,4))]
  with tempfile.TemporaryDirectory() as out:
   row=l.run_batch([RUT],'eloisa','1y',DAY,out,{'eloisa':Visits()})['results'][0]
   self.assertEqual(row['status'],'complete')
   reading=Path(row['reading_pdf']);self.assertEqual(reading.name,'Eloisa ambulatorio Marzo-Sept 2026.pdf')
   reader=l.pdf_library()[0](io.BytesIO(reading.read_bytes()))
   self.assertEqual(len(reader.pages),2)
   self.assertIn('ID de atención: 2',reader.pages[0].extract_text())
   self.assertIn('ID de atención: 1',reader.pages[1].extract_text())
   self.assertEqual(l.reading_pdf_stem('syslab',[datetime(2026,3,1),datetime(2026,9,1)]),'LAB HHR Marzo-Sept 2026')
   self.assertEqual(l.reading_pdf_stem('exalab',[datetime(2025,12,1),datetime(2026,1,1)],True),'LAB HDS Diciembre 2025-Enero 2026 - PARCIAL')
 def test_retry_after_and_no_auth_retry(self):
  class Opener:
   def __init__(self,code):self.n=0;self.code=code
   def open(self,*a,**kw):
    self.n+=1
    if self.n==1:raise HTTPError('https://example.test',self.code,'',{'Retry-After':'2'},None)
    return 'ok'
  raw=Opener(503);sleeps=[];wrapped=ReliableOpener(raw,sleep=sleeps.append)
  self.assertEqual(wrapped.open(Request('https://example.test')),'ok');self.assertEqual(sleeps,[2]);self.assertEqual(raw.n,2)
  raw=Opener(401)
  with self.assertRaises(HTTPError):ReliableOpener(raw).open(Request('https://example.test'))
  self.assertEqual(raw.n,1)
 def test_long_delay_and_login_no_retry(self):
  class Bad:
   def __init__(self):self.n=0
   def open(self,*a,**kw):self.n+=1;raise HTTPError('https://example.test',503,'',{'Retry-After':'120'},None)
  raw=Bad()
  with self.assertRaises(SourceUnavailable):ReliableOpener(raw,sleep=lambda _:self.fail('No esperar')).open(Request('https://example.test'))
  self.assertEqual(raw.n,1)
  raw=Bad()
  with self.assertRaises(SourceUnavailable):ReliableOpener(raw).open(Request('https://example.test',data=b'login'))
  self.assertEqual(raw.n,1)
 def test_circuit_limits_requests(self):
  class Bad:
   n=0
   def open(self,*a,**kw):self.n+=1;raise URLError('fixture')
  raw=Bad();wrapped=ReliableOpener(raw,sleep=lambda _:None)
  for _ in range(3):
   with self.assertRaises(SourceUnavailable):wrapped.open(Request('https://example.test'))
  self.assertEqual(raw.n,4)
 def test_all_and_both(self):
  self.assertIn('rayen',l.selected_sources('all'));self.assertEqual(l.selected_sources('both'),['syslab','exalab'])
 def test_partial_and_retry_only_one_source(self):
  with tempfile.TemporaryDirectory() as out:
   good=Fake();bad=Fake(source='his',fail=True)
   first=l.run_batch([RUT],'eloisa,his','6m',DAY,out,{'eloisa':good,'his':bad})
   self.assertEqual(first['results'][0]['status'],'complete');self.assertTrue(Path(first['results'][0]['files'][0]).exists())
   fresh=Fake(source='his')
   second=l.run_batch([RUT],'eloisa,his','6m',DAY,out,{'his':fresh},resume=first['checkpoint'],retry_sources='his')
   self.assertEqual(len(good.events),1);self.assertTrue(all(r['status']=='complete' for r in second['results']))
 def test_failed_source_not_requeried_for_next_patient(self):
  bad=Fake(source='his',fail=True)
  with tempfile.TemporaryDirectory() as out:
   result=l.run_batch([RUT,'22222222-2'],'his','6m',DAY,out,{'his':bad})
   self.assertEqual(len(bad.events),1);self.assertTrue(all(r['status']=='error' for r in result['results']))
 def test_rayen_pending_is_not_empty(self):
  class Pending(Fake):
   def search(self,rut):self.pending_records=[{'episode':3,'reason':'Sin fecha'}];return []
  with tempfile.TemporaryDirectory() as out:
   result=l.run_batch([RUT],'rayen','6m',DAY,out,{'rayen':Pending()})
   self.assertEqual(result['results'][0]['status'],'partial')
 def test_rayen_integrates_patient_pdf(self):
  with tempfile.TemporaryDirectory() as out:
   result=l.run_batch([RUT],'eloisa,rayen','6m',DAY,out,{'eloisa':Fake(),'rayen':Fake(source='rayen')},patient_merge=True)
   self.assertEqual(result['patient_pdfs'][0]['pages'],2)
 def test_merge_failure_delivers_individuals(self):
  with tempfile.TemporaryDirectory() as out,patch.object(l,'merge_reports',side_effect=ValueError('fixture')):
   result=l.run_batch([RUT],'eloisa','6m',DAY,out,{'eloisa':Fake()},merge=True)['results'][0]
   self.assertEqual(result['status'],'partial');self.assertEqual(len(result['files']),1);self.assertTrue(Path(result['files'][0]).exists())
 def test_images_are_after_reports(self):
  events=[]
  def images(*args,**kw):events.append('images');return {'rut':args[1],'source':'mmrad_images','status':'empty','folios':[],'files':[],'pages':0,'errors':[]}
  with tempfile.TemporaryDirectory() as out,patch.object(l,'collect_mmrad_images',side_effect=images):
   l.run_batch([RUT,'22222222-2'],'eloisa,mmrad','6m',DAY,out,{'eloisa':Fake(events),'mmrad':Fake(events,'mmrad')},mmrad_mode='both')
  self.assertEqual(events[-2:],['images','images']);self.assertEqual(events.count('eloisa'),2)
 def test_bounded_dates_sent_only_when_enabled(self):
  class Client:
   def search(self,rut,**kw):return kw
  a=l.Adapter('eloisa',Client());a.period='6m';a.today=DAY
  self.assertIsNone(a.search(RUT)['since']);a.bounded_dates=True
  self.assertEqual(a.search(RUT)['since'],date(2026,4,19))
 def test_changed_original_preserves_previous(self):
  with tempfile.TemporaryDirectory() as out:
   state=l.Progress(Path(out),{'fixture':True})
   with state.locked():
    state.put(RUT,'eloisa',exam(),pdf(),1);state.put(RUT,'eloisa',exam(),pdf()+b'\n',1)
    self.assertEqual(len(list(state.path.parent.rglob('versiones/*.pdf'))),1)
if __name__=='__main__':unittest.main()
