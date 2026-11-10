"""Application Services (Service Layer, U3 Etapa 4). Cada método = un caso de uso con una transacción.
Coordinan; las reglas viven en el dominio."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, List, Optional
from uuid import uuid4

from src.domain.cargos import CalculadoraDeCargosExtra, CargoExtra
from src.domain.compensacion import CompensacionDeCategoria, DisponibilidadDeCategoria, TipoDeOferta
from src.domain.contrato import ContratoDeRenta, SolicitudDeCancelacion
from src.domain.events import MantenimientoMayorRegistrado
from src.domain.value_objects import (Categoria, Dinero, DocumentacionConductor, EstatusDeVehiculo, Rol,
                                      TipoDeCargo, VoucherAbierto)

from .commands import DecisionDelCliente, EntregarVehiculoCommand, RegistrarDevolucionCommand
from .dtos import (CargoDto, ExtensionDto, FilaIngresoDto, IngresosPorCargosDto, OfertaDto, PanelVehiculoDto,
                   ReservacionDto, ResultadoCompensacionDto, ResultadoValidacionDto, ResumenDeCargosDto,
                   TasaDeUtilizacionDto, UtilizacionPorCategoriaDto)
from .errors import NoEncontrado, SinVehiculoDisponible
from .ports import (CatalogoDeCategorias, PasarelaDeAutorizacionBancaria, ProveedorDePrecioDeCombustible,
                    Reloj, UnidadDeTrabajo, ValidadorDePin)

log = logging.getLogger(__name__)
UowFactory = Callable[[], UnidadDeTrabajo]


def _req(obj, nombre: str, ident: str):
    if obj is None:
        raise NoEncontrado(f"{nombre} '{ident}' no encontrada")
    return obj


# ---------------- CU-02 / paso 1 de CU-01 ----------------
class ServicioDeValidacionDeDocumentacion:
    def __init__(self, uow_factory: UowFactory, reloj: Reloj):
        self.uow_factory, self.reloj = uow_factory, reloj

    def validar_documentacion_del_conductor(self, reservacion_id: str,
                                            doc: DocumentacionConductor) -> ResultadoValidacionDto:
        with self.uow_factory() as uow:
            r = _req(uow.reservaciones.obtener(reservacion_id), "Reservación", reservacion_id)
            valida = r.validar_documentacion(doc, self.reloj.hoy())
            uow.reservaciones.guardar(r)
            uow.commit()
            return ResultadoValidacionDto(r.reservacion_id, valida, r.estatus.value, r.retencion.monto)


# ---------------- CU-03 ----------------
class ServicioDeCompensacionDeCategoria:
    def __init__(self, uow_factory: UowFactory, catalogo: CatalogoDeCategorias,
                 compensacion: Optional[CompensacionDeCategoria] = None):
        self.uow_factory, self.catalogo = uow_factory, catalogo
        self.compensacion = compensacion or CompensacionDeCategoria()

    def _oferta(self, uow, r, rechaza_upgrade=False):
        cat = r.categoria_entrega
        sup = self.catalogo.superior_inmediata_de(cat)
        inf = self.catalogo.inferior_inmediata_de(cat)
        disp = DisponibilidadDeCategoria(
            hay_en_categoria=uow.vehiculos.hay_disponibilidad_en(cat),
            hay_superior=bool(sup and uow.vehiculos.hay_disponibilidad_en(sup)),
            hay_inferior=bool(inf and uow.vehiculos.hay_disponibilidad_en(inf)))
        return self.compensacion.determinar_oferta(
            r.tarifa_diaria, disp, sup, inf, self.catalogo.tarifa_de(inf) if inf else None, rechaza_upgrade)

    def consultar_oferta(self, reservacion_id: str) -> Optional[OfertaDto]:   # Query (U3)
        with self.uow_factory() as uow:
            r = _req(uow.reservaciones.obtener(reservacion_id), "Reservación", reservacion_id)
            o = self._oferta(uow, r)
            return None if o is None else OfertaDto(o.tipo.value, o.categoria.name,
                                                    o.tarifa_diaria.monto, o.descuento_adicional_pct)

    def resolver_categoria_no_disponible(self, reservacion_id: str,
                                         decision: DecisionDelCliente) -> ResultadoCompensacionDto:
        with self.uow_factory() as uow:
            r = _req(uow.reservaciones.obtener(reservacion_id), "Reservación", reservacion_id)
            if uow.vehiculos.hay_disponibilidad_en(r.categoria_entrega):
                resultado = "SIN_COMPENSACION"
            else:
                oferta = self._oferta(uow, r, rechaza_upgrade=not decision.acepta_upgrade)
                if oferta is None or (oferta.tipo == TipoDeOferta.DOWNGRADE and not decision.acepta_inferior):
                    r.cancelar_por_falta_de_categoria()
                    resultado = "CANCELADA"
                else:
                    r.aplicar_compensacion(oferta)
                    resultado = oferta.tipo.value
            uow.reservaciones.guardar(r)
            uow.commit()
            return ResultadoCompensacionDto(r.reservacion_id, resultado, r.categoria_entrega.name,
                                            r.tarifa_diaria.monto, r.estatus.value)


# ---------------- CU-01 ----------------
class ServicioDeEntrega:
    def __init__(self, uow_factory: UowFactory, pasarela: PasarelaDeAutorizacionBancaria):
        self.uow_factory, self.pasarela = uow_factory, pasarela

    def entregar_vehiculo(self, cmd: EntregarVehiculoCommand) -> str:
        with self.uow_factory() as uow:
            r = _req(uow.reservaciones.obtener(cmd.reservacion_id), "Reservación", cmd.reservacion_id)
            if r.documentacion is None or not r.documentacion_verificada:
                from src.domain.value_objects import ConflictoDeEstado
                raise ConflictoDeEstado("Primero debe validarse la documentación del conductor")
            vehiculo = uow.vehiculos.buscar_disponible_de_categoria(r.categoria_entrega)
            if vehiculo is None:
                raise SinVehiculoDisponible(f"No hay vehículos disponibles de categoría {r.categoria_entrega.name}")
            codigo = self.pasarela.autorizar_deposito(cmd.ultimos_4, cmd.titular)
            voucher = VoucherAbierto(cmd.ultimos_4, codigo, cmd.titular)
            contrato = ContratoDeRenta.crear(
                f"CON-{uuid4().hex[:8].upper()}", r.reservacion_id, vehiculo.vehiculo_id, r.periodo,
                r.tarifa_diaria, voucher, cmd.inspeccion_salida, r.documentacion)
            vehiculo.entregar()
            r.marcar_entregada()
            uow.contratos.agregar(contrato)
            uow.vehiculos.guardar(vehiculo)
            uow.reservaciones.guardar(r)
            uow.commit()
            return contrato.contrato_id


# ---------------- CU-04 ----------------
class ServicioDeDevolucion:
    def __init__(self, uow_factory: UowFactory, calculadora: CalculadoraDeCargosExtra,
                 combustible: ProveedorDePrecioDeCombustible):
        self.uow_factory, self.calculadora, self.combustible = uow_factory, calculadora, combustible

    def registrar_devolucion(self, cmd: RegistrarDevolucionCommand) -> str:
        with self.uow_factory() as uow:
            c = _req(uow.contratos.obtener(cmd.contrato_id), "Contrato", cmd.contrato_id)
            v = _req(uow.vehiculos.obtener(c.vehiculo_id), "Vehículo", c.vehiculo_id)
            c.registrar_devolucion(cmd.inspeccion_devolucion, cmd.hora_devolucion, self.calculadora,
                                   v.capacidad_tanque_litros, self.combustible.precio_por_litro())
            v.recibir_en_revision()
            uow.contratos.guardar(c)
            uow.vehiculos.guardar(v)
            uow.commit()
            return c.contrato_id


# ---------------- CU-05 ----------------
class ServicioDeLimpieza:
    def __init__(self, uow_factory: UowFactory):
        self.uow_factory = uow_factory

    def _cambiar(self, vehiculo_id: str, accion, *args) -> PanelVehiculoDto:
        with self.uow_factory() as uow:
            v = _req(uow.vehiculos.obtener(vehiculo_id), "Vehículo", vehiculo_id)
            getattr(v, accion)(*args)
            uow.vehiculos.guardar(v)
            uow.commit()
            return PanelVehiculoDto(v.vehiculo_id, v.placas, v.categoria.name, v.estatus.value)

    def iniciar_limpieza(self, vehiculo_id: str): return self._cambiar(vehiculo_id, "iniciar_limpieza")
    def marcar_terminado(self, vehiculo_id: str): return self._cambiar(vehiculo_id, "marcar_terminado")

    def reportar_mantenimiento_mayor(self, vehiculo_id: str, motivo: str, monto):
        return self._cambiar(vehiculo_id, "reportar_mantenimiento_mayor", motivo, monto)


class ManejadorMantenimientoMayor:
    """Handler del evento MantenimientoMayorRegistrado: agrega el cargo retroactivo (US13)."""
    def __init__(self, uow_factory: UowFactory):
        self.uow_factory = uow_factory

    def __call__(self, evento: MantenimientoMayorRegistrado) -> None:
        with self.uow_factory() as uow:
            c = uow.contratos.obtener_ultimo_de_vehiculo(evento.vehiculo_id)
            if c is None:
                log.warning("Mantenimiento Mayor sin contrato previo: %s", evento.vehiculo_id)
                return
            c.agregar_cargo_retroactivo(CargoExtra(TipoDeCargo.MANTENIMIENTO_MAYOR, Dinero(evento.monto),
                                                   evento.motivo))
            uow.contratos.guardar(c)
            uow.commit()


def _resumen(c: ContratoDeRenta) -> ResumenDeCargosDto:
    return ResumenDeCargosDto(
        c.contrato_id,
        [CargoDto(i, x.tipo.value, x.monto.monto, x.descripcion, x.cancelado) for i, x in enumerate(c.cargos)],
        c.total_cargos().monto)


# ---------------- US09 / US08 / daños ----------------
class ServicioDeContratos:
    """Operaciones posteriores a la firma sobre un ContratoDeRenta (extensión, cancelación de cargos, daños)."""
    def __init__(self, uow_factory: UowFactory, reloj: Reloj, validador_pin: ValidadorDePin):
        self.uow_factory, self.reloj, self.validador_pin = uow_factory, reloj, validador_pin

    def extender_renta(self, contrato_id: str, nuevo_fin: datetime,
                       vehiculo_reservado_por_otro: bool = False) -> ExtensionDto:
        with self.uow_factory() as uow:
            c = _req(uow.contratos.obtener(contrato_id), "Contrato", contrato_id)
            monto = c.extender(nuevo_fin, self.reloj.ahora(), vehiculo_reservado_por_otro)
            uow.contratos.guardar(c)
            uow.commit()
            return ExtensionDto(c.contrato_id, c.periodo.fin_pactado, monto.monto)

    def cancelar_cargo(self, contrato_id: str, indice: int, rol: Rol, pin: str, motivo: str) -> ResumenDeCargosDto:
        with self.uow_factory() as uow:
            c = _req(uow.contratos.obtener(contrato_id), "Contrato", contrato_id)
            c.cancelar_cargo(indice, SolicitudDeCancelacion(rol, self.validador_pin.es_valido(pin)), motivo)
            uow.contratos.guardar(c)
            uow.commit()
            return _resumen(c)

    def registrar_cargo_por_danos(self, contrato_id: str, monto: Decimal, descripcion: str = "") -> ResumenDeCargosDto:
        with self.uow_factory() as uow:
            c = _req(uow.contratos.obtener(contrato_id), "Contrato", contrato_id)
            c.registrar_cargo_por_danos(Dinero(monto), descripcion)
            uow.contratos.guardar(c)
            uow.commit()
            return _resumen(c)


# ---------------- Queries ----------------
class ConsultasDeNovaRent:
    def __init__(self, uow_factory: UowFactory, reloj: Reloj):
        self.uow_factory, self.reloj = uow_factory, reloj

    def panel_de_vehiculos(self, categoria: Optional[Categoria] = None) -> List[PanelVehiculoDto]:
        with self.uow_factory() as uow:
            return [PanelVehiculoDto(v.vehiculo_id, v.placas, v.categoria.name, v.estatus.value)
                    for v in uow.vehiculos.listar(categoria)]

    def resumen_de_cargos(self, contrato_id: str) -> ResumenDeCargosDto:
        with self.uow_factory() as uow:
            return _resumen(_req(uow.contratos.obtener(contrato_id), "Contrato", contrato_id))

    def reservacion(self, reservacion_id: str) -> ReservacionDto:
        with self.uow_factory() as uow:
            r = _req(uow.reservaciones.obtener(reservacion_id), "Reservación", reservacion_id)
            return ReservacionDto(r.reservacion_id, r.categoria.name, r.categoria_entrega.name,
                                  r.estatus.value, r.tarifa_diaria.monto, r.retencion.monto,
                                  r.documentacion_verificada)

    # ---- US14: Tasa de Utilización (foto del día) ----
    def tasa_de_utilizacion(self) -> TasaDeUtilizacionDto:
        with self.uow_factory() as uow:
            flota = uow.vehiculos.listar()
        rentados = sum(1 for v in flota if v.estatus == EstatusDeVehiculo.RENTADO)
        tasa = (Decimal(rentados) * 100 / len(flota)).quantize(Decimal("0.01"), ROUND_HALF_UP) if flota else Decimal("0.00")
        por_cat = [UtilizacionPorCategoriaDto(
            cat.name, sum(1 for v in flota if v.categoria == cat and v.estatus == EstatusDeVehiculo.RENTADO),
            sum(1 for v in flota if v.categoria == cat)) for cat in Categoria]
        return TasaDeUtilizacionDto(self.reloj.hoy(), rentados, len(flota), tasa, por_cat)

    # ---- US15: Ingresos por Cargos Adicionales (semana lunes-domingo) ----
    def ingresos_por_cargos_adicionales(self, desde: Optional[date] = None) -> IngresosPorCargosDto:
        hoy = self.reloj.hoy()
        inicio = desde or (hoy - timedelta(days=hoy.weekday()))     # lunes de la semana en curso
        fin_exclusivo = inicio + timedelta(days=7)
        with self.uow_factory() as uow:
            contratos = uow.contratos.listar_devueltos_entre(
                datetime.combine(inicio, time.min), datetime.combine(fin_exclusivo, time.min))
        orden = [TipoDeCargo.COMBUSTIBLE, TipoDeCargo.DANOS, TipoDeCargo.RETRASO, TipoDeCargo.KILOMETRAJE,
                 TipoDeCargo.MANTENIMIENTO_MAYOR, TipoDeCargo.EXTENSION]
        acumulado = {t: [0, Decimal("0")] for t in orden}
        for c in contratos:
            for cargo in c.cargos:
                if not cargo.cancelado:
                    acumulado[cargo.tipo][0] += 1
                    acumulado[cargo.tipo][1] += cargo.monto.monto
        filas = [FilaIngresoDto(t.value, n, m) for t, (n, m) in acumulado.items()]
        return IngresosPorCargosDto(inicio, fin_exclusivo - timedelta(days=1), len(contratos), filas,
                                    sum((f.monto_mxn for f in filas), Decimal("0")))
