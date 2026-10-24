"""Operaciones de pedidos. Cambios transaccionales y auditados."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import usuario_tiene_permiso
from purchasing.models import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem


def _autorizar(actor, permiso):
    if not actor or not actor.is_authenticated or not usuario_tiene_permiso(actor, permiso):
        raise PermissionDenied("No tienes permiso para realizar esta operación.")


@transaction.atomic
def actualizar_cantidad_borrador(*, pedido_id, detalle_id, cantidad, actor):
    _autorizar(actor, "purchasing.manage_purchasing")
    pedido = PurchaseOrder.objects.select_for_update().get(pk=pedido_id)
    if pedido.status != PurchaseOrder.Status.DRAFT:
        raise ValidationError("Solo se pueden modificar cantidades de pedidos en borrador.")
    if cantidad < 1:
        raise ValidationError("La cantidad debe ser mayor que cero.")
    detalle = PurchaseOrderItem.objects.select_for_update().get(pk=detalle_id, order=pedido)
    anterior = detalle.quantity_ordered
    if cantidad != anterior:
        detalle.quantity_ordered = cantidad
        detalle.full_clean()
        detalle.save(update_fields=["quantity_ordered", "updated_at"])
        PurchaseOrderEvent.objects.create(
            order=pedido, actor=actor, event_type="quantity_changed",
            from_status=pedido.status, to_status=pedido.status,
            details={"item_id": detalle.pk, "previous": anterior, "new": cantidad},
        )
    return pedido


@transaction.atomic
def actualizar_cantidades_borrador(*, pedido_id, items, actor):
    """Actualiza todas las líneas como una sola operación o no modifica ninguna."""
    _autorizar(actor, "purchasing.manage_purchasing")
    pedido = PurchaseOrder.objects.select_for_update().get(pk=pedido_id)
    if pedido.status != PurchaseOrder.Status.DRAFT:
        raise ValidationError("Solo puedes cambiar un pedido en borrador.")
    ids = [item["item_id"] for item in items]
    if len(set(ids)) != len(ids):
        raise ValidationError("Hay productos repetidos en la solicitud.")
    encontrados = PurchaseOrderItem.objects.filter(order=pedido, pk__in=ids).count()
    if encontrados != len(ids):
        raise ValidationError("Algunos productos no pertenecen a este pedido.")
    for item in items:
        actualizar_cantidad_borrador(
            pedido_id=pedido.pk,
            detalle_id=item["item_id"],
            cantidad=item["quantity"],
            actor=actor,
        )
    return pedido


@transaction.atomic
def aprobar_pedido(*, pedido_id, actor):
    _autorizar(actor, "purchasing.approve_purchasing")
    pedido = PurchaseOrder.objects.select_for_update().get(pk=pedido_id)
    if pedido.status != PurchaseOrder.Status.DRAFT:
        raise ValidationError("Solo se pueden aprobar pedidos en borrador.")
    if not pedido.items.exists():
        raise ValidationError("El pedido debe contener productos.")
    pedido.status = PurchaseOrder.Status.APPROVED
    pedido.approved_by = actor
    pedido.approved_at = timezone.now()
    pedido.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    PurchaseOrderEvent.objects.create(
        order=pedido, actor=actor, event_type="approved",
        from_status=PurchaseOrder.Status.DRAFT, to_status=pedido.status,
    )
    return pedido


@transaction.atomic
def registrar_envio_pedido(*, pedido_id, actor, evidencia):
    _autorizar(actor, "purchasing.record_purchase_dispatch")
    pedido = PurchaseOrder.objects.select_for_update().get(pk=pedido_id)
    if pedido.status != PurchaseOrder.Status.APPROVED:
        raise ValidationError("Solo se pueden registrar envíos de pedidos aprobados.")
    evidencia = (evidencia or "").strip()
    if not evidencia:
        raise ValidationError("Registra una referencia o evidencia del envío.")
    if len(evidencia) > 2000:
        raise ValidationError("La evidencia no puede superar 2000 caracteres.")
    pedido.status = PurchaseOrder.Status.SENT
    pedido.sent_at = timezone.now()
    pedido.save(update_fields=["status", "sent_at", "updated_at"])
    PurchaseOrderEvent.objects.create(
        order=pedido, actor=actor, event_type="sent",
        from_status=PurchaseOrder.Status.APPROVED, to_status=pedido.status,
        notes=evidencia,
    )
    return pedido
