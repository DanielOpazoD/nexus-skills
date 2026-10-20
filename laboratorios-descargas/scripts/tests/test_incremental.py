"""Revalidación con servidores ficticios; no conecta portales."""
import hashlib,io,json,sys,tempfile,unittest
from http.client import HTTPMessage
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request
from reportlab.pdfgen.canvas import Canvas
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laboratorios_download as labs
from clinical_incremental import Cache,CachedResponse,fingerprint
from test_access import RUT,DAY,exam,pdf


class IncrementalTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.cache=Cache(self.root/'cache')
    def tearDown(self):self.temp.cleanup()
    def syslab_fixture(self,patient=RUT):
        out=io.BytesIO();canvas=Canvas(out)
        canvas.drawString(30,800,'Paciente Ficticio')
        canvas.drawString(30,780,'Rut / Fic: '+patient)
        canvas.drawString(30,760,'Numero: 1');canvas.save()
        body=out.getvalue();url='http://example.invalid/folio'
        class Server:
            def __init__(self):self.calls=[]
            def open(self,request,timeout=None):
                self.calls.append(request)
                if request.get_header('If-none-match')=='"syslab-fixture"':
                    raise HTTPError(url,304,'not modified',{},None)
                return CachedResponse(body,url,{'ETag':'"syslab-fixture"'})
        class Syslab:
            def __init__(self):self.opener=Server();self.searched=[]
            def search(self,rut):
                self.searched.append(rut)
                return [dict(exam(),rut=rut,url=url)]
            def request(self,path,pdf=False):
                request=Request(path);request.nexo_pdf=pdf
                with self.opener.open(request) as response:return response.read()
        return Syslab()
    def test_syslab_body_search_uses_full_requested_rut_for_cached_pdf_validation(self):
        client=self.syslab_fixture();adapter=labs.Adapter('syslab',client)
        first=labs.run_batch([RUT],'syslab','1y',DAY,self.root/'syslab-one',{'syslab':adapter},cache_dir=self.root/'cache')
        self.assertEqual(first['results'][0]['status'],'complete')
        second=labs.run_batch([RUT],'syslab','6m',DAY,self.root/'syslab-two',{'syslab':adapter},cache_dir=self.root/'cache')
        self.assertEqual(second['results'][0]['status'],'complete')
        self.assertEqual(second['results'][0]['retrieval']['revalidated'],1)
        self.assertEqual(client.searched,[RUT.split('-')[0]]*2)
        self.assertEqual(len(client.opener.calls),2)
    def test_syslab_cache_still_rejects_pdf_with_other_patient_rut(self):
        client=self.syslab_fixture('22222222-2')
        result=labs.run_batch([RUT],'syslab','1y',DAY,self.root/'syslab-wrong',{'syslab':labs.Adapter('syslab',client)},cache_dir=self.root/'cache')['results'][0]
        self.assertEqual(result['status'],'error');self.assertEqual(result['files'],[])
        self.assertFalse(list((self.root/'cache').rglob('*.pdf')))
    def test_structured_new_request_reuses_only_same_patient_content_and_scope(self):
        class Clinical:
            scope='medicos';content=['medical'];node_id=1
            def __init__(self):self.searches=0;self.downloads=0;self.raw={'text':'Dato ficticio'}
            def search(self,*args,**kwargs):self.searches+=1;return [dict(exam(),raw=self.raw)]
            def download(self,row):self.downloads+=1;return pdf()
        client=Clinical();adapter=labs.Adapter('eloisa',client)
        first=labs.run_batch([RUT],'eloisa','1y',DAY,self.root/'one',{'eloisa':adapter},cache_dir=self.root/'cache')
        second=labs.run_batch([RUT],'eloisa','6m',DAY,self.root/'two',{'eloisa':adapter},cache_dir=self.root/'cache')
        self.assertEqual(client.searches,2);self.assertEqual(client.downloads,1);self.assertEqual(second['results'][0]['retrieval']['reused'],1)
        self.assertTrue(Path(first['results'][0]['files'][0]).exists())
        client.raw={'text':'Dato corregido'}
        labs.run_batch([RUT],'eloisa','6m',DAY,self.root/'three',{'eloisa':adapter},cache_dir=self.root/'cache')
        self.assertEqual(client.downloads,2)
        client.content=['medical','prescriptions']
        labs.run_batch([RUT],'eloisa','6m',DAY,self.root/'four',{'eloisa':adapter},cache_dir=self.root/'cache')
        self.assertEqual(client.downloads,3)
        labs.run_batch([RUT],'eloisa','6m',DAY,self.root/'five',{'eloisa':adapter},cache_dir=self.root/'cache',fresh=True)
        self.assertEqual(client.downloads,4)
    def http_fixture(self,headers=None):
        content=pdf();url='https://example.invalid/report?token=FICTION_SECRET'
        class Server:
            def __init__(self):self.calls=[];self.error=None;self.body=content;self.headers=headers if headers is not None else {'ETag':'"v1"'}
            def open(self,request,timeout=None):
                self.calls.append(request)
                if self.error:raise self.error
                if request.get_header('If-none-match')==self.headers.get('ETag') and self.headers.get('ETag'):
                    h=HTTPMessage();h['Set-Cookie']='fixture=yes; Path=/'
                    raise HTTPError(url,304,'not modified',h,None)
                return CachedResponse(self.body,url,self.headers)
        server=Server();client=type('Client',(),{})();client.opener=server
        def download():
            request=Request(url);request.nexo_pdf=True
            with client.opener.open(request,timeout=3) as response:
                CookieJar().extract_cookies(response,request)
                return response.read()
        validate=lambda content:labs.validate_pdf(content,RUT,'1','eloisa')
        return client,server,download,validate
    def test_http_200_then_304_rechecks_identity_and_keeps_authenticated_request(self):
        client,server,download,validate=self.http_fixture();ctx={'rut':RUT,'id':'1'}
        one=self.cache.http(client,ctx,download,validate);two=self.cache.http(client,ctx,download,validate)
        self.assertEqual(one,two);self.assertEqual(len(server.calls),2);self.assertEqual(self.cache.metrics['revalidated'],1)
        self.assertIs(client.opener,server)
        for path in self.cache.root.glob('*.json'):self.assertNotIn('FICTION_SECRET',path.read_text())
    def test_modified_report_and_other_patient_cannot_reuse_old_bytes(self):
        client,server,download,validate=self.http_fixture();ctx={'rut':RUT,'id':'1'}
        self.cache.http(client,ctx,download,validate);server.headers={'ETag':'"v2"'};server.body=pdf(id='2')
        with self.assertRaises(labs.LabsError):self.cache.http(client,ctx,download,validate)
        self.assertEqual(self.cache.metrics['revalidated'],0)
        server.body=pdf()
        other=lambda content:labs.validate_pdf(content,'22222222-2','1','eloisa')
        with self.assertRaises(labs.LabsError):self.cache.http(client,{'rut':'22222222-2','id':'1'},download,other)
        self.assertIsNone(server.calls[-1].get_header('If-none-match'))
    def test_auth_network_errors_never_fall_back_to_cached_report(self):
        for error in (HTTPError('https://example.invalid/report',401,'expired',{},None),URLError('offline')):
            client,server,download,validate=self.http_fixture();self.cache.http(client,{},download,validate);server.error=error
            with self.assertRaises(type(error)):self.cache.http(client,{},download,validate)
            self.assertIs(client.opener,server)
    def test_corrupt_bytes_are_not_sent_as_conditional_candidate(self):
        client,server,download,validate=self.http_fixture();self.cache.http(client,{},download,validate)
        next(self.cache.root.glob('*.pdf')).write_bytes(b'changed')
        self.cache.http(client,{},download,validate);self.assertIsNone(server.calls[-1].get_header('If-none-match'))
    def test_no_validator_no_store_and_vary_disable_http_reuse(self):
        for index,headers in enumerate(({}, {'ETag':'"v1"','Cache-Control':'no-store'},{'ETag':'"v1"','Vary':'Cookie'})):
            cache=Cache(self.root/str(index));client,server,download,validate=self.http_fixture(headers)
            cache.http(client,{},download,validate);cache.http(client,{},download,validate)
            self.assertIsNone(server.calls[-1].get_header('If-none-match'));self.assertEqual(cache.metrics['revalidated'],0)
    def test_attachment_metadata_alone_never_authorizes_structured_reuse(self):
        class Attachment:
            def download(self,exam):return b'original'
        adapter=labs.Adapter('eloisa',Attachment());adapter.incremental=self.cache
        self.assertEqual(adapter.download(dict(exam(),validation={'kind':'attachment'})),b'original')
        self.assertEqual(self.cache.metrics['reused'],0)

if __name__=='__main__':unittest.main()
