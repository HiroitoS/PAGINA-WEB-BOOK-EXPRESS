"""Salidas auditables de inventario; la recepción original permanece inmutable."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import StockEntry, StockMovement


def saldo_entrada(entry):
    """Conformes disponibles de una entrada, incluidas las cortesías descontadas."""
    variacion = StockMovement.objects.filter(source_entry=entry).aggregate(
        total=Sum("quantity_delta")
    )["total"] or 0
    return entry.quantity_available + variacion


@transaction.atomic
def registrar_cortesia(
    *, actor, stock_entry_id, school_id, quantity, recipient_name,
    recipient_role, idempotency_key, notes="",
):
    if not actor or not actor.is_authenticated or not usuario_tiene_permiso(
        actor, "warehouse.manage_stock_courtesies"
    ):
        raise PermissionDenied("No tienes permiso para registrar cortesías.")

    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValidationError("La cantidad debe ser un entero mayor que cero.")

    recipient_name = str(recipient_name or "").strip()
    recipient_role = str(recipient_role or "").strip()
    notes = str(notes or "").strip()
    if not recipient_name or not recipient_role:
        raise ValidationError("Identifica a la persona que recibe la cortesía.")
    if len(recipient_name) > 200 or len(recipient_role) > 80 or len(notes) > 500:
        raise ValidationError("Los datos de la cortesía superan la longitud permitida.")

    try:
        entry = StockEntry.objects.select_for_update().select_related(
            "receipt_line__order_item__order", "product",
        ).get(pk=stock_entry_id)
    except StockEntry.DoesNotExist:
        raise ValidationError("No existe la entrada de mercadería seleccionada.")

    origen = entry.receipt_line.order_item.order
    if origen.school_id is None or origen.school_id != school_id:
        raise ValidationError(
            "La cortesía debe salir de la mercadería asignada al mismo colegio."
        )

    anterior = StockMovement.objects.filter(idempotency_key=idempotency_key).first()
    if anterior is not None:
        if (
            anterior.source_entry_id != entry.pk
            or anterior.school_id != school_id
            or anterior.quantity_delta != -quantity
            or anterior.recipient_name != recipient_name
            or anterior.recipient_role != recipient_role
            or anterior.notes != notes
            or anterior.kind != StockMovement.Kind.COURTESY
        ):
            raise ValidationError("La clave de operación ya corresponde a otra salida.")
        return anterior, False

    if saldo_entrada(entry) < quantity:
        raise ValidationError("No existe stock conforme suficiente para esta cortesía.")

    movimiento = StockMovement.objects.create(
        source_entry=entry,
        kind=StockMovement.Kind.COURTESY,
        quantity_delta=-quantity,
        school_id=school_id,
        recipient_name=recipient_name,
        recipient_role=recipient_role,
        notes=notes,
        unit_cost_snapshot=entry.unit_cost_snapshot,
        idempotency_key=idempotency_key,
        created_by=actor,
    )
    return movimiento, True
