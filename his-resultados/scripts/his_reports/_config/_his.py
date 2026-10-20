"""URLs y endpoints del HIS Hanga Roa.

Las constantes acá son paths RELATIVOS al host del HIS — se concatenan con
`HIS_BASE`/`HIS_ORIGIN` en el código que los consume. Todos confirmados vía
exploración manual 2026-04.
"""
from __future__ import annotations

HIS_ORIGIN = "https://his.hospitalhangaroa.cl"
HIS_BASE_PATH = "/hishhr"
HIS_BASE = HIS_ORIGIN + HIS_BASE_PATH

# --- menú y dashboards ---

# Menú tras login exitoso — necesario como warm-up para estabilizar sesión.
MENU = "/hishhr/menu.php"

# Form landing de "DAU CERRADOS". GET aquí muestra las atenciones del día del
# usuario logueado; sirve además para warm-up y tomar el form real.
ATENCIONES_FORM = "/hishhr/ateurg022.php"

# Endpoint real del listado cross-usuario. Acepta POST con fdes/fhas/cboser/
# app/apm/nom/dau. Devuelve 11 columnas (ver `parsers.atenciones`).
ATENCIONES_LIST = "/hishhr/ateurg023.php"

# "REPORTE ATENCIONES AMBULATORIAS Y ESTADO" — el listado correcto para la
# vista "Por fecha + especialidad". Accesible bajo AMBULATORIO → INFORME
# ATENCIONES en el sidebar HIS. GET sirve además para enumerar el catálogo
# de especialidades (`parse_servicios` usa este mismo HTML) y como warm-up
# de sesión/referer para el POST al validador.
REPORTE_FORM = "/hishhr/reporte_atenciones_amb.php"

# Endpoint real del listado (2026-04): el form `reporte_atenciones_amb.php`
# ya no hace POST a sí mismo; ahora dispara un AJAX (jQuery `.load`) contra
# `app/View/informesAmbulatorio/reportesAmb/php/validador.php` con
# `accion=buscar_reporte_atenciones&fdes=&fhas=&print=0&serv=`. Devuelve
# HTML con la tabla de 10 columnas (CTACTE/RUT/HC/PACIENTE/FECHA CITA/
# SERVICIO/FECHA LLEGADA/ESTADO/MEDICO ATIENDE/ATENCION) — el parser
# `parse_reporte_atenciones_amb` lo consume sin cambios.
REPORTE_LIST = (
    "/hishhr/app/View/informesAmbulatorio/reportesAmb/php/validador.php"
)

# --- fichas imprimibles ---

# Ficha imprimible de urgencia: <b>LABEL:</b> ... + tabla de signos vitales.
FICHA_URG = "/hishhr/PURG0005.php"
# Ficha imprimible ambulatoria: misma estructura <b>LABEL:</b>, sin SV.
FICHA_AMB = "/hishhr/PAMB0005.php"
# Búsqueda por RUT / consulta de ficha. Accesible a todos los médicos.
CONSULTA_FICHA = "/hishhr/consficha000.php"

# --- login ---

LOGIN_ROOT = "/hishhr/"
LOGIN_ACTION = "/hishhr/acceso1.php"
