import io
import json
from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rayen_epicrisis as r
from reportlab.pdfgen.canvas import Canvas

RUT='111111111'  # Identidad ficticia, nunca enviada a una red.
def row(enc=1, **extra):
    return dict(encounterId=enc, patientId=99, facilityId=77, patientIdentifier=RUT,
                patientIdentifierTypeId=2, patientName='Paciente Ficticio', endPeriod='2026-10-15T10:00:00',
                startPeriod='2026-10-12T10:00:00', generatedReport=True, deleted=False, **extra)
def pdf(rut=RUT, discharge='15/10/2026'):
    output=io.BytesIO();c=Canvas(output);c.drawString(40,800,'Paciente Ficticio RUN: '+rut)
    c.drawString(40,780,'Fecha egreso: '+discharge);c.save();return output.getvalue()
class Tests(unittest.TestCase):
    def client(self, rows, downloads=None):
        def transport(req):
            self.assertEqual(req.get_method(),'GET')
            self.assertEqual(req.get_header('Authorization'),'fixture-token')
            parsed=urlparse(req.full_url)
            self.assertEqual(parsed.hostname,'fichamedicoback.rayensalud.cl')
            self.assertNotIn('fixture-token',req.full_url)
            if parsed.path.endswith(r.LIST_PATH):
                query=parse_qs(parsed.query,keep_blank_values=True)
                self.assertEqual(query['prefferedPeridentId'],['2'])
                self.assertEqual(query['prefferedIdentifierCode'],[RUT])
                return json.dumps({'data':rows}).encode()
            self.assertTrue(parsed.path.endswith(r.PDF_PATH))
            result=(downloads or {}).get(int(parse_qs(parsed.query)['enc_id'][0]),pdf())
            if isinstance(result,Exception):raise result
            return result
        return r.Client({'token':'fixture-token','facilityId':77},transport)
    def test_filter_period_and_only_list(self):
        old=row(2);old['endPeriod']='2025-01-01'
        with tempfile.TemporaryDirectory() as out:
            _,state=r.run(self.client([row(),old]),RUT,date(2026,10,1),date(2026,10,19),out)
            self.assertEqual(len(state['episodes']),1);self.assertEqual(state['files'],[])
            self.assertEqual(list(Path(out).rglob('*.pdf')),[])
    def test_partial_preserves_valid_documents(self):
        with tempfile.TemporaryDirectory() as out:
            _,state=r.run(self.client([row(1),row(2)],{2:b'<html>login</html>'}),RUT,date(2026,10,1),date(2026,10,19),out,True)
            self.assertEqual(state['status'],'partial');self.assertEqual(len(state['files']),1)
            self.assertTrue(Path(state['files'][0]['path']).exists())
            self.assertEqual(len(state['pending']),1)
            self.assertNotIn('fixture-token',json.dumps(state))
    def test_session_expiry_preserves_previous(self):
        with tempfile.TemporaryDirectory() as out:
            _,state=r.run(self.client([row(1),row(2),row(3)],{2:r.SessionExpired('Sesión vencida')}),RUT,date(2026,10,1),date(2026,10,19),out,True)
            self.assertEqual(len(state['files']),1);self.assertEqual(len(state['pending']),2)
            self.assertTrue(state['auth_required'])
    def test_wrong_identity_rejected(self):
        bad=row();bad['patientIdentifier']='222222222'
        with self.assertRaises(r.ReportError):self.client([bad]).episodes(RUT,date(2026,10,1),date(2026,10,19))
    def test_missing_report_and_date_are_pending(self):
        a=row();a['generatedReport']=False;b=row(2);b['endPeriod']=None
        rows,pending=self.client([a,b]).episodes(RUT,date(2026,10,1),date(2026,10,19))
        self.assertEqual(len(rows),1);self.assertEqual(len(pending),1) # generatedReport no bloquea el intento de lectura
    def test_pdf_identity_and_date_validation(self):
        with self.assertRaises(r.ReportError):r.validate_pdf(pdf('222222222'),row())
        with self.assertRaises(r.ReportError):r.validate_pdf(pdf(discharge='01/01/2025'),row())
    def test_versions_and_duplicate_reuse(self):
        with tempfile.TemporaryDirectory() as out:
            content=pdf();a=r.save_version(Path(out),row(),content);b=r.save_version(Path(out),row(),content)
            self.assertEqual(a['path'],b['path'])
            c=r.save_version(Path(out),row(),content+b'\n')
            self.assertNotEqual(a['path'],c['path']);self.assertTrue(Path(a['path']).exists())
    def test_invalid_rut_no_request(self):
        with self.assertRaises(r.ReportError):r.rut_normalized('11111111-2')
    def test_auth_not_inferred_as_empty_results(self):
        client=r.Client({'token':'fixture-token','facilityId':77},lambda req:b'{"ok":false,"data":[]}')
        with self.assertRaises(r.ReportError):client.episodes(RUT,date(2026,10,1),date(2026,10,19))
    def test_redirect_blocked(self):
        with self.assertRaises(r.ReportError):r.NoRedirect().redirect_request(None,None,302,'',{},'https://other.example')
if __name__=='__main__':unittest.main()
