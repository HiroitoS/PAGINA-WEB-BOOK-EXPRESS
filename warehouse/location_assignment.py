"""Asignación inicial de ubicación por lote (P-08.1b).

El ingreso documental ya existe en StockEntry y nunca se crea otra entrada.
Una conciliación solo identifica físicamente el lote neto, después de
descontar las cortesías. No registra un traslado ni modifica saldos globales.
"""
from django.core.exceptions import ValidationError
from django.db import transaction

from warehouse.models import StockEntry, StockEntryLocation, WarehouseLocation
from warehouse.stock_movements import saldo_entrada


def _principal_activo():
    principal_ids = list(
        WarehouseLocation.objects.filter(
            kind=WarehouseLocation.Kind.MAIN, is_active=True
        ).values_list("pk", flat=True)[:2]
    )
    if len(principal_ids) > 1:
        raise ValidationError(
            "Hay varios almacenes principales activos. Define uno antes de validar más recepciones."
        )
    return principal_ids[0] if principal_ids else None


def asignar_nueva_entrada(*, entry, actor):
    """Llamar solo cuando se acaba de crear StockEntry.

    En instalaciones antiguas sin almacén principal, mantiene la entrada
    sin ubicación para no inventar un depósito ni bloquear pruebas existentes.
    """
    main_id = _principal_activo()
    if main_id is None:
        return None
    assigned, _ = StockEntryLocation.objects.get_or_create(
        stock_entry=entry,
        defaults={
            "location_id": main_id,
            "origin": StockEntryLocation.Origin.RECEIPT,
            "available_at_assignment": entry.quantity_available,
            "observed_at_assignment": entry.quantity_quarantined,
            "assigned_by": actor,
        },
    )
    if assigned.location_id != main_id:
        raise ValidationError(
            "El lote ya está asociado a otro lugar; requiere revisión de almacén."
        )
    return assigned


@transaction.atomic
def conciliar_lotes(*, location, entry_ids, actor, notes=""):
    """Confirma lotes COMPLETOS después de cotejar su ubicación física.

    El bloqueo por StockEntry impide asignar el mismo lote a dos ubicaciones.
    Una petición repetida al mismo sitio es idempotente. No fracciona lotes
    entre tiendas: ese caso debe esperar la conciliación por partidas.
    """
    if not location.is_active:
        raise ValidationError("La ubicación debe estar activa.")
    if not entry_ids or len(entry_ids) > 100:
        raise ValidationError("Selecciona entre 1 y 100 lotes para conciliar.")
    ids = sorted(set(entry_ids))
    entries = list(
        StockEntry.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    )
    if len(entries) != len(ids):
        raise ValidationError("Algunos lotes ya no existen. Actualiza la pantalla.")
    existing = {
        item.stock_entry_id: item
        for item in StockEntryLocation.objects.filter(stock_entry_id__in=ids)
    }
    for entry in entries:
        assigned = existing.get(entry.pk)
        if assigned is not None and assigned.location_id != location.pk:
            raise ValidationError(
                f"El lote {entry.pk} ya fue asignado a otra ubicación."
            )
    created = 0
    for entry in entries:
        if entry.pk in existing:
            continue
        available = saldo_entrada(entry)
        if available < 0:
            raise ValidationError(f"El lote {entry.pk} registra un saldo inválido.")
        if available == 0 and entry.quantity_quarantined == 0:
            raise ValidationError(
                f"El lote {entry.pk} ya no tiene unidades físicas que asignar."
            )
        StockEntryLocation.objects.create(
            stock_entry=entry,
            location=location,
            origin=StockEntryLocation.Origin.RECONCILIATION,
            available_at_assignment=available,
            observed_at_assignment=entry.quantity_quarantined,
            assigned_by=actor,
            notes=notes,
        )
        created += 1
    return {"assigned": created, "already_assigned": len(entries) - created}
