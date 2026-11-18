"""B3: disponibilidad y reserva de lotes para entregas de adopción.

Reserva física != despacho, venta, GRE emitida ni transferencia de stock.
Cada reserva y cada traslado directo bloquean la misma StockEntry.
"""
from collections import defaultdict

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from warehouse.models import (
    DistributionOperation, DistributionOperationEvent,
    DistributionStockReservation, StockEntry, StockTransfer,
)
from warehouse.transfers import posiciones_lotes


def _entries(operation, *, lock=False):
    product_ids = list(operation.items.values_list("product_id", flat=True))
    traveled = StockTransfer.objects.filter(
        destination_id=operation.source_id,
    ).values("stock_entry_id")
    qs = StockEntry.objects.filter(
        product_id__in=product_ids,
        receipt_line__order_item__order__school_id=operation.school_id,
    ).filter(
        Q(initial_location__location_id=operation.source_id)
        | Q(pk__in=traveled)
    ).select_related(
        "initial_location", "product", "receipt_line__receipt",
    ).order_by("pk")
    # No DISTINCT junto a FOR UPDATE: PostgreSQL no permite esa combinación.
    if lock:
        qs = qs.select_for_update(of=("self",))
    return list(qs)


def _reservados(entries, location_id):
    ids = [entry.pk for entry in entries]
    rows = DistributionStockReservation.objects.filter(
        stock_entry_id__in=ids, source_id=location_id,
        status=DistributionStockReservation.Status.ACTIVE,
    ).values("stock_entry_id").annotate(qty=Sum("quantity"))
    return {row["stock_entry_id"]: row["qty"] for row in rows}


def _reservas_operacion(operation):
    return list(operation.stock_reservations.select_related(
        "stock_entry__product", "stock_entry__receipt_line__receipt",
    ).order_by("stock_entry_id"))


def resumen_preparacion(operation):
    """Vista sin movimientos. Cantidades libres excluyen todas las reservas activas."""
    entries = _entries(operation)
    saldo = posiciones_lotes(entries)
    reservas = _reservados(entries, operation.source_id)
    propias = {r.stock_entry_id: r for r in _reservas_operacion(operation)}
    by_product = defaultdict(list)
    for entry in entries:
        actual = max(0, saldo.get((entry.pk, operation.source_id), 0))
        reserved = reservas.get(entry.pk, 0)
        if actual <= 0:
            continue
        by_product[entry.product_id].append({
            "stock_entry_id": entry.pk,
            "product_id": entry.product_id,
            "product": entry.product.name,
            "receipt_number": entry.receipt_line.receipt.document_number,
            "physical_at_origin": actual,
            "reserved_global": reserved,
            "free": max(0, actual - reserved),
            "reserved_for_this_operation": (
                propias[entry.pk].quantity
                if entry.pk in propias and propias[entry.pk].status == "active"
                else 0
            ),
        })
    items = []
    for line in operation.items.all().order_by("pk"):
        options = by_product.get(line.product_id, [])
        own = sum(r["reserved_for_this_operation"] for r in options)
        free = sum(r["free"] for r in options)
        items.append({
            "product_id": line.product_id,
            "product": line.product_name_snapshot,
            "planned": line.quantity_planned,
            "free_at_origin": free,
            "already_reserved": own,
            "shortage": max(0, line.quantity_planned - free - own),
            "lots": options,
        })
    reserved_rows = _reservas_operacion(operation)
    return {
        "operation_id": operation.pk,
        "status": operation.status,
        "source_id": operation.source_id,
        "source": operation.source.name,
        "destination_id": operation.destination_id,
        "destination": operation.destination.name,
        "items": items,
        "can_reserve": (
            operation.status == DistributionOperation.Status.PLANNED
            and bool(items) and all(x["shortage"] == 0 for x in items)
        ),
        "reservations": [
            {
                "id": row.pk, "stock_entry_id": row.stock_entry_id,
                "product": row.stock_entry.product.name,
                "receipt_number": row.stock_entry.receipt_line.receipt.document_number,
                "quantity": row.quantity, "counted_quantity": row.counted_quantity,
                "status": row.status,
            }
            for row in reserved_rows
        ],
        "notice": (
            "Las unidades reservadas permanecen físicamente en su almacén de origen. "
            "Reservar no crea una GRE, no despacha, no traslada ni vende libros."
        ),
    }


