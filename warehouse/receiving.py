"""Reglas transaccionales de Recepción de Mercadería.

Los saldos se calculan a partir de recepciones VALIDADAS; no de movimientos
de stock, ventas ni facturas. No se permite sobre-recepción aceptada sin
un flujo formal de excepción que se diseñará posteriormente.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.permissions import usuario_tiene_permiso
from catalog.models import Provider
from purchasing.models import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem
from warehouse.models import GoodsReceipt, GoodsReceiptEvent, GoodsReceiptLine


def _autorizar(actor, permiso):
    if not actor or not actor.is_authenticated or not usuario_tiene_permiso(actor, permiso):
        raise PermissionDenied("No tienes permiso para realizar esta operación.")


@transaction.atomic
def crear_borrador_recepcion(
    *, actor, provider_id, document_type, document_number,
    received_on, lines, notes="",
):
    _autorizar(actor, "warehouse.manage_receiving")
    if not lines:
        raise ValidationError("La recepción debe contener al menos un producto.")
    ids = [line["order_item_id"] for line in lines]
    if len(set(ids)) != len(ids):
        raise ValidationError("No puedes repetir una línea del pedido en una recepción.")
    provider = Provider.objects.get(pk=provider_id)
    detalles = {
        item.pk: item for item in PurchaseOrderItem.objects.select_related("order")
        .filter(pk__in=ids)
    }
    if len(detalles) != len(ids):
        raise ValidationError("Algunos productos del pedido no existen.")
    for row in lines:
        item = detalles[row["order_item_id"]]
        if item.order.provider_id != provider.pk:
            raise ValidationError("Todos los productos deben pertenecer a la misma editorial.")
        if item.order.status not in (
            PurchaseOrder.Status.SENT,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
        ):
            raise ValidationError("Solo puedes recepcionar pedidos enviados y aún pendientes.")
        if row["quantity_arrived"] != row["quantity_accepted"] + row["quantity_observed"]:
            raise ValidationError("Cantidad llegada debe ser igual a aceptada más observada.")
    recepcion = GoodsReceipt(
        provider=provider,
        document_type=document_type,
        document_number=document_number.strip().upper(),
        received_on=received_on,
        notes=notes.strip(),
        created_by=actor,
    )
    recepcion.full_clean()
    recepcion.save()
    for row in lines:
        linea = GoodsReceiptLine(
            receipt=recepcion,
            order_item=detalles[row["order_item_id"]],
            quantity_arrived=row["quantity_arrived"],
            quantity_accepted=row["quantity_accepted"],
            quantity_observed=row["quantity_observed"],
            notes=row.get("notes", "").strip(),
        )
        linea.full_clean()
        linea.save()
    GoodsReceiptEvent.objects.create(
        receipt=recepcion, actor=actor, action="created",
        details={"items": len(lines)},
    )
    return recepcion


@transaction.atomic
def validar_recepcion(*, actor, receipt_id):
    _autorizar(actor, "warehouse.validate_receiving")
    receipt = GoodsReceipt.objects.select_for_update().get(pk=receipt_id)
    if receipt.status != GoodsReceipt.Status.DRAFT:
        raise ValidationError("Esta recepción ya fue validada.")
    if not receipt.document_number.strip():
        raise ValidationError("Registra el número del documento del proveedor.")

    filas = list(
        GoodsReceiptLine.objects.select_related("order_item__order")
        .filter(receipt=receipt).order_by("pk")
    )
    if not filas:
        raise ValidationError("Una recepción sin productos no puede validarse.")
    ids_pedidos = sorted({fila.order_item.order_id for fila in filas})
    pedidos = {
        item.pk: item for item in PurchaseOrder.objects.select_for_update()
        .filter(pk__in=ids_pedidos).order_by("pk")
    }
    for pedido in pedidos.values():
        if pedido.provider_id != receipt.provider_id or pedido.status not in (
            PurchaseOrder.Status.SENT, PurchaseOrder.Status.PARTIALLY_RECEIVED,
        ):
            raise ValidationError("Hay un pedido que no está pendiente de recepción.")

    ids_lineas = [fila.order_item_id for fila in filas]
    anteriores = {
        row["order_item_id"]: row["total"] for row in
        GoodsReceiptLine.objects.filter(
            order_item_id__in=ids_lineas,
            receipt__status=GoodsReceipt.Status.VALIDATED,
        ).values("order_item_id").annotate(total=Sum("quantity_accepted"))
    }
    for fila in filas:
        if fila.quantity_arrived != fila.quantity_accepted + fila.quantity_observed:
            raise ValidationError("Hay cantidades de recepción que no cuadran.")
        if anteriores.get(fila.order_item_id, 0) + fila.quantity_accepted > fila.order_item.quantity_ordered:
            raise ValidationError(
                f"Se excede la cantidad solicitada para {fila.order_item.product_name_snapshot}."
            )

    receipt.status = GoodsReceipt.Status.VALIDATED
    receipt.validated_by = actor
    receipt.validated_at = timezone.now()
    receipt.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])
    GoodsReceiptEvent.objects.create(
        receipt=receipt, actor=actor, action="validated",
        details={
            "accepted": sum(row.quantity_accepted for row in filas),
            "observed": sum(row.quantity_observed for row in filas),
        },
    )

    for pedido in pedidos.values():
        lineas_pedido = list(
            PurchaseOrderItem.objects.filter(order=pedido).only("id", "quantity_ordered")
        )
        total_aceptado = {
            row["order_item_id"]: row["total"] for row in
            GoodsReceiptLine.objects.filter(
                order_item__order=pedido,
                receipt__status=GoodsReceipt.Status.VALIDATED,
            ).values("order_item_id").annotate(total=Sum("quantity_accepted"))
        }
        if all(total_aceptado.get(item.pk, 0) == item.quantity_ordered for item in lineas_pedido):
            estado_nuevo = PurchaseOrder.Status.RECEIVED
        elif any(total_aceptado.values()):
            estado_nuevo = PurchaseOrder.Status.PARTIALLY_RECEIVED
        else:
            estado_nuevo = pedido.status
        if estado_nuevo != pedido.status:
            anterior = pedido.status
            pedido.status = estado_nuevo
            pedido.save(update_fields=["status", "updated_at"])
            PurchaseOrderEvent.objects.create(
                order=pedido, actor=actor, event_type="receipt_validated",
                from_status=anterior, to_status=estado_nuevo,
                details={"receipt_id": receipt.pk},
            )
    return receipt


def saldos_pedido(*, actor, order_id):
    _autorizar(actor, "warehouse.view_receiving")
    pedido = PurchaseOrder.objects.get(pk=order_id)
    lineas = PurchaseOrderItem.objects.filter(order=pedido)
    aceptadas = {
        row["order_item_id"]: row["total"] for row in
        GoodsReceiptLine.objects.filter(
            order_item__order=pedido,
            receipt__status=GoodsReceipt.Status.VALIDATED,
        ).values("order_item_id").annotate(total=Sum("quantity_accepted"))
    }
    return {
        "pedido_id": pedido.pk,
        "editorial": pedido.provider_name_snapshot,
        "colegio": pedido.school_name_snapshot,
        "estado_pedido": pedido.status,
        "productos": [
            {
                "item_id": item.pk,
                "producto": item.product_name_snapshot,
                "cantidad_solicitada": item.quantity_ordered,
                "cantidad_aceptada": aceptadas.get(item.pk, 0),
                "cantidad_pendiente": max(0, item.quantity_ordered - aceptadas.get(item.pk, 0)),
            }
            for item in lineas
        ],
    }
