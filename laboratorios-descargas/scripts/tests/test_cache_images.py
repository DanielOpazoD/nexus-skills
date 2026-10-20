import io,json,sys,tempfile,unittest,threading,time
from pathlib import Path
from datetime import date
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_access import RUT,DAY,pdf,exam
import laboratorios_download as l
from urllib.error import HTTPError

class Tests(unittest.TestCase):
 def test_etag_requires_authenticated_304_and_valid_cache(self):
  r=l.load_backend('rayen').module
  row={'encounterId':1,'patientIdentifier':RUT,'endPeriod':'2026-10-15'}
  class Response(io.BytesIO):
   headers={'ETag':'"fixture-1"'}
  class Opener:
   def __init__(self):self.requests=[]
   def open(self,req,**kw):
    self.requests.append(req)
    if req.get_header('If-none-match'):raise HTTPError(req.full_url,304,'',{},None)
    return Response(pdf())
  with tempfile.TemporaryDirectory() as out:
   c=r.Client({'token':'fixture-secret','facilityId':77});c.pdf_cache=out;c.opener=Opener()
   first=c.pdf(row);second=c.pdf(row)
   self.assertEqual(first,second);self.assertTrue(c.last_pdf_revalidated)
   self.assertEqual(len(c.opener.requests),2);self.assertEqual(c.opener.requests[-1].get_header('Authorization'),'fixture-secret')
   self.assertNotIn('fixture-secret',''.join(f.read_text() for f in Path(out).glob('*.json')))
   # Un archivo corrupto no permite usar 304 ni saltarse la validación.
   next(Path(out).glob('*.pdf')).write_bytes(b'broken')
   c.pdf(row);self.assertIsNone(c.opener.requests[-1].get_header('If-none-match'))
 def test_images_resume_instances_and_bound_concurrency(self):
  mm=l.load_backend('mmrad');events=[];running=0;peak=0;lock=threading.Lock()
  class Raw:
   fail=True
   def search(self,*a,**kw):return [dict(exam(),modality='US')]
   def image_instances(self,e):return 'https://fixture.test',[{'series_uid':'1','sop_uid':str(i),'study_uid':'7'} for i in (1,2,3)]
   def download_dicom(self,viewer,item):return self.download_dicom_isolated(viewer,item)
   def download_dicom_isolated(self,viewer,item):
    nonlocal running,peak
    with lock:running+=1;peak=max(peak,running);events.append(item['sop_uid'])
    try:
     time.sleep(.01)
     if self.fail and item['sop_uid']=='2':raise mm.MMRADError('fixture')
     return item['sop_uid'].encode()
    finally:
     with lock:running-=1
  raw=Raw();adapter=l.Adapter('mmrad',raw);adapter.image_workers=2
  real_load=l.load_backend
  def load(name):return mm if name=='mmrad' else real_load(name)
  with tempfile.TemporaryDirectory() as out,patch.object(l,'load_backend',side_effect=load),patch.object(mm,'validate_dicom'),patch.object(mm,'render_image_pdf',return_value=pdf()),patch.object(l,'validate_pdf') as validation:
   validation.return_value.pages=[1,2,3]
   first=l.collect_mmrad_images(adapter,RUT,'6m',DAY,Path(out))
   self.assertEqual(first['status'],'error');self.assertEqual(len(first['originals']),1);self.assertFalse(first['files'])
   raw.fail=False
   second=l.collect_mmrad_images(adapter,RUT,'6m',DAY,Path(out))
   self.assertEqual(second['status'],'complete');self.assertEqual(events.count('1'),1);self.assertEqual(peak,2)
 def test_rayen_adapter_filters_egress(self):
  ray=l.load_backend('rayen').Rayen({'token':'fixture','facilityId':77})
  with patch.object(ray.client,'episodes',return_value=([],[])) as episodes:
   ray.search(RUT,'6m',DAY)
   self.assertEqual(episodes.call_args.args[1],date(2026,4,19))
if __name__=='__main__':unittest.main()
