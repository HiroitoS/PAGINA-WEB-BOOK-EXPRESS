"""Ingreso manual-controlado desde recepciones validadas, sin doble registro."""
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import GoodsReceipt, GoodsReceiptLine, StockEntry


@transaction.atomic
def registrar_entrada_recepcion(*, actor, receipt_id):
    if not actor or not actor.is_authenticated or not usuario_tiene_permiso(actor, "warehouse.validate_receiving"):
        raise ValidationError("No tienes permiso para ingresar existencias.")
    receipt = GoodsReceipt.objects.select_for_update().get(pk=receipt_id)
    if receipt.status != GoodsReceipt.Status.VALIDATED:
        raise ValidationError("Solo las recepciones validadas ingresan a Inventario.")
    lines = list(GoodsReceiptLine.objects.select_related("order_item").filter(receipt=receipt))
    if not lines:
        raise ValidationError("La recepción no contiene productos.")
    created = 0
    for line in lines:
        entry, is_new = StockEntry.objects.get_or_create(
            receipt_line=line,
            defaults={
                "product_id": line.order_item.product_id,
                "quantity_available": line.quantity_accepted + line.quantity_extra,
                "quantity_quarantined": line.quantity_observed,
                "quantity_extra": line.quantity_extra,
                "posted_by": actor,
            },
        )
        if not is_new and (
            entry.quantity_available != line.quantity_accepted + line.quantity_extra
            or entry.quantity_quarantined != line.quantity_observed
            or entry.quantity_extra != line.quantity_extra
        ):
            raise ValidationError("La entrada ya existe con otras cantidades. Requiere auditoría.")
        created += int(is_new)
    return {"receipt_id": receipt.pk, "new_entries": created, "total_lines": len(lines)}
