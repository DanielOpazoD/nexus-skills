"""Biblioteca con identidades ficticias; no lee el Drive real."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from clinical_archive import ArchiveError
from clinical_library import ClinicalLibrary, RULES, document_identity, filename_date, same_name
from clinical_publication import publish,note_evidence
from clinical_archive import digest
from test_access import pdf

RUT='11111111-1';NAME='Paciente Ficticio'
TEXT='Paciente: '+NAME+'\nRUT: '+RUT+'\nFecha de elaboración: 20-10-2026\nFecha de referencia: 19-10-2026\n\nAntecedentes documentados el 15-10-2026.\n'

class LibraryTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.library=ClinicalLibrary(self.root)
    def tearDown(self):self.temp.cleanup()
    def patient(self,name=NAME,rut=RUT,suffix=''):
        folder=self.root/'Pacientes'/(name+suffix);control=folder/RULES['controlFolder'];control.mkdir(parents=True)
        (control/RULES['identityFilename']).write_text('Paciente: '+name+'\nRUT: '+rut+'\n')
        reading=folder/RULES['readingFolder'];reading.mkdir();return folder,reading
    def test_shared_identity_and_filename_cases(self):
        fixtures=json.loads(Path(__file__).with_name('library_cases.json').read_text())
        for case in fixtures['identities']:
            try:
                name,rut=document_identity(case['text'],case['name']);valid=rut==case['rut'] and same_name(name,case['name'])
            except (ValueError,ArchiveError):valid=False
            with self.subTest(case=case['text'][:25]):self.assertEqual(valid,case['valid'])
        for case in fixtures['filenames']:self.assertEqual(filename_date(case['name']),case['date'])
    def test_only_clinical_txt_is_listed_and_read_rechecks_bytes(self):
        folder,reading=self.patient();path=reading/'20-10-2026 Resumen antecedentes.txt';path.write_text(TEXT)
        (reading/'20-10-2026 Sustento Resumen antecedentes.txt').write_text('Control')
        (reading/'Resumen de fuentes - 20-10-2026.txt').write_text('Control')
        catalog=self.library.list();document=catalog['patients'][0]['documents'][0]
        self.assertEqual(len(catalog['patients'][0]['documents']),1)
        result=self.library.read(document['id'],document['sha256']);self.assertEqual(result['text'],TEXT)
        self.assertFalse(any('path' in d for p in catalog['patients'] for d in p['documents']))
        path.write_text(TEXT+'Cambio\n')
        with self.assertRaises(ValueError):self.library.read(document['id'],document['sha256'])
    def test_current_manifest_selects_exact_version_and_exports_staleness(self):
        folder,reading=self.patient();path=reading/'20-10-2026 Resumen antecedentes.txt';path.write_text(TEXT)
        (reading/'19-10-2026 Resumen antecedentes.txt').write_text(TEXT)
        manifest=folder/RULES['controlFolder']/RULES['manifestFilename']
        data={'version':1,'products':{'delivery-antecedentes':{'current':{'path':str(path.relative_to(folder)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'freshness':'stale'}}}}
        manifest.write_text(json.dumps(data));catalog=self.library.list();docs=catalog['patients'][0]['documents']
        self.assertEqual(len(docs),1);self.assertEqual(docs[0]['status'],'stale')
        path.write_text(TEXT+'Edición\n');self.assertEqual(self.library.list()['patients'][0]['documents'],[])
    def test_legacy_header_and_identity_controls_remain_useful(self):
        folder,reading=self.patient();control=folder/RULES['controlFolder'];(control/RULES['identityFilename']).unlink()
        (control/'Estado de descargas - 19-10-2026.txt').write_text('Paciente: '+NAME+'\nRUT: '+RUT+'\nFecha: 19-10-2026')
        legacy=NAME+'\nRUT 11.111.111-1\n\nAntecedentes documentados.'
        (reading/'Resumen de antecedentes.txt').write_text(legacy)
        docs=self.library.list()['patients'][0]['documents'];self.assertEqual(len(docs),1)
        self.assertEqual(self.library.read(docs[0]['id'],docs[0]['sha256'])['text'],legacy)
        (control/'Estado de descargas - 20-10-2026.txt').write_text('Paciente: '+NAME+'\nRUT: 22222222-2\n')
        self.assertEqual(self.library.list()['patients'],[])
    def test_wrong_header_and_symlink_never_mix_patients(self):
        _,reading=self.patient();outside=self.root/'outside.txt';outside.write_text(TEXT)
        (reading/'20-10-2026 Resumen antecedentes.txt').symlink_to(outside)
        (reading/'Resumen de antecedentes.txt').write_text(TEXT.replace(RUT,'22222222-2'))
        self.assertEqual(self.library.list()['patients'][0]['documents'],[])
    def test_duplicates_blocked_homonyms_retained_and_root_not_created(self):
        self.patient();self.patient(rut='22222222-2',suffix=' (2)')
        self.assertEqual(len(self.library.list()['patients']),2)
        self.patient(suffix=' (3)');self.assertEqual(len(self.library.list()['patients']),1)
        missing=self.root/'missing';self.assertFalse(ClinicalLibrary(missing).list()['available']);self.assertFalse(missing.exists())
    def test_invalid_date_and_corrupt_manifest_do_not_discard_other_patients(self):
        folder,reading=self.patient();(reading/'31-02-2026 Resumen antecedentes.txt').write_text(TEXT)
        second,second_reading=self.patient(name='Otra Persona',rut='22222222-2')
        (second_reading/'Resumen de antecedentes.txt').write_text(TEXT.replace(NAME,'Otra Persona').replace(RUT,'22222222-2'))
        (folder/RULES['controlFolder']/RULES['manifestFilename']).write_text('{broken')
        catalog=self.library.list();self.assertEqual(len(catalog['patients']),1);self.assertGreater(catalog['issues'],0)
    def test_folder_open_is_explicit_and_rechecks_identity_without_accepting_a_path(self):
        folder,_=self.patient();catalog=self.library.list();ident=catalog['patients'][0]['id'];calls=[]
        self.library.open(ident,runner=lambda args,**kwargs:calls.append(args))
        self.assertEqual(calls,[['/usr/bin/open',str(folder/RULES['readingFolder'])]])
        with self.assertRaises(ValueError):self.library.open('../outside',runner=lambda *args:None)
        (folder/RULES['controlFolder']/RULES['identityFilename']).write_text('Paciente: '+NAME+'\nRUT: 22222222-2\n')
        with self.assertRaises(ValueError):self.library.open(ident,runner=lambda *args:None)
    def test_new_source_invalidates_prior_summary_and_replay_cannot_restore_freshness(self):
        folder,reading=self.patient();source=self.root/'source.pdf';source.write_bytes(pdf())
        draft=self.root/'20-10-2026 Resumen antecedentes.txt';draft.write_text(TEXT)
        old=dict(id='old',as_of='2026-10-20',started_at='2026-10-20T10:00:00+00:00')
        new=dict(id='new',as_of='2026-10-20',started_at='2026-10-20T11:00:00+00:00')
        publish(source,folder,digest(source),'source-eloisa',old)
        publish(draft,folder,digest(draft),'delivery-antecedentes',old,revision='revision-1')
        self.assertEqual(self.library.list()['patients'][0]['documents'][0]['status'],'current')
        publish(source,folder,digest(source),'source-eloisa',new)
        self.assertEqual(self.library.list()['patients'][0]['documents'][0]['status'],'current')
        source.write_bytes(pdf(id='2'));publish(source,folder,digest(source),'source-eloisa',new)
        self.assertEqual(self.library.list()['patients'][0]['documents'][0]['status'],'stale')
        publish(draft,folder,digest(draft),'delivery-antecedentes',old,revision='revision-1')
        self.assertEqual(self.library.list()['patients'][0]['documents'][0]['status'],'stale')
        publish(draft,folder,digest(draft),'delivery-antecedentes',new,revision='revision-2')
        self.assertEqual(self.library.list()['patients'][0]['documents'][0]['status'],'current')
    def test_new_attachment_bytes_alone_invalidate_summary_and_identical_copy_does_not(self):
        folder,_=self.patient();draft=self.root/'20-10-2026 Resumen antecedentes.txt';draft.write_text(TEXT)
        job=dict(id='job',as_of='2026-10-20',started_at='2026-10-20T10:00:00+00:00')
        note_evidence(folder,{'a'*64});publish(draft,folder,digest(draft),'delivery-antecedentes',job,revision='one')
        note_evidence(folder,{'a'*64});self.assertEqual(self.library.list()['patients'][0]['documents'][0]['status'],'current')
        note_evidence(folder,{'b'*64});self.assertEqual(self.library.list()['patients'][0]['documents'][0]['status'],'stale')

if __name__=='__main__':unittest.main()
