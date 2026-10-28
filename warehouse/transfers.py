"""P-08.2: traslados confirmados por lote entre ubicaciones físicas.

Un traslado no crea StockEntry y no afecta el stock global. Las entradas
históricas sin ubicación requieren conciliación antes de cualquier traslado.
Se bloquea cada StockEntry al confirmar para evitar sobretraslados y competir
correctamente con las cortesías, que usan el mismo bloqueo.
"""
from collections import defaultdict

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import StockEntry, StockMovement, StockTransfer, WarehouseLocation


def posiciones_lotes(entries):
    """Saldo conforme por (lote, ubicación); no incluye observados.

    StockEntryLocation es una foto del saldo al asignar la ubicación.
    Las cortesías anteriores a la conciliación ya están incluidas en la foto;
    las posteriores disminuyen la ubicación inicial. Los traslados son
    internos: restan en origen y suman en destino, nunca en global.
    """
    entries = list(entries)
    if not entries:
        return {}
    ids = [entry.pk for entry in entries]
    asignaciones = {
        entry.pk: getattr(entry, "initial_location", None)
        for entry in entries
    }
    saldos = defaultdict(int)
    for entry in entries:
        asignacion = asignaciones[entry.pk]
        if asignacion:
            saldos[(entry.pk, asignacion.location_id)] += asignacion.available_at_assignment

    for move in StockMovement.objects.filter(
        source_entry_id__in=ids
    ).values("source_entry_id", "quantity_delta", "created_at"):
        asignacion = asignaciones[move["source_entry_id"]]
        if asignacion and move["created_at"] > asignacion.created_at:
            saldos[(move["source_entry_id"], asignacion.location_id)] += move["quantity_delta"]

    for move in StockTransfer.objects.filter(
        stock_entry_id__in=ids
    ).values("stock_entry_id", "source_id", "destination_id").annotate(
        total=Sum("quantity")
    ):
        saldos[(move["stock_entry_id"], move["source_id"])] -= move["total"]
        saldos[(move["stock_entry_id"], move["destination_id"])] += move["total"]
    return dict(saldos)


def saldo_en_ubicacion(entry, location_id):
    entry = StockEntry.objects.select_related("initial_location").get(pk=entry.pk)
    return posiciones_lotes([entry]).get((entry.pk, location_id), 0)


@transaction.atomic
def registrar_traslado(
    *, actor, stock_entry_id, source_id, destination_id,
    quantity, idempotency_key, notes="",
):
    if not actor or not actor.is_authenticated or not usuario_tiene_permiso(
        actor, "warehouse.manage_stock_transfers"
    ):
        raise PermissionDenied("No tienes permiso para registrar traslados.")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValidationError("La cantidad debe ser un entero mayor que cero.")
    if source_id == destination_id:
        raise ValidationError("El origen y el destino deben ser diferentes.")
    notes = str(notes or "").strip()
    if len(notes) > 500:
        raise ValidationError("La observación supera los 500 caracteres.")

    try:
        entry = StockEntry.objects.select_for_update().select_related(
            "initial_location",
        ).get(pk=stock_entry_id)
    except StockEntry.DoesNotExist:
        raise ValidationError("El lote de mercadería ya no existe.")

    anterior = StockTransfer.objects.filter(idempotency_key=idempotency_key).first()
    if anterior is not None:
        if (
            anterior.stock_entry_id != entry.pk
            or anterior.source_id != source_id
            or anterior.destination_id != destination_id
            or anterior.quantity != quantity
            or anterior.notes != notes
        ):
            raise ValidationError("Esta clave ya corresponde a otro traslado.")
        return anterior, False

    if not hasattr(entry, "initial_location"):
        raise ValidationError(
            "Antes del traslado debes conciliar la ubicación física de este lote."
        )
    ubicaciones = {
        loc.pk: loc for loc in WarehouseLocation.objects.filter(
            pk__in=[source_id, destination_id]
        )
    }
    if len(ubicaciones) != 2 or any(not loc.is_active for loc in ubicaciones.values()):
        raise ValidationError("Selecciona dos ubicaciones activas y válidas.")

    saldo = saldo_en_ubicacion(entry, source_id)
    if saldo < quantity:
        raise ValidationError(
            f"Solo hay {max(saldo, 0)} unidades conformes en el almacén de origen."
        )
    move = StockTransfer.objects.create(
        stock_entry=entry,
        source_id=source_id, destination_id=destination_id,
        quantity=quantity, idempotency_key=idempotency_key,
        notes=notes, unit_cost_snapshot=entry.unit_cost_snapshot,
        created_by=actor,
    )
    return move, True
