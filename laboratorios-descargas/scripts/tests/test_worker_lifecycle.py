import json,subprocess,sys,tempfile,time,unittest
from pathlib import Path
class WorkerLifecycleTests(unittest.TestCase):
    def test_orphan_stops_when_launcher_disappears(self):
        worker=Path(__file__).resolve().parents[1]/'clinical_worker.py'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);marker=root/'running';log=root/'worker.log';target=root/'target.py'
            target.write_text('from pathlib import Path\nimport time\nPath('+repr(str(marker))+').write_text("ready")\ntime.sleep(15)\n')
            parent=root/'parent.py'
            parent.write_text('import os,subprocess,sys,time\nfrom pathlib import Path\nwith open('+repr(str(log))+',"w") as log:\n subprocess.Popen([sys.executable,'+repr(str(worker))+',str(os.getpid()),'+repr(str(target))+'],stdout=log,stderr=log)\n deadline=time.monotonic()+3\n while not Path('+repr(str(marker))+').exists() and time.monotonic()<deadline:time.sleep(.02)\nos._exit(0)\n')
            completed=subprocess.run([sys.executable,str(parent)],timeout=5)
            self.assertEqual(completed.returncode,0)
            until=time.monotonic()+3
            while time.monotonic()<until and 'Interrumpido' not in log.read_text():time.sleep(.05)
            self.assertIn('Interrumpido; avance conservado.',log.read_text())
if __name__=='__main__':unittest.main()
