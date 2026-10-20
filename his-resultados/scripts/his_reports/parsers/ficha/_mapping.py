"""Fase 2 del parsing de ficha: `pairs` dict → estructura tipada.

Este módulo solo define el vocabulario: qué labels del HIS corresponden a
qué campos del frontend, y cuáles son sinónimos aceptables (con/sin tilde,
variantes entre PURG0005 y PAMB0005).

Toda la lógica de parsing HTML vive en los siblings (`_pairs`, `_medico`,
`_signos`). Este archivo se lee de arriba a abajo como una tabla de
traducción — es el lugar correcto para agregar un campo nuevo sin tocar
el resto.
"""
from __future__ import annotations

from ...types import Ficha
from .._common import decode_html
from ._medico import find_medico
from ._pairs import COMMENT_RE, extract_pairs
from ._signos import extract_signos_vitales


def parse_ficha_purg(html: bytes) -> Ficha:
    """Parsea PURG0005/PAMB0005 y devuelve la estructura tipada del frontend.

    El mismo parser sirve para ambos tipos de ficha — solo PURG0005 incluye
    la tabla de signos vitales, y en PAMB0005 los campos de SV quedan vacíos
    (la UI los omite gracias a los helpers `sec()`/`kv()` en `app.js`).
    """
    s = decode_html(html)
    # Saneo único para todas las fases: comentarios HTML pueden contener
    # literales `<b>LABEL:</b>` o `<input name="...">` que harían match
    # falso — tanto en extract_pairs como en find_medico.
    s = COMMENT_RE.sub("", s)
    pairs = extract_pairs(s)
    sv = extract_signos_vitales(s)

    def P(*labels: str) -> str:
        """Primera label presente, uppercase. `""` si ninguna."""
        for label in labels:
            v = pairs.get(label.upper())
            if v:
                return v
        return ""

    def SV(*keys: str) -> str:
        """Match de substring sobre los headers de la tabla SV."""
        for k in keys:
            for hkey, val in sv.items():
                if k.upper() in hkey:
                    return val
        return ""

    return {
        "paciente": {
            "nombre": P("NOMBRES"),
            "nombreSocial": P("NOMBRE SOCIAL"),
            "rut": P("RUT"),
            "nacimiento": P("NACIMIENTO"),
            "edad": P("EDAD"),
            "sexo": P("SEXO"),
            "genero": P("IDENTIDAD DE GÉNERO", "IDENTIDAD DE GENERO"),
            "prevision": P("PREVISIÓN", "PREVISION"),
            "direccion": P("DIRECCIÓN", "DIRECCION"),
            "comuna": P("COMUNA"),
            "nacionalidad": P("NACIONALIDAD"),
            "telefono": P("TELÉFONO", "TELEFONO"),
            "pueblo": P("PUEBLO ORIGINARIO"),
        },
        "atencionMeta": {
            "tipoAtencion": P("TIPO ATENCIÓN", "TIPO ATENCION"),
            "clasificacion": P("CLASIFICACIÓN ATENCIÓN",
                                "CLASIFICACION ATENCION"),
            "admisor": P("ADMISOR"),
            "fechaIngreso": P("FECHA INGRESO"),
            "horaIngreso": P("HR INGRESO", "HORA INGRESO"),
            "llegadaEn": P("LLEGADA EN"),
            "atencionesAnteriores": P("N° ATENCIONES ANT."),
            "ultimaAtencion": P("FECHA ÚLTIMA ATENCIÓN",
                                 "FECHA ULTIMA ATENCION"),
            "fechaSuceso": P("FECHA SUCESO"),
            "motivoConsulta": P("MOTIVO CONSULTA"),
            "medico": find_medico(pairs, s),
            "fechaAtencion": P("FECHA ATENCIÓN", "FECHA ATENCION"),
            "horaAtencion": P("HORA ATENCIÓN", "HORA ATENCION"),
            "boxAtencion": P("BOX ATENCIÓN", "BOX ATENCION"),
        },
        "signosVitales": {
            "hora": SV("HORA"),
            "FC": SV("F.C."),
            "PAS": SV("P. SISTÓLICA", "P. SISTOLICA", "SISTO"),
            "PAD": SV("P. DIASTÓLICA", "P. DIASTOLICA", "DIASTO"),
            "PAM": SV("PAM"),
            "FR": SV("F.R."),
            "SatO2": SV("SAT. O2", "SAT O2"),
            "TempRectal": SV("T° RECTAL", "TEMP RECTAL", "RECTAL"),
            "TempAxilar": SV("T° AXILAR", "TEMP AXILAR", "AXILAR"),
            "dolor": SV("ESCALA DEL DOLOR"),
            "glicemia": SV("HEMOGLUCOTEST"),
            "glasgow": SV("ESCALA GLASGOW"),
            "peso": P("PESO"),
            "altura": P("ALTURA"),
            "imc": P("IMC"),
        },
        "atencion": {
            "antecedentesMorbidos": P("ANTECEDENTES MÓRBIDOS",
                                       "ANTECEDENTES MORBIDOS"),
            "anamnesis": P("ANAMNESIS"),
            "examenFisico": P("EXAMEN FÍSICO", "EXAMEN FISICO"),
            "hipotesis": P("HIPOTESIS DIAGNÓSTICA",
                            "HIPOTESIS DIAGNOSTICA", "HIPOTESIS"),
            "indicaciones": P("INDICACIONES MÉDICAS / PLAN DE TTO",
                               "INDICACIONES MEDICAS / PLAN DE TTO",
                               "INDICACIONES"),
            "indicacionesAlta": P("INDICACIONES AL ALTA"),
        },
        "diagnosticos": {
            "principal": P("DIAGNÓSTICO PRI", "DIAGNOSTICO PRI"),
            "secundario": P("DIAGNÓSTICO SEC", "DIAGNOSTICO SEC"),
            "complementario": P("DIAG. COMPLEMENTARIO"),
        },
        "cierre": {
            "condicion": P("CONDICIÓN CIERRE ATENCIÓN",
                            "CONDICION CIERRE ATENCION"),
            "pronostico": P("PRONÓSTICO MÉDICO LEGAL",
                             "PRONOSTICO MEDICO LEGAL"),
            "destino": P("DESTINO"),
            "fechaSalida": P("FECHA SALIDA"),
            "horaSalida": P("HORA SALIDA"),
        },
        "destino": P("DESTINO"),
        "_raw_labels": pairs,
    }
