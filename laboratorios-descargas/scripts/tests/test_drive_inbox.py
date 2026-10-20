"""Drive handoff with fictional patients and no portal access."""
from hashlib import sha256
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drive_inbox import DriveInbox


class FakeQueue:
    def __init__(self):
        self.requests = {}

    def new_job(self, request):
        ident = request['requestId']
        if ident in self.requests:
            if self.requests[ident] != request:
                raise ValueError('El identificador ya existe con otro contenido.')
            return {'id':'job-1','reused':True}
        self.requests[ident] = request
        return {'id':'job-1','reused':False}


class DriveInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queue = FakeQueue()
        self.inbox = DriveInbox(self.queue, self.root / '_Solicitudes Nexo')
        self.inbox.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def packet(self):
        return dict(kind='hhr-clinical-request',version=4,id='a'*32,target='mac-mini',
                    timeZone='Pacific/Easter',asOf='2026-10-19',request=dict(
                        schema=2,ruts=['11111111-1'],source='syslab,exalab',period='1y',
                        sourcePeriods={},sourceContent={},deliveryModel='documents',
                        deliveryInstructions='',emailAccount='daniel.opazo@hospitalhangaroa.cl',
                        eloisaScope='medicos',mmradMode='both',mmradImageTypes=['radiographs'],
                        merge=False,patientMerge=False))

    def place(self, packet):
        raw = (json.dumps(packet, ensure_ascii=False, indent=2) + '\n').encode()
        digest = sha256(raw).hexdigest()
        stem = f"solicitud-{packet['id']}"
        (self.inbox.root / (stem + '.json')).write_bytes(raw)
        (self.inbox.root / (stem + '.ready')).write_text(digest + '\n')
        return digest

    def receipt(self, packet):
        return json.loads((self.inbox.root / 'acuses' / f"acuse-{packet['id']}.json").read_text())

    def test_imports_once_and_preserves_reference_date(self):
        packet = self.packet()
        self.place(packet)
        self.assertEqual(self.inbox.scan_once(), 1)
        self.assertEqual(self.receipt(packet)['status'], 'imported')
        self.assertEqual(self.queue.requests[packet['id']]['asOf'], packet['asOf'])
        self.assertEqual(self.inbox.scan_once(), 0)
        self.assertEqual(len(self.queue.requests), 1)

    def test_waits_for_complete_matching_file(self):
        packet = self.packet()
        self.place(packet)
        (self.inbox.root / f"solicitud-{packet['id']}.json").write_text('{')
        self.assertEqual(self.inbox.scan_once(), 0)
        self.assertEqual(self.queue.requests, {})
        self.place(packet)
        self.assertEqual(self.inbox.scan_once(), 1)

    def test_rejects_changed_content_for_existing_id(self):
        packet = self.packet()
        self.place(packet)
        self.assertEqual(self.inbox.scan_once(), 1)
        packet['request']['period'] = '10y'
        self.place(packet)
        self.assertEqual(self.inbox.scan_once(), 1)
        self.assertEqual(self.receipt(packet)['status'], 'rejected')
        self.assertEqual(len(self.queue.requests), 1)


if __name__ == '__main__':
    unittest.main()
