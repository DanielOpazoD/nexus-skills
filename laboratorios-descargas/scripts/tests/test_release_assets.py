import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from package_extension import validate_files

class ReleaseAssetsTests(unittest.TestCase):
    def test_missing_nested_script_or_worker_import_blocks_packaging(self):
        files={'panel/index.html':b'<script src="../request/a.js"></script>','request/a.js':b'',
               'worker.js':b"importScripts('patient_context.js');",'patient_context.js':b''}
        validate_files(files)
        for missing in ('request/a.js','patient_context.js'):
            with self.assertRaises(ValueError):validate_files({key:value for key,value in files.items() if key!=missing})
        with self.assertRaises(ValueError):validate_files({'panel/index.html':b'<iframe src="../../elsewhere.html"></iframe>'})

if __name__=='__main__':unittest.main()
