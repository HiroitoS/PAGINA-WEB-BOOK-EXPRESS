"""Valorización referencial de existencias agrupadas por editorial.

Los movimientos se agregan por separado para no multiplicar los ingresos.
El valor de los observados se informa por separado: no está disponible para venta.
"""
from decimal import Decimal

from django.db.models import (
    Case, DecimalField, ExpressionWrapper, F, IntegerField, Sum, Value, When,
)

from warehouse.models import StockMovement


MONEY_FIELD = DecimalField(max_digits=20, decimal_places=2)


def _valor(cantidad, costo):
    return Sum(ExpressionWrapper(F(cantidad) * F(costo), output_field=MONEY_FIELD))


def _sin_costo(cantidad, campo="unit_cost_snapshot"):
    return Sum(Case(
        When(**{f"{campo}__isnull": True}, then=F(cantidad)),
        default=Value(0), output_field=IntegerField(),
    ))


def valorizar_por_editorial(entradas):
    """Devuelve saldos físicos y valorizaciones netas sin sumar dos veces salidas."""
    grupos = list(
        entradas.values("product__provider_id", "product__provider__name")
        .annotate(
            conformes=Sum("quantity_available"),
            observados=Sum("quantity_quarantined"),
            adicionales=Sum("quantity_extra"),
            valor_conformes=_valor("quantity_available", "unit_cost_snapshot"),
            valor_observados=_valor("quantity_quarantined", "unit_cost_snapshot"),
            sin_costo_conformes=_sin_costo("quantity_available"),
            sin_costo_observados=_sin_costo("quantity_quarantined"),
        )
        .order_by("product__provider__name", "product__provider_id")
    )
    variaciones = {
        movimiento["source_entry__product__provider_id"]: movimiento
        for movimiento in (
            StockMovement.objects.filter(source_entry__in=entradas)
            .values("source_entry__product__provider_id")
            .annotate(
                unidades=Sum("quantity_delta"),
                importe=_valor("quantity_delta", "unit_cost_snapshot"),
                sin_costo=_sin_costo("quantity_delta"),
            )
        )
    }
    resultado = []
    for grupo in grupos:
        editorial_id = grupo["product__provider_id"]
        movimiento = variaciones.get(editorial_id, {})
        observados = grupo["observados"] or 0
        disponibles = (grupo["conformes"] or 0) + (movimiento.get("unidades") or 0)
        valor_disponible = (
            (grupo["valor_conformes"] or Decimal("0")) +
            (movimiento.get("importe") or Decimal("0"))
        )
        valor_observado = grupo["valor_observados"] or Decimal("0")
        sin_costo_disponibles = (
            (grupo["sin_costo_conformes"] or 0) +
            (movimiento.get("sin_costo") or 0)
        )
        sin_costo_observados = grupo["sin_costo_observados"] or 0
        resultado.append({
            "editorial_id": editorial_id,
            "editorial": grupo["product__provider__name"],
            "physical": disponibles + observados,
            "available": disponibles,
            "observed": observados,
            "extra_received": grupo["adicionales"] or 0,
            "available_value_reference": str(valor_disponible),
            "observed_value_reference": str(valor_observado),
            "physical_value_reference": str(valor_disponible + valor_observado),
            "unvalued_available_units": sin_costo_disponibles,
            "unvalued_observed_units": sin_costo_observados,
            "valuation_complete": sin_costo_disponibles + sin_costo_observados == 0,
        })
    return resultado
