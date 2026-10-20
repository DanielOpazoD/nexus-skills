"""API de apertura ficticia: origen, nonce y carpeta verificada; nunca abre Finder."""
import json,sys,tempfile,threading,unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from clinical_library import ClinicalLibrary
from local_launcher import Handler
from clinical_archive import PatientArchive,CONTROL_FOLDER

class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.folder=self.root/'Pacientes/Paciente Ficticio';control=self.folder/CONTROL_FOLDER;control.mkdir(parents=True)
        (control/'Identidad del paciente.txt').write_text('Paciente: Paciente Ficticio\nRUT: 11111111-1\n')
        (self.folder/'Lectura y entregas').mkdir();self.library=ClinicalLibrary(self.root)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.server.launcher=SimpleNamespace(library=lambda:self.library,library_nonce='a'*43,labs=SimpleNamespace(LabsError=RuntimeError))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def post(self,body,origin):
        return urlopen(Request(self.base+'/api/library/open',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':origin}),timeout=3)
    def test_only_current_nonce_and_allowed_origin_can_open_an_identified_folder(self):
        with urlopen(self.base+'/api/library') as response:catalog=json.load(response)
        body=dict(id=catalog['patients'][0]['id'],token=catalog['openToken'])
        with patch('clinical_library.subprocess.run') as opened:
            for changed,origin in ((body,'https://other.invalid'),({**body,'token':'b'*43},self.base),({**body,'id':'../outside'},self.base)):
                with self.assertRaises(HTTPError):self.post(changed,origin)
            self.assertEqual(opened.call_count,0)
            with self.post(body,'chrome-extension://'+'a'*32) as response:self.assertTrue(json.load(response)['opened'])
            self.assertEqual(opened.call_count,1);self.assertEqual(opened.call_args.args[0],['/usr/bin/open',str(self.folder/'Lectura y entregas')])
    def test_web_folder_metadata_requires_a_confirmed_cloud_ancestor(self):
        archive=PatientArchive(self.root,self.root);target=self.folder/CONTROL_FOLDER/'Carpeta Drive.json'
        for remote in ({'status':'pending','patient_folder_id':'folder-fixture-123'},{'status':'confirmed','patient_folder_id':'https://evil.invalid/'}):
            archive.remember_link(self.folder,'11111111-1','Paciente Ficticio',remote)
            self.assertFalse(target.exists())
        archive.remember_link(self.folder,'11111111-1','Paciente Ficticio',dict(status='confirmed',patient_folder_id='folder-fixture-123'))
        self.assertEqual(json.loads(target.read_text())['rut'],'11111111-1')

if __name__=='__main__':unittest.main()
