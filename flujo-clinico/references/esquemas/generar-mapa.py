"""Regenerate the two maintained architecture diagrams. No patient data."""
from pathlib import Path
import subprocess
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import HexColor,white
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

ROOT=Path(__file__).resolve().parent
# ReportLab's bundled Vera font makes rendering reproducible across Macs.
import reportlab
fontdir=Path(reportlab.__file__).parent/'fonts'
pdfmetrics.registerFont(TTFont('Map',str(fontdir/'Vera.ttf')))
pdfmetrics.registerFont(TTFont('MapBold',str(fontdir/'VeraBd.ttf')))
W,H=960,720
c=Canvas(str(ROOT/'mapa-flujo-clinico.pdf'),pagesize=(W,H))
c.setTitle('Flujo clínico HHR · 19-10-2026')
style=ParagraphStyle('box',fontName='Map',fontSize=11,leading=16,textColor=HexColor('#233a35'),alignment=1)
def page(number,title,subtitle):
 c.setFillColor(HexColor('#f5f7f4'));c.rect(0,0,W,H,fill=1,stroke=0)
 c.setFillColor(HexColor('#17685b'));c.setFont('MapBold',10);c.drawString(42,H-36,'HHR / FLUJO CLÍNICO')
 c.setFont('MapBold',25);c.drawString(42,H-77,title)
 c.setFillColor(HexColor('#50645b'));c.setFont('Map',11);c.drawString(42,H-103,subtitle)
 c.setFont('Map',9);c.drawString(42,23,'19-10-2026 · Capacidades documentadas; comprobar accesos en cada ejecución.')
 c.drawRightString(W-42,23,str(number)+' / 2')
def box(x,y,w,h,title,body='',tint=False):
 c.setFillColor(HexColor('#dcebe4') if tint else white);c.setStrokeColor(HexColor('#d3dfd8'));c.roundRect(x,y,w,h,10,fill=1,stroke=1)
 p=Paragraph('<font name="MapBold">'+title+'</font>'+('<br/>'+body if body else ''),style);pw,ph=p.wrap(w-24,h-16);p.drawOn(c,x+12,y+(h-ph)/2)
def line(x1,y1,x2,y2):
 c.setStrokeColor(HexColor('#78978b'));c.setLineWidth(1.3);c.line(x1,y1,x2,y2)
 c.setFillColor(HexColor('#78978b'))
 if x1==x2:p=c.beginPath();p.moveTo(x2-3,y2+5);p.lineTo(x2,y2);p.lineTo(x2+3,y2+5);c.drawPath(p,fill=1,stroke=0)
def para(x,y,w,text):
 p=Paragraph(text,ParagraphStyle('note',parent=style,alignment=0,fontSize=10,leading=15));pw,ph=p.wrap(w,100);p.drawOn(c,x,y-ph)
page(1,'Doce skills, una entrada','La solicitud define pacientes, fuentes, períodos propios y formato de entrega opcional.')
box(325,515,310,65,'$flujo-clinico','Coordina sólo el alcance solicitado',True)
line(480,515,480,488);box(240,423,480,65,'laboratorios-descargas','Formulario · cola persistente · clientes e importación',True)
line(480,423,480,398)
box(42,260,576,138,'Seis skills de portal','syslab-resultados · exalab-resultados<br/>eloisa-resultados · his-resultados<br/>rayen-epicrisis · mmrad-resultados')
box(640,260,278,138,'correo-clinico','Gmail institucional en Codex<br/>Identidad de mensajes y adjuntos<br/>Evidencia importada al trabajo')
line(480,398,330,398);line(480,398,779,398)
box(42,147,275,80,'reporte-clinico','Síntesis solicitada y citas')
box(339,147,279,80,'formularios-clinicos','Plantilla o formulario solicitado')
box(640,147,278,80,'eloisa-archivo-drive','Expediente por nombre de paciente')
line(330,260,330,242);line(179,242,779,242);line(179,242,179,227);line(479,242,479,227);line(779,260,779,227)
para(42,116,565,'<b>Cierre siempre:</b> respuesta + TXT numerado con [X] completada, [~] parcial y [ ] pendiente/no solicitada. El cierre también existe cuando no se pide un documento clínico.')
para(640,116,278,'<b>Continuidad:</b> un fallo conserva los documentos verificados de todas las fuentes. Copia y subida se comprueban por separado.')
c.showPage()
page(2,'De la solicitud al expediente','Air prepara la orden; el Mac mini ejecuta. Copiar el texto no equivale a enviar ni consultar.')
box(42,520,268,62,'MacBook Air','HTML portátil: texto / TXT')
box(346,520,268,62,'Codex del Mac mini','Valida alcance, fecha y selección',True)
box(650,520,268,62,'Ejecución local','CLI / puente o cola persistente')
line(310,551,346,551);line(614,551,650,551)
line(784,520,784,500);line(252,500,784,500);line(252,500,252,485);line(708,500,708,485)
box(42,400,420,85,'API / HTTP de portales','Chrome: sesión · Adjuntos Eloísa: PDF original<br/>MMRAD: informes TAC y radiografías')
box(498,400,420,85,'Gmail en Codex','Cuenta institucional solicitada<br/>Mensajes completos y adjuntos')
line(252,400,252,382);line(708,400,708,382);line(252,382,708,382);line(480,382,480,365)
box(200,300,560,65,'Revisión de identidad e integridad','Paciente · rol · fecha · episodio · SHA-256',True)
line(480,300,480,282);line(252,282,708,282);line(252,282,252,265);line(708,282,708,265)
box(42,185,420,80,'Trabajo local por paciente','Originales, copias y avance<br/>Correo aparte del PDF único de portales')
box(498,185,420,80,'Resumen obligatorio','[X] / [~] / [ ] por fuente<br/>Respuesta + TXT',True)
line(252,185,252,160);line(708,185,708,160);line(252,160,708,160);line(328,160,328,150)
box(42,75,572,75,'Drive / Pacientes / Nombre completo','Fuentes primarias / Correo y portales<br/>Resúmenes, formularios y cierre TXT')
box(650,75,268,75,'Verificación independiente','Copia: SHA-256<br/>Nube: ruta, tamaño y checksum')
line(614,112,650,112)
para(42,62,876,'Sin nombre verificado: cierre en Documentos generales. Sesiones fuera del expediente. Traslado Air a Mini manual; Gmail requiere Codex.')
c.save()
subprocess.run(['pdftoppm','-png','-scale-to','1600',str(ROOT/'mapa-flujo-clinico.pdf'),str(ROOT/'mapa')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
