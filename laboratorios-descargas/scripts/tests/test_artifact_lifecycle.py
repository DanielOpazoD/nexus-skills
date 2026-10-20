"""Recorrido clínico ficticio: parcial → TXT → archivo → reinicio → actualización."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clinical_artifacts as artifacts
import laboratorios_download as labs
from clinical_archive import ArchiveError, CONTROL_FOLDER, READING_FOLDER, digest
from clinical_jobs import PersistentLauncher
from clinical_publication import publish
from local_launcher import SERVICES
from test_access import DAY, Fake, RUT
from test_regression_workflow import Cloud, Keychain, wait_for


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.root = Path(self.temp.name)
        self.drive = self.root/'drive';self.drive.mkdir();self.queues = []
    def tearDown(self):
        for queue in self.queues:queue.close()
        self.temp.cleanup()
    def queue(self, auto=False, cloud=None):
        queue = PersistentLauncher(self.root/'local', sys.executable, Keychain(), Path(__file__).with_name('fake_download.py'),
                                   labs, SERVICES, self.drive, cloud or Cloud(), auto)
        self.queues.append(queue);return queue
    def job(self, queue, source='eloisa', **extra):
        request = queue.new_job(dict(schema=2, ruts=[RUT], source=source, period='6m',
                                    requestId='a'*32, asOf=DAY.isoformat(), **extra))
        job = queue.jobs[request['id']]
        summary = labs.run_batch([RUT], source, '6m', DAY, job['work_output'], {'eloisa':Fake()})
        job.update(checkpoint=summary['checkpoint'], status='attention')
        queue.status(job['id'])
        if not job['pending_sources']:queue.retry(job['id'])
        return job
    def draft(self, job, text=None):
        today = datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y')
        path = Path(job['work_output'])/'borradores'/(today+' Resumen antecedentes.txt')
        path.parent.mkdir(exist_ok=True)
        path.write_text(text or ('Paciente: Paciente Ficticio\nRUT: '+RUT+'\nFecha de elaboración: '+today+
                                '\nFecha de referencia: '+DAY.strftime('%d-%m-%Y')+'\n\nAtención registrada el 15-10-2026.\n'))
        snapshot = artifacts.evidence(job, RUT)
        ref = snapshot['files'][0]
        return dict(version=1, jobId=job['id'], rut=RUT, asOf=job['as_of'], evidenceRevision=snapshot['revision'],
                    createdOn=today, kind='antecedentes', path=str(path),
                    citations=[dict(path=ref['path'], sha256=ref['sha256'], pages=[1], claim='Atención del 15-10-2026.')], notes='')

    def test_full_partial_restart_expired_session_resume_and_new_current(self):
        q = self.queue(True)
        request = q.new_job(dict(schema=2,ruts=[RUT],source='eloisa,rayen',period='6m',requestId='b'*32,asOf=DAY.isoformat()))
        q.provide_sessions({**request,'eloisa':{'access_token':'fixture'}})
        first = wait_for(lambda:(s if (s:=q.status(request['id']))['status']=='attention' and s['files'] else None))
        self.assertEqual(first['artifacts'][0]['status'],'pending')
        job = q.jobs[request['id']];draft = self.draft(job)
        result = q.register_delivery(draft)
        self.assertEqual(result['artifacts'][0]['status'],'archived')
        key = result['key'];sha = digest(result['artifacts'][0]['artifact']['path'])
        self.assertTrue(q.register_delivery(draft)['reused'])
        old_files = {f['sha256'] for f in first['files']}
        q.close();self.queues.remove(q);q = self.queue(True)
        restored = q.status(request['id'])
        self.assertEqual(restored['artifacts'][0]['artifact']['key'],key)
        with self.assertRaises(ValueError):q.provide_sessions({**request,'rayen':{'token':'expired','facilityId':77}})
        fresh = {k:restored[k] for k in ('id','nonce')}
        q.provide_sessions({**fresh,'rayen':{'token':'fixture','facilityId':77}})
        complete = wait_for(lambda:(s if (s:=q.status(request['id']))['status']=='complete' else None))
        self.assertTrue(old_files.issubset({f['sha256'] for f in complete['files']}))
        self.assertEqual(complete['artifacts'][0]['status'],'stale')
        self.assertEqual(digest(complete['artifacts'][0]['artifact']['path']),sha)
        with self.assertRaises(ValueError):q.register_delivery(draft)
        updated = self.draft(q.jobs[request['id']])
        Path(updated['path']).write_text(Path(updated['path']).read_text()+'Epicrisis registrada el 15-10-2026.\n')
        delivered = q.register_delivery(updated)
        self.assertEqual(delivered['artifacts'][0]['status'],'archived')
        folder = self.drive/'Pacientes'/'Paciente Ficticio'
        self.assertEqual(len(list((folder/READING_FOLDER).glob('*Resumen antecedentes*.txt'))),1)
        self.assertEqual(len(list((folder/CONTROL_FOLDER/'Archivo anterior/Entregas/delivery-antecedentes').glob('*.txt'))),1)
        self.assertTrue((folder/CONTROL_FOLDER/'Entregas vigentes.json').exists())

    def test_rejects_wrong_identity_dates_pages_foreign_reference_and_scope(self):
        q = self.queue();job = self.job(q);draft = self.draft(job)
        for change in ({'rut':'22222222-2'}, {'asOf':'2020-01-01'}, {'kind':'epicrisis'}, {'evidenceRevision':'0'*64}):
            with self.subTest(change=change),self.assertRaises(ValueError):q.register_delivery(dict(draft,**change))
        for change in ({'pages':[999]}, {'path':'/tmp/other-patient.pdf'}, {'sha256':'0'*64}, {'pages':[]}):
            bad = copy.deepcopy(draft);bad['citations'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):q.register_delivery(bad)
        original = Path(draft['path']).read_text()
        for text in (original.replace(RUT,'22222222-2'), original.replace('Paciente Ficticio','Otro Paciente'),
                     original.replace('15-10-2026','31-02-2026'), original.replace('15-10-2026','2026-10-15'),
                     original.replace('15-10-2026','15/10/2026'), original.replace('15-10-2026','1-10-2026'),
                     original.split('\n\n')[0],
                     original.replace('RUT: '+RUT,'RUT: 22222222-2')+'\nMédico: Paciente Ficticio\nRUT: '+RUT+'\n'):
            Path(draft['path']).write_text(text)
            with self.assertRaises(ValueError):q.register_delivery(draft)
        self.assertEqual(artifacts.load(job)['artifacts'],[])

    def test_no_evidence_produces_identified_local_txt_without_inventing_name(self):
        q=self.queue(True)
        request=q.new_job(dict(schema=2,ruts=[RUT],source='eloisa',period='6m',requestId='b'*32,asOf=DAY.isoformat()))
        wait_for(lambda:q.status(request['id'])['status']=='waiting')
        job=q.jobs[request['id']]
        today=datetime.now(ZoneInfo('Pacific/Easter')).strftime('%d-%m-%Y')
        path=Path(job['work_output'])/'borradores'/(today+' Resumen antecedentes.txt');path.parent.mkdir()
        path.write_text('Paciente: Nombre no disponible\nRUT: '+RUT+'\nFecha de elaboración: '+today+
                        '\nFecha de referencia: '+DAY.strftime('%d-%m-%Y')+'\n\nNo se obtuvo documentación clínica verificable para elaborar antecedentes en esta corrida.\n')
        data=dict(version=1,jobId=job['id'],rut=RUT,asOf=job['as_of'],createdOn=today,kind='antecedentes',
                  evidenceRevision=artifacts.evidence(job,RUT)['revision'],path=str(path),citations=[],notes='Nombre pendiente de verificar.')
        result=q.register_delivery(data)
        self.assertEqual(result['artifacts'][0]['status'],'verified')
        self.assertFalse(list((self.drive/'Pacientes').glob('*')))
        self.assertNotEqual(q.status(job['id'])['fulfillment'],'complete')

    def test_additional_requested_docx_uses_same_validation_without_replacing_baseline(self):
        import zipfile
        q=self.queue();job=self.job(q,deliveryModel='custom',deliveryInstructions='Informe breve')
        baseline=self.draft(job);q.register_delivery(baseline)
        path=Path(job['work_output'])/('Informe - '+baseline['createdOn']+'.docx')
        from xml.sax.saxutils import escape
        paragraphs=['Paciente: Paciente Ficticio','RUT: '+RUT,'Atención registrada el 15-10-2026. Documento adicional solicitado.']
        xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+''.join('<w:p><w:r><w:t>'+escape(p)+'</w:t></w:r></w:p>' for p in paragraphs)+'</w:body></w:document>'
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('word/document.xml',xml)
            archive.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
            archive.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        additional=dict(baseline,kind='custom',path=str(path))
        result=q.register_delivery(additional)
        self.assertEqual([r['status'] for r in result['artifacts']],['archived','archived'])
        self.assertEqual(q.status(job['id'])['fulfillment'],'complete')
        self.assertEqual(q.status(job['id'])['delivery']['status'],'archived')

    def test_corrupt_delivery_registry_preserved_and_cloud_pending_stays_explicit(self):
        class Offline:
            def verify(self,*args):return {'status':'pending'}
        q=self.queue(cloud=Offline());job=self.job(q);result=q.register_delivery(self.draft(job))
        self.assertEqual(result['artifacts'][0]['status'],'archived')
        self.assertEqual(q.status(job['id'])['archive']['sync'],'pending')
        ledger=artifacts.ledger_path(job);ledger.write_text('{broken')
        state=q.status(job['id'])['artifacts'][0]
        self.assertEqual(state['status'],'modified');self.assertIn('revisión',state['reason'])
        self.assertEqual(ledger.read_text(),'{broken')

    def test_cli_http_registration_origin_and_download_hash_are_enforced(self):
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from local_launcher import Handler
        from register_delivery import submit
        q=self.queue();job=self.job(q);draft=self.draft(job)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.launcher=q
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        port=server.server_port;base=f'http://127.0.0.1:{port}'
        try:
            request=Request(base+'/api/delivery/register',data=json.dumps(draft).encode(),headers={'Origin':'https://other.invalid'})
            with self.assertRaises(HTTPError) as rejected:urlopen(request)
            self.assertEqual(rejected.exception.code,403)
            first=submit(draft,port);self.assertFalse(first['reused']);self.assertTrue(submit(draft,port)['reused'])
            sha=first['artifacts'][0]['artifact']['path_sha256']
            url=base+'/api/artifact?id='+job['id']+'&index=0&sha256='+sha
            with urlopen(url) as response:self.assertEqual(response.read(),Path(draft['path']).read_bytes())
            Path(first['artifacts'][0]['artifact']['path']).write_text('Modified')
            with self.assertRaises(HTTPError) as modified:urlopen(url)
            self.assertEqual(modified.exception.code,404)
        finally:server.shutdown();server.server_close();thread.join()

    def test_registered_copy_modification_and_pending_cloud_do_not_claim_completion(self):
        q = self.queue();job = self.job(q);draft = self.draft(job)
        result = q.register_delivery(draft);record = result['artifacts'][0]['artifact']
        Path(record['path']).write_text('Edited')
        self.assertEqual(q.status(job['id'])['artifacts'][0]['status'],'modified')
        self.assertTrue(Path(record['support']).exists())
        # La copia de Drive también se revalida, no basta el estado persistido.
        Path(record['path']).write_bytes(Path(draft['path']).read_bytes())
        reading = next((self.drive/'Pacientes'/'Paciente Ficticio'/READING_FOLDER).glob('*.txt'))
        reading.write_text('Edición manual del usuario')
        status = q.status(job['id'])['artifacts'][0]
        self.assertEqual(status['status'],'verified')
        self.assertIn('modificada',status['reason'])
        q.verify_archive(job['id'])
        self.assertEqual(reading.read_text(),'Edición manual del usuario')

    def test_validates_exact_bytes_published_even_if_draft_changes_while_reading(self):
        q=self.queue();job=self.job(q);draft=self.draft(job)
        original=Path(draft['path']).read_bytes();reader=artifacts.text_of
        def edited(path,content=None):
            Path(path).write_bytes(original.replace(RUT.encode(),b'22222222-2'))
            return reader(path,content)
        with patch('clinical_artifacts.text_of',side_effect=edited):result=q.register_delivery(draft)
        self.assertEqual(Path(result['artifacts'][0]['artifact']['path']).read_bytes(),original)
        self.assertEqual(result['artifacts'][0]['status'],'archived')

    def test_registration_persists_before_failed_archive_and_recovers(self):
        q = self.queue();job = self.job(q);draft = self.draft(job)
        self.drive.rename(self.root/'offline')
        result = q.register_delivery(draft)
        self.assertEqual(result['artifacts'][0]['status'],'verified')
        q.close();self.queues.remove(q)
        (self.root/'offline').rename(self.drive)
        q = self.queue();q.verify_archive(job['id'])
        self.assertEqual(q.status(job['id'])['artifacts'][0]['status'],'archived')

    def test_other_patient_cannot_supply_identity_or_evidence(self):
        q = self.queue();job = self.job(q)
        job['ruts'].append('22222222-2')
        self.assertIsNone(artifacts.evidence(job,'22222222-2')['name'])
        self.assertEqual(artifacts.evidence(job,'22222222-2')['files'],[])

    def test_name_order_and_accents_do_not_hide_a_real_identity_conflict(self):
        q=self.queue();job=self.job(q)
        original=copy.deepcopy(job['summary'][0])
        job['summary'][0]['patient_name']='Ángela Pérez Soto'
        alternate=dict(original,source='exalab',patient_name='PEREZ SOTO, ANGELA')
        job['summary'].append(alternate)
        self.assertEqual(artifacts.evidence(job,RUT)['name'],'Ángela Pérez Soto')
        alternate['patient_name']='Otra Persona Distinta'
        self.assertIsNone(artifacts.evidence(job,RUT)['name'])

    def test_publication_old_order_never_replaces_new_or_moves_unknown_files(self):
        folder = self.drive/'patient';folder.mkdir()
        source = self.root/'document.txt';source.write_text('new')
        new = dict(id='new',as_of='2026-10-20',started_at='2026-10-20T12:00:00-05:00')
        a,_,_ = publish(source,folder,digest(source),'delivery-antecedentes',new)
        unknown = folder/READING_FOLDER/'Otra edición.txt';unknown.write_text('Manual')
        source.write_text('old')
        b,_,_ = publish(source,folder,digest(source),'delivery-antecedentes',dict(new,id='old',as_of='2026-10-19'))
        self.assertEqual(a.read_text(),'new');self.assertIn('Archivo anterior',str(b));self.assertTrue(unknown.exists())

    def test_retirement_recovers_after_interruption(self):
        folder = self.drive/'patient';folder.mkdir();source = self.root/'document.txt';source.write_text('first')
        job = dict(id='new',as_of='2026-10-20',started_at='2026-10-20T12:00:00-05:00')
        first,_,_ = publish(source,folder,digest(source),'delivery-antecedentes',job)
        source.write_text('second')
        with patch('clinical_publication.publish_without_replace',side_effect=OSError('Interruption')):
            with self.assertRaises(OSError):publish(source,folder,digest(source),'delivery-antecedentes',job)
        publish(source,folder,digest(source),'delivery-antecedentes',job)
        self.assertFalse(first.exists())
        self.assertEqual(len(list((folder/READING_FOLDER).glob('*.txt'))),1)


if __name__ == '__main__':unittest.main()