@transaction.atomic
def reservar_operacion(operation_id, actor, lots=None):
    """Reserva por lotes elegidos o por FIFO, siempre dentro del mismo colegio."""
    operation = get_object_or_404(
        DistributionOperation.objects.select_for_update(), pk=operation_id,
    )
    if operation.status == DistributionOperation.Status.RESERVED:
        return operation, False
    if operation.status != DistributionOperation.Status.PLANNED:
        raise DjangoValidationError("Solo puedes reservar una entrega por preparar.")
    if not operation.adoption.is_current:
        raise DjangoValidationError("Revisa la adopción vigente antes de reservar.")
    if not operation.source.is_active or not operation.destination.is_active:
        raise DjangoValidationError("El origen y destino deben estar activos.")
    if operation.stock_reservations.exists():
        raise DjangoValidationError("Esta entrega ya tiene reservas anteriores. Revisa su historial.")

    entries = _entries(operation, lock=True)
    positions = posiciones_lotes(entries)
    reserved = _reservados(entries, operation.source_id)
    by_product = defaultdict(list)
    for entry in entries:
        available = (
            positions.get((entry.pk, operation.source_id), 0)
            - reserved.get(entry.pk, 0)
        )
        if available > 0:
            by_product[entry.product_id].append((entry, available))

    chosen = []
    planned_lines = list(operation.items.all().order_by("product_id"))
    if lots is not None:
        # El usuario puede elegir guías/lotes reales; no puede cambiar el colegio,
        # el almacén ni tomar cantidades reservadas por otra operación.
        eligible = {
            entry.pk: (entry, available)
            for entries_for_product in by_product.values()
            for entry, available in entries_for_product
        }
        chosen_ids = set()
        selected_by_product = defaultdict(int)
        for selection in lots:
            entry_id = selection["stock_entry_id"]
            quantity = selection["quantity"]
            if entry_id in chosen_ids:
                raise DjangoValidationError(
                    "Un mismo lote no puede figurar dos veces en la reserva."
                )
            chosen_ids.add(entry_id)
            found = eligible.get(entry_id)
            if not found:
                raise DjangoValidationError(
                    "Un lote elegido no pertenece a esta entrega o no tiene saldo "
                    "libre en el almacén indicado."
                )
            entry, available = found
            if quantity > available:
                raise DjangoValidationError(
                    f"El lote {entry_id} dispone de {available} unidades libres; "
                    f"no es posible reservar {quantity}."
                )
            selected_by_product[entry.product_id] += quantity
            chosen.append(DistributionStockReservation(
                operation=operation, stock_entry=entry, source_id=operation.source_id,
                quantity=quantity, reserved_by=actor,
            ))
        for line in planned_lines:
            if selected_by_product[line.product_id] != line.quantity_planned:
                raise DjangoValidationError(
                    f"{line.product_name_snapshot}: selecciona exactamente "
                    f"{line.quantity_planned} unidades entre sus lotes disponibles."
                )
    else:
        # Comportamiento anterior, conservado para compatibilidad.
        for line in planned_lines:
            missing = line.quantity_planned
            for entry, quantity in by_product.get(line.product_id, []):
                taken = min(missing, quantity)
                if taken:
                    chosen.append(DistributionStockReservation(
                        operation=operation, stock_entry=entry, source_id=operation.source_id,
                        quantity=taken, reserved_by=actor,
                    ))
                    missing -= taken
                if not missing:
                    break
            if missing:
                raise DjangoValidationError(
                    f"{line.product_name_snapshot}: faltan {missing} unidades conformes "
                    "no reservadas para completar la preparación en este almacén."
                )
    if not chosen:
        raise DjangoValidationError("La entrega no tiene libros para reservar.")

    DistributionStockReservation.objects.bulk_create(chosen)
    operation.status = DistributionOperation.Status.RESERVED
    operation.save(update_fields=["status", "updated_at"])
    DistributionOperationEvent.objects.create(
        operation=operation, actor=actor, action="stock_reserved",
        current={
            "operation_id": operation.pk,
            "status": operation.status,
            "stock_entries": [
                {"id": x.stock_entry_id, "quantity": x.quantity}
                for x in chosen
            ],
        },
    )
    return operation, True


@transaction.atomic
def confirmar_preparacion(operation_id, actor, counts):
    """Requiere conteo explícito por lote; diferencia no se acepta silenciosamente."""
    operation = get_object_or_404(
        DistributionOperation.objects.select_for_update(), pk=operation_id,
    )
    if operation.status != DistributionOperation.Status.RESERVED:
        raise DjangoValidationError("Primero reserva las unidades de esta entrega.")
    reservations = list(
        operation.stock_reservations.select_for_update().filter(
            status=DistributionStockReservation.Status.ACTIVE,
        ).order_by("pk")
    )
    expected_ids = {r.pk for r in reservations}
    received = {row["reservation_id"]: row["counted"] for row in counts}
    if not reservations or len(received) != len(counts) or set(received) != expected_ids:
        raise DjangoValidationError("Registra el conteo físico de todos los lotes reservados.")
    for reservation in reservations:
        if received[reservation.pk] != reservation.quantity:
            raise DjangoValidationError(
                f"El lote {reservation.stock_entry_id} presenta diferencia de conteo: "
                f"reservado {reservation.quantity}, contado {received[reservation.pk]}. "
                "No se confirma la preparación; solicita revisión física."
            )
    now = timezone.now()
    for reservation in reservations:
        reservation.counted_quantity = received[reservation.pk]
        reservation.counted_at = now
        reservation.counted_by = actor
        reservation.save(update_fields=[
            "counted_quantity", "counted_at", "counted_by", "updated_at",
        ])
    operation.status = DistributionOperation.Status.PREPARED
    operation.save(update_fields=["status", "updated_at"])
    DistributionOperationEvent.objects.create(
        operation=operation, actor=actor, action="prepared",
        current={"operation_id": operation.pk, "status": operation.status,
                 "counted_total": sum(received.values())},
    )
    return operation


def liberar_reservas_operacion(operation):
    """Usar solo dentro de transacción tras bloquear la operación."""
    operation.stock_reservations.filter(
        status=DistributionStockReservation.Status.ACTIVE,
    ).update(status=DistributionStockReservation.Status.RELEASED, updated_at=timezone.now())
