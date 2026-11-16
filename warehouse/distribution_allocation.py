"""Presupuesto de unidades de adopción para planificaciones logísticas.

Una asignación planificada NO reserva stock físico ni genera traslado/venta.
Todas las escrituras deben bloquear primero la fila Adoption en transacción,
para serializar las operaciones que compiten por la misma adopción.
"""
from collections import defaultdict

from django.db.models import Sum
from rest_framework.exceptions import ValidationError

from warehouse.models import DistributionOperation, DistributionOperationLine


def _adoption_products(adoption):
    products = {}
    for item in adoption.items.all():
        product_id = item.product_id
        if product_id not in products:
            products[product_id] = {
                "product_id": product_id,
                "product": item.product_name_snapshot,
                "adopted": 0,
            }
        products[product_id]["adopted"] += item.quantity
    return products


def allocation_summary(adoption, operation=None):
    """Cantidades de una adopción: otras planificaciones vs edición actual."""
    products = _adoption_products(adoption)
    plans = DistributionOperationLine.objects.filter(
        operation__adoption_id=adoption.pk,
        operation__status=DistributionOperation.Status.PLANNED,
    )
    if operation is not None:
        plans = plans.exclude(operation_id=operation.pk)
    others = dict(
        plans.values("product_id")
        .annotate(total=Sum("quantity_planned"))
        .values_list("product_id", "total")
    )
    current = (
        dict(operation.items.values_list("product_id", "quantity_planned"))
        if operation is not None else {}
    )

    result = []
    for product_id, info in products.items():
        used = others.get(product_id, 0)
        own = current.get(product_id, 0)
        remaining = info["adopted"] - used
        result.append({
            **info,
            "other_planned": used,
            "current_planned": own,
            "assignable": max(0, remaining),
            "overallocated": max(0, used + own - info["adopted"]),
        })
    return {
        "adoption_id": adoption.pk,
        "operation_id": operation.pk if operation else None,
        "items": result,
        "notice": (
            "Son cantidades de la adopción para organizar entregas. "
            "No indican stock físico disponible ni mercadería reservada."
        ),
    }


def validate_requested_allocation(adoption, items, operation=None):
    """Evita duplicados y sobreplanificación bajo bloqueo del padre Adoption."""
    summary = allocation_summary(adoption, operation=operation)
    allowed = {row["product_id"]: row for row in summary["items"]}
    if not allowed:
        raise ValidationError({"items": "Esta adopción no contiene productos."})

    chosen = {}
    for item in items:
        product_id = item["product_id"]
        if product_id in chosen:
            raise ValidationError({
                "items": "Un mismo libro no puede aparecer dos veces en una entrega.",
            })
        if product_id not in allowed:
            raise ValidationError({
                "items": "Uno de los libros no corresponde a la adopción seleccionada.",
            })
        quantity = item["quantity"]
        available = allowed[product_id]["assignable"]
        if quantity > available:
            raise ValidationError({
                "items": (
                    f"{allowed[product_id]['product']}: puedes planificar hasta "
                    f"{available} unidades en esta entrega; "
                    "revisa otras entregas de la misma adopción."
                ),
            })
        chosen[product_id] = quantity
    if not chosen:
        raise ValidationError({
            "items": "Indica al menos un libro con cantidad mayor que cero.",
        })
    return {
        product_id: {
            "quantity": quantity,
            "name": allowed[product_id]["product"],
        }
        for product_id, quantity in chosen.items()
    }


def replace_operation_lines(operation, planned):
    """Solo se usa mientras la operación está Por preparar."""
    operation.items.all().delete()
    DistributionOperationLine.objects.bulk_create([
        DistributionOperationLine(
            operation=operation,
            product_id=product_id,
            product_name_snapshot=details["name"],
            quantity_planned=details["quantity"],
        )
        for product_id, details in planned.items()
    ])
