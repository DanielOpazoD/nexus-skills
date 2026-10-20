"""Contratos de datos entre parsers → API → frontend.

TypedDicts documentan las formas que el frontend consume. Python no los
enforza en runtime, pero:

  - Sirven como documentación viva (un lector ve la forma exacta sin
    rebuscar por el código).
  - Los IDE (pyright/pylance/mypy) marcan typos o campos faltantes al
    construir dicts.
  - Si en el futuro agregamos mypy al CI, ya hay una base.

No usamos dataclasses ni pydantic a propósito: el frontend espera JSON con
forma de dict, y los parsers actuales ya devuelven dicts. Envolver en
dataclasses obligaría a convertir `asdict()` en cada endpoint — ruido sin
beneficio para un proyecto de este tamaño.

Campos marcados como `str` que "pueden venir vacíos" se documentan como
`str` (no `Optional[str]`) porque esa es la convención de los parsers:
nunca devuelven `None`, siempre `""`. Así el frontend no tiene que hacer
`?? ""` en cada acceso.
"""
from __future__ import annotations

from typing import TypedDict


class Servicio(TypedDict):
    """Una fila del `<select name="cboser">` del HIS."""
    id: str
    nombre: str


class AtencionRow(TypedDict, total=False):
    """Fila del listado de atenciones (cualquier fuente).

    `total=False` porque las tres fuentes (`ateurg023`, `reporte_amb`,
    `consficha`) pueblan subconjuntos distintos. El frontend lee con `||`
    para tolerar campos faltantes. Los campos mínimos garantizados por
    todas las fuentes: `idCuenta`, `tipoFicha`, `rut`, `fecha`.
    """
    # Identificación + routing al endpoint de ficha
    idCuenta: str
    tipoFicha: str          # "urgencia" | "ambulatorio"
    ctacte: str
    # Paciente
    rut: str
    hc: str
    nombre: str
    nombreSocial: str
    # Temporalidad
    fecha: str              # ISO YYYY-MM-DD
    hora: str               # HH:MM (puede venir vacío)
    fechaLlegada: str       # ISO (solo reporte_amb)
    horaLlegada: str        # HH:MM (solo reporte_amb)
    # Clasificación
    servicio: str
    tipoAtencion: str
    estado: str             # solo reporte_amb: "atendido" / "NSP" / "anulada"
    # Profesional
    medico: str
    # Extras que rellena la ficha (no la tabla)
    diagnostico: str
    destino: str
    hospitalizacion: str
    dau: str
    ficha: str


class Paciente(TypedDict, total=False):
    nombre: str
    nombreSocial: str
    rut: str
    nacimiento: str
    edad: str
    sexo: str
    genero: str
    prevision: str
    direccion: str
    comuna: str
    nacionalidad: str
    telefono: str
    pueblo: str


class AtencionMeta(TypedDict, total=False):
    tipoAtencion: str
    clasificacion: str
    admisor: str
    fechaIngreso: str
    horaIngreso: str
    llegadaEn: str
    atencionesAnteriores: str
    ultimaAtencion: str
    fechaSuceso: str
    motivoConsulta: str
    medico: str
    fechaAtencion: str
    horaAtencion: str
    boxAtencion: str


class SignosVitales(TypedDict, total=False):
    hora: str
    FC: str
    PAS: str
    PAD: str
    PAM: str
    FR: str
    SatO2: str
    TempRectal: str
    TempAxilar: str
    dolor: str
    glicemia: str
    glasgow: str
    peso: str
    altura: str
    imc: str


class AtencionClinica(TypedDict, total=False):
    antecedentesMorbidos: str
    anamnesis: str
    examenFisico: str
    hipotesis: str
    indicaciones: str
    indicacionesAlta: str


class Diagnosticos(TypedDict, total=False):
    principal: str
    secundario: str
    complementario: str


class Cierre(TypedDict, total=False):
    condicion: str
    pronostico: str
    destino: str
    fechaSalida: str
    horaSalida: str


class Ficha(TypedDict, total=False):
    """Estructura devuelta por `parse_ficha_purg` + inyectada por el handler."""
    paciente: Paciente
    atencionMeta: AtencionMeta
    signosVitales: SignosVitales
    atencion: AtencionClinica
    diagnosticos: Diagnosticos
    cierre: Cierre
    destino: str
    idCuenta: str           # inyectado por el handler (no por el parser)
    tipoFicha: str          # inyectado por el handler
    _raw_labels: dict[str, str]
