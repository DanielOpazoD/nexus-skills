"""Instalación fallida y compatibilidad real de PDF/DICOM en el entorno fijado."""
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import setup_runtime
import laboratorios_download as labs
from test_access import RUT, DAY


class InstallationTests(unittest.TestCase):
    def test_existing_non_environment_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            valuable = Path(folder) / 'conservar.txt'
            valuable.write_text('ficticio')
            with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
                setup_runtime.main(['--venv', folder])
            self.assertEqual(valuable.read_text(), 'ficticio')
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_failed_verification_does_not_enable_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'runtime'
            with patch.object(setup_runtime.venv.EnvBuilder, 'create'), patch.object(setup_runtime.subprocess, 'run') as run:
                run.side_effect = [None, subprocess.CalledProcessError(1, 'verify')]
                self.assertEqual(setup_runtime.main(['--venv', str(target)]), 1)
            self.assertFalse((target / 'runtime.ok').exists())

    def test_altered_wheel_is_rejected_before_enabling_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'runtime'
            wheel = root / 'hhr_fixture-1.0-py3-none-any.whl'
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('hhr_fixture/__init__.py', '')
                archive.writestr('hhr_fixture-1.0.dist-info/METADATA', 'Metadata-Version: 2.1\nName: hhr-fixture\nVersion: 1.0\n')
                archive.writestr('hhr_fixture-1.0.dist-info/WHEEL', 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
                archive.writestr('hhr_fixture-1.0.dist-info/RECORD', '')
            lock = root / 'requirements.lock'
            lock.write_text('hhr-fixture==1.0 --hash=sha256:' + '0' * 64 + '\n')
            with patch.object(setup_runtime, 'LOCK', lock):
                self.assertEqual(setup_runtime.main(['--venv', str(target), '--wheelhouse', folder]), 1)
            self.assertFalse((target / 'runtime.ok').exists())
            self.assertFalse(any((target / 'lib').rglob('hhr_fixture/__init__.py')))

    def test_uncompressed_synthetic_dicom_to_pdf_uses_real_dependencies(self):
        import numpy as np
        import pydicom
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage
        from pypdf import PdfReader
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.SOPClassUID = SecondaryCaptureImageStorage
        ds.SOPInstanceUID = '1.2.826.0.1.3680043.10.543.3'
        ds.StudyInstanceUID = '1.2.826.0.1.3680043.10.543.1'
        ds.SeriesInstanceUID = '1.2.826.0.1.3680043.10.543.2'
        ds.Rows = ds.Columns = 4
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = 'MONOCHROME2'
        ds.BitsAllocated = ds.BitsStored = 8
        ds.HighBit = 7
        ds.PixelRepresentation = 0
        ds.PixelData = np.arange(16, dtype=np.uint8).reshape(4, 4).tobytes()
        stream = io.BytesIO()
        pydicom.dcmwrite(stream, ds, enforce_file_format=True)
        item = dict(study_uid=str(ds.StudyInstanceUID), series_uid=str(ds.SeriesInstanceUID), sop_uid=str(ds.SOPInstanceUID), expected_frames=1)
        exam = dict(datetime=DAY, rut=RUT, exam_name='Imagen ficticia', modality='DX')
        content = labs.load_backend('mmrad').render_image_pdf(exam, [(item, stream.getvalue())])
        reader = PdfReader(io.BytesIO(content))
        self.assertEqual(len(reader.pages), 1)
        self.assertIn(RUT, reader.pages[0].extract_text())
        self.assertIn('19-10-2026', reader.pages[0].extract_text())


if __name__ == '__main__':
    unittest.main()
