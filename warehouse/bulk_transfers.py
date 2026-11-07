"""P-08.3: traslado confirmado de varios lotes de una misma guía.

La transacción es indivisible: o se trasladan todos los renglones elegidos
o no cambia ningún saldo. No representa un envío en tránsito.
"""
import hashlib
import json
from uuid import UUID, uuid5

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import (
    GoodsReceipt, StockEntry, StockTransferBatch,
)
from warehouse.transfers import registrar_traslado


@transaction.atomic
def registrar_traslado_por_guia(
    *, actor, receipt_id, source_id, destination_id, items,
    idempotency_key, entrega_confirmada=False, notes="",
):
    if not actor or not actor.is_authenticated or not usuario_tiene_permiso(
        actor, "warehouse.manage_stock_transfers"
    ):
        raise PermissionDenied("No tienes permiso para registrar traslados.")

    if source_id == destination_id:
        raise ValidationError("Selecciona dos almacenes diferentes.")
    if entrega_confirmada is not True:
        raise ValidationError(
            "Confirma que los libros ya están físicamente en el destino."
        )

    notes = str(notes or "").strip()
    if len(notes) > 500:
        raise ValidationError("La observación supera los 500 caracteres.")
    if not items or len(items) > 200:
        raise ValidationError("Selecciona entre 1 y 200 lotes de una misma guía.")

    selected = sorted(items, key=lambda item: item["stock_entry_id"])
    ids = [item["stock_entry_id"] for item in selected]
    if len(ids) != len(set(ids)):
        raise ValidationError("No puedes repetir un lote en el mismo traslado.")

    try:
        request_key = UUID(str(idempotency_key))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError("La referencia del traslado no es válida.") from exc

    canonical = {
        "receipt_id": receipt_id,
        "source_id": source_id,
        "destination_id": destination_id,
        "notes": notes,
        "items": [
            (item["stock_entry_id"], item["quantity"]) for item in selected
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True).encode("utf-8")
    ).hexdigest()

    try:
        # Serializa modificaciones de una guía y permite reintentos consistentes.
        receipt = GoodsReceipt.objects.select_for_update().get(pk=receipt_id)
    except GoodsReceipt.DoesNotExist as exc:
        raise ValidationError("La guía seleccionada no existe.") from exc
    if (
        receipt.status != GoodsReceipt.Status.VALIDATED
        or receipt.document_type != GoodsReceipt.DocumentType.GUIDE
    ):
        raise ValidationError("Solo se pueden trasladar guías validadas.")

    batch, created = StockTransferBatch.objects.get_or_create(
        idempotency_key=request_key,
        defaults={
            "receipt": receipt,
            "source_id": source_id,
            "destination_id": destination_id,
            "request_hash": fingerprint,
            "notes": notes,
            "created_by": actor,
        },
    )
    if not created:
        if batch.request_hash != fingerprint:
            raise ValidationError(
                "Esta confirmación ya corresponde a otro traslado. Recarga la selección."
            )
        return batch, list(batch.transfers.order_by("stock_entry_id")), False

    found = set(StockEntry.objects.filter(
        pk__in=ids, receipt_line__receipt_id=receipt_id,
    ).values_list("pk", flat=True))
    if len(found) != len(ids):
        raise ValidationError(
            "La selección contiene libros ajenos a la guía indicada."
        )

    movements = []
    for item in selected:
        move, _ = registrar_traslado(
            actor=actor,
            stock_entry_id=item["stock_entry_id"],
            source_id=source_id,
            destination_id=destination_id,
            quantity=item["quantity"],
            idempotency_key=uuid5(request_key, str(item["stock_entry_id"])),
            entrega_confirmada=True,
            notes=notes,
        )
        move.batch = batch
        move.save(update_fields=["batch"])
        movements.append(move)
    return batch, movements, True
