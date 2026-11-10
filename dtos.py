"""DTOs de lectura (CQRS básico): no exponen los Aggregates."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional


@dataclass(frozen=True)
class ResultadoValidacionDto:
    reservacion_id: str
    documentacion_valida: bool
    estatus: str
    retencion_mxn: Decimal


@dataclass(frozen=True)
class OfertaDto:
    tipo: str
    categoria: str
    tarifa_diaria_mxn: Decimal
    descuento_adicional_pct: int


@dataclass(frozen=True)
class ResultadoCompensacionDto:
    reservacion_id: str
    resultado: str             # SIN_COMPENSACION | UPGRADE | DOWNGRADE | CANCELADA
    categoria_entrega: str
    tarifa_diaria_mxn: Decimal
    estatus: str


@dataclass(frozen=True)
class PanelVehiculoDto:
    vehiculo_id: str
    placas: str
    categoria: str
    estatus: str


@dataclass(frozen=True)
class CargoDto:
    indice: int
    tipo: str
    monto_mxn: Decimal
    descripcion: str
    cancelado: bool


@dataclass(frozen=True)
class ResumenDeCargosDto:
    contrato_id: str
    cargos: List[CargoDto]
    total_mxn: Decimal


@dataclass(frozen=True)
class ReservacionDto:
    reservacion_id: str
    categoria: str
    categoria_entrega: str
    estatus: str
    tarifa_diaria_mxn: Decimal
    retencion_mxn: Decimal
    documentacion_verificada: bool = False


@dataclass(frozen=True)
class ExtensionDto:
    contrato_id: str
    nuevo_fin_pactado: datetime
    monto_mxn: Decimal


@dataclass(frozen=True)
class UtilizacionPorCategoriaDto:
    categoria: str
    rentados: int
    flota: int


@dataclass(frozen=True)
class TasaDeUtilizacionDto:
    fecha: date
    rentados: int
    flota_total: int
    tasa_pct: Decimal
    por_categoria: List[UtilizacionPorCategoriaDto]


@dataclass(frozen=True)
class FilaIngresoDto:
    tipo: str
    cargos: int
    monto_mxn: Decimal


@dataclass(frozen=True)
class IngresosPorCargosDto:
    desde: date
    hasta: date          # inclusive
    contratos: int
    filas: List[FilaIngresoDto]
    total_mxn: Decimal
