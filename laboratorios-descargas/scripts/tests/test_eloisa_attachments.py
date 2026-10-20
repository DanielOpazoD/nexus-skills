"""Synthetic attachments: patient/episode, original bytes, partial/resume and archive."""
import copy,io,json,sys,tempfile,unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laboratorios_download as labs
from clinical_content import DEFAULTS,normalize_source_content,CATALOG
from clinical_archive import PatientArchive
from test_access import RUT,DAY,Fake,exam,pdf
from test_regression_workflow import Cloud
import test_clinical_content as content_tests
import test_portable_request as portable_tests
from portable_request import parse
from reportlab.pdfgen.canvas import Canvas
eloisa=labs.load_backend('eloisa')
import eloisa_attachments as att

def original(rut=RUT,name='Paciente Ficticio',extra='',episode=None):
    stream=io.BytesIO();c=Canvas(stream)
    for i,line in enumerate(['NOMBRE: '+name,'DIAGNOSTICO: prueba. RUT: '+rut,'FECHA: 15/10/26',extra]+(['ID de atención: '+episode] if episode else [])):
        c.drawString(30,800-i*20,line)
    c.save();return stream.getvalue()

def client(content=('medical','attachments'),bad=False):
    row=content_tests.ContentTests().visit();row['ArchivosAdjunto']=[{'NombreArchivo':'Informe.pdf','PathAzure':'archivo.pdf'}]
    c=eloisa.Eloisa({'access_token':'synthetic'},content=list(content))
    c.request=Mock(side_effect=[{'Id':88,'Rut':RUT,'NombreFormateado':'Paciente Ficticio'},[row]])
    c.original_download=c.download
    c.download=lambda e: (_ for _ in ()).throw(att.AttachmentError('Adjunto pendiente')) if e.get('validation') and bad else original() if e.get('validation') else c.original_download(e)
    return c

