"""Regresiones de identidad: todas las personas y episodios son ficticios."""
import io
from pathlib import Path
import sys
import unittest
from reportlab.pdfgen.canvas import Canvas
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rayen_epicrisis as rayen
ROW={'patientIdentifier':'11111111-1','encounterId':7,'endPeriod':'2026-10-15'}
def document(*pages):
    out=io.BytesIO();c=Canvas(out)
    for lines in pages:
        for i,line in enumerate(lines):c.drawString(35,800-18*i,line)
        c.showPage()
    c.save();return out.getvalue()
def header(rut='11111111-1'):
    return ['DATOS DEL PACIENTE','Paciente Ficticio',rut,'Sexo: X','RUN:','DIAGNOSTICO','Fecha Egreso: 15-10-2026']
class PatientHeaderTests(unittest.TestCase):
    def test_patient_values_before_labels(self):rayen.validate_pdf(document(header()),ROW)
    def test_expected_rut_only_as_doctor_rejected(self):
        lines=header('22222222-2')+['MEDICO TRATANTE','RUT: 11111111-1']
        with self.assertRaises(rayen.ReportError):rayen.validate_pdf(document(lines),ROW)
    def test_unqualified_rut_in_narrative_rejected(self):
        with self.assertRaises(rayen.ReportError):rayen.validate_pdf(document(['ANAMNESIS','RUT: 11111111-1','Fecha Egreso: 15-10-2026']),ROW)
    def test_patient_same_line(self):
        rayen.validate_pdf(document(['Paciente: Persona Ficticia RUN: 11.111.111-1','Fecha Egreso: 15-10-2026']),ROW)
    def test_second_page_conflicting_patient_rejected(self):
        with self.assertRaises(rayen.ReportError):rayen.validate_pdf(document(header(),header('22222222-2')),ROW)
    def test_matching_episode(self):rayen.validate_pdf(document(header()+['ID de episodio: 7']),ROW)
    def test_wrong_episode_rejected(self):
        with self.assertRaises(rayen.ReportError):rayen.validate_pdf(document(header()+['ID de episodio: 8']),ROW)
    def test_ambiguous_patient_header_rejected(self):
        lines=header();lines.insert(3,'22222222-2')
        with self.assertRaises(rayen.ReportError):rayen.validate_pdf(document(lines),ROW)
    def test_unlabelled_patient_id_rejected(self):
        with self.assertRaises(rayen.ReportError):rayen.validate_pdf(document([x for x in header() if x!='RUN:']),ROW)
if __name__=='__main__':unittest.main()