class AttachmentTests(unittest.TestCase):
    def item(self):return client(['attachments']).search(RUT,DAY,date(2026,1,1))[0]
    def test_defaults_explicit_selection_and_old_contract(self):
        self.assertIn('attachments',DEFAULTS['eloisa'])
        for content in (['medical'],['prescriptions'],None):
            c=client(content or ['medical']);c.content=content
            self.assertFalse(any(e.get('validation') for e in c.search(RUT,DAY,date(2026,1,1))))
        self.assertEqual(len(client(['attachments']).search(RUT,DAY,date(2026,1,1))),1)
        p=portable_tests.PortableRequestTests().packet();p['request']['sourceContent']={'eloisa':['attachments'],'mmrad':['ct_reports']};p['request']['mmradMode']='both'
        self.assertEqual(parse(json.dumps(p))['version'],4)
        p['version']=3
        with self.assertRaises(ValueError):parse(json.dumps(p))
        self.assertEqual(normalize_source_content(None,['eloisa']),{})
    def test_identity_requires_patient_header_and_episode_when_present(self):
        context=self.item()['validation'];self.assertEqual(len(att.validate(original(),RUT,context).pages),1)
        for data in [original('22222222-2',extra='Profesional: RUT: '+RUT),original(name='Otra Persona'),original(episode='999'),pdf(),b'%PDF-truncated']:
            with self.subTest(data=data[:20]),self.assertRaises(att.AttachmentError):att.validate(data,RUT,context)
        # A provider RUT in its own labelled block must not identify the patient.
        provider=io.BytesIO();c=Canvas(provider);c.drawString(30,800,'NOMBRE: Paciente Ficticio');c.drawString(30,780,'Profesional: RUT: '+RUT);c.save()
        with self.assertRaises(att.AttachmentError):att.validate(provider.getvalue(),RUT,context)
        att.validate(original(extra='Profesional: RUT: 22222222-2'),RUT,context)
        for role in ('Medico tratante','Responsable','Familiar'):
            data=io.BytesIO();c=Canvas(data);c.drawString(30,800,'NOMBRE: Paciente Ficticio');c.drawString(30,780,role+': RUT: '+RUT);c.save()
            with self.assertRaises(att.AttachmentError):att.validate(data.getvalue(),RUT,context)
    def test_parent_binding_dedup_non_pdf_and_unknown_profession(self):
        row=content_tests.ContentTests().visit('Sin dato');a={'NombreArchivo':'a.pdf','PathAzure':'a.pdf'};row['ArchivosAdjunto']=[a,a,dict(a,IdUsuario=99),dict(a,PathAzure='b.pdf',IdAtencion=99),{'NombreArchivo':'imagen.jpg','PathAzure':'imagen.jpg'}]
        found,pending=att.enumerate_attachments(row,88,5576,RUT,'Paciente Ficticio',exam()['datetime'])
        self.assertEqual(len(found),1);self.assertEqual(len(pending),3)
    def test_signed_urls_patient_origin_and_secret_free_errors(self):
        token={'connection':'https://example.blob.core.windows.net/88?ignored','sas':'?sig=synthetic&sp=r'}
        value=att.signed_url(token,'informe prueba.pdf',88);self.assertIn('/88/informe%20prueba.pdf?',value)
        self.assertEqual(att.signed_url(token,'https://example.blob.core.windows.net/88/a.pdf',88),'https://example.blob.core.windows.net/88/a.pdf?sig=synthetic&sp=r')
        for path in ['https://evil.test/88/a.pdf','https://example.blob.core.windows.net/99/a.pdf','../a.pdf','%2e%2e/a.pdf','%252e%252e/a.pdf','a.pdf?token=secret','//evil.test/a.pdf','a\\b.pdf']:
            with self.subTest(path=path),self.assertRaises(att.AttachmentError):att.signed_url(token,path,88)
        bad=dict(token,connection='https://example.blob.core.windows.net/99')
        with self.assertRaises(att.AttachmentError):att.signed_url(bad,'a.pdf',88)
    def test_download_has_no_bearer_and_sanitizes_signed_error(self):
        item=self.item();c=Mock();c.request.return_value={'connection':'https://example.blob.core.windows.net/88','sas':'sig=private-signature'}
        def opened(request,**kw):
            self.assertNotIn('Authorization',request.headers)
            raise HTTPError(request.full_url,403,'expired',{},None)
        c.attachment_opener.open.side_effect=opened
        with self.assertRaises(att.AttachmentError) as caught:att.download(c,item)
        self.assertNotIn('private-signature',str(caught.exception));self.assertIn('403',str(caught.exception))
        c.request.assert_called_once_with('/API/api/rayen/Autentificacion/TokenGestorDocumento/88/5576')
    def test_end_to_end_original_merge_archive_and_failed_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'local';drive=root/'drive';drive.mkdir()
            c=client();bytes_=original();old=c.download;c.download=lambda e:bytes_ if e.get('validation') else old(e)
            kwargs=dict(source_content={'eloisa':['medical','attachments']},merge=True)
            first=labs.run_batch([RUT],'eloisa','6m',DAY,output,{'eloisa':labs.Adapter('eloisa',c)},**kwargs)
            row=first['results'][0];self.assertEqual(row['status'],'complete',row);self.assertEqual(len(row['files']),3);self.assertEqual(row['attachment_count'],1)
            self.assertIn(row['reading_pdf'],row['files'])
            reading=labs.pdf_library()[0](Path(row['reading_pdf']))
            self.assertEqual(len(reading.pages),1,'El adjunto no debe entrar en el PDF de atenciones.')
            original_file=next(Path(f) for f in row['files'] if 'Documentos adjuntos' in f);self.assertEqual(original_file.read_bytes(),bytes_)
            archived=PatientArchive(output,drive,Cloud()).archive(first);self.assertEqual(archived['status'],'complete',archived)
            self.assertTrue(any(Path(f['path']).read_bytes()==bytes_ for f in archived['files'] if f['path'].endswith('.pdf')))
            cached_client=client();cached_client.download=Mock(side_effect=AssertionError('No redescargar bytes verificados.'))
            cached=labs.run_batch([RUT],'eloisa','6m',DAY,output,{'eloisa':labs.Adapter('eloisa',cached_client)},resume=first['checkpoint'],**kwargs)
            self.assertEqual(cached['results'][0]['status'],'complete');cached_client.download.assert_not_called()
            retry=labs.run_batch([RUT],'eloisa','6m',DAY,output,{},resume=first['checkpoint'],**kwargs)
            self.assertIn(str(original_file),retry['results'][0]['files']);self.assertEqual(retry['results'][0]['freshness'],'update_pending')
            original_file.write_bytes(b'changed')
            cached=next((Path(first['checkpoint']).parent/'originales').rglob('*-*.pdf'));cached.write_bytes(b'changed')
            retry=labs.run_batch([RUT],'eloisa','6m',DAY,output,{},resume=first['checkpoint'],**kwargs)
            self.assertNotIn(str(original_file),retry['results'][0]['files'])
    def test_attachment_failure_preserves_visits_and_other_source(self):
        with tempfile.TemporaryDirectory() as out:
            result=labs.run_batch([RUT],'eloisa,his','6m',DAY,out,{'eloisa':labs.Adapter('eloisa',client(bad=True)),'his':Fake(source='his')},source_content={'eloisa':['medical','attachments']})
            self.assertEqual([r['status'] for r in result['results']],['partial','complete']);self.assertEqual(len(result['results'][0]['files']),2)
            self.assertIn('PARCIAL',Path(result['results'][0]['reading_pdf']).name)
    def test_mmrad_ct_only_does_not_request_radiograph_or_echo_reports(self):
        class Images(Fake):
            def search(self,rut):return [dict(exam(str(n)),modality=m,pdf_url='https://example.test/pdf') for n,m in enumerate(['CR','US','CT'],1)]
        with tempfile.TemporaryDirectory() as tmp:
            c=Images();c.download=Mock(return_value=pdf())
            summary=labs.run_batch([RUT],'mmrad','6m',DAY,tmp,{'mmrad':c},source_content={'mmrad':['ct_reports']})
            self.assertEqual(summary['results'][0]['status'],'complete');self.assertEqual(c.download.call_args.args[0]['modality'],'CT');self.assertEqual(c.download.call_count,1)

    def test_latest_keeps_all_attachments_of_selected_visit(self):
        c=client(['attachments']);visit=content_tests.ContentTests().visit()
        visit['ArchivosAdjunto']=[{'NombreArchivo':name+'.pdf','PathAzure':name+'.pdf'} for name in ('one','two')]
        c.request=Mock(side_effect=[{'Id':88,'Rut':RUT,'NombreFormateado':'Paciente Ficticio'},[visit]])
        with tempfile.TemporaryDirectory() as tmp:
            row=labs.run_batch([RUT],'eloisa','latest',DAY,tmp,{'eloisa':labs.Adapter('eloisa',c)},source_content={'eloisa':['attachments']})['results'][0]
            self.assertEqual(row['status'],'complete');self.assertEqual(len(row['files']),2);self.assertEqual(len(set(row['completed_folios'])),2)
    def test_ct_scope_expands_latest_window_and_rejects_conflicting_products(self):
        from unittest.mock import patch
        from clinical_content import validate_products
        with self.assertRaises(ValueError):validate_products({'mmrad':['ct_reports']},'images')
        mm=labs.load_backend('mmrad');c=mm.MMRAD();c.search_action=mm.PANEL;c.content=['ct_reports']
        rows=[[dict(exam(),modality='US',pdf_url='fixture')],[dict(exam(),modality='CR',pdf_url='fixture')],[dict(exam(),modality='CT',pdf_url='fixture')]]
        with patch.object(c,'request',return_value='<table>') as request,patch.object(mm,'parse_exams',side_effect=rows):
            self.assertEqual(c.search(RUT,'latest',DAY,reports_only=True)[0]['modality'],'CT');self.assertEqual(request.call_count,3)
