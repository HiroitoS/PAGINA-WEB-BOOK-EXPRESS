"""Observaciones de conteo al cierre de una distribución.

Registrar que faltan libros y que posteriormente aparecen no crea stock,
no supone ventas y no es el cierre de conciliación comercial.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from warehouse.models import (
    DistributionDispatch, DistributionOperation, DistributionOperationEvent,
)


KINDS = {"not_found", "count_error", "teacher_delivery", "damaged", "other"}


@transaction.atomic
def report_close_difference(operation_id, actor, *, idempotency_key, line_id,
                            quantity, category, note):
    operation = get_object_or_404(
        DistributionOperation.objects.select_for_update(), pk=operation_id,
    )
    dispatch = get_object_or_404(
        DistributionDispatch, operation=operation,
        status=DistributionDispatch.Status.RECEIVED,
    )
    if category not in KINDS or quantity < 1 or len(note.strip()) < 20:
        raise ValidationError("Indica categoría, cantidad y sustento de al menos 20 caracteres.")
    line = get_object_or_404(dispatch.lines, pk=line_id)
    existing = DistributionOperationEvent.objects.filter(
        operation=operation, action="close_diff_reported",
        current__idempotency_key=str(idempotency_key),
    ).first()
    payload = {
        "idempotency_key": str(idempotency_key),
        "line_id": line.pk, "quantity": quantity,
        "category": category, "note": note.strip(),
    }
    if existing:
        if existing.current != payload:
            raise ValidationError("La clave ya corresponde a una observación diferente.")
        return operation, existing, False
    previous_reports = DistributionOperationEvent.objects.filter(
        operation=operation, action="close_diff_reported",
        current__line_id=line.pk,
    )
    reported_total = sum(event.current.get("quantity", 0) for event in previous_reports)
    if reported_total + quantity > line.quantity:
        raise ValidationError(
            "Las diferencias acumuladas no pueden superar los libros entregados del lote."
        )
    event = DistributionOperationEvent.objects.create(
        operation=operation, actor=actor, action="close_diff_reported",
        reason=note.strip()[:500], current=payload,
    )
    return operation, event, True


@transaction.atomic
def record_later_finding(operation_id, actor, *, idempotency_key, report_id,
                         quantity, location_note):
    operation = get_object_or_404(
        DistributionOperation.objects.select_for_update(), pk=operation_id,
    )
    report = get_object_or_404(
        DistributionOperationEvent, operation=operation,
        action="close_diff_reported", pk=report_id,
    )
    if quantity < 1 or len(location_note.strip()) < 20:
        raise ValidationError("Detalla cuántos libros aparecieron y dónde estaban.")
    payload = {
        "idempotency_key": str(idempotency_key),
        "report_id": report.pk, "quantity": quantity,
        "location_note": location_note.strip(),
    }
    existing = DistributionOperationEvent.objects.filter(
        operation=operation, action="close_diff_found",
        current__idempotency_key=str(idempotency_key),
    ).first()
    if existing:
        if existing.current != payload:
            raise ValidationError("La clave ya corresponde a otro hallazgo.")
        return operation, existing, False
    prior = DistributionOperationEvent.objects.filter(
        operation=operation, action="close_diff_found",
        current__report_id=report.pk,
    )
    found = sum(event.current.get("quantity", 0) for event in prior)
    if found + quantity > report.current["quantity"]:
        raise ValidationError("El hallazgo supera la cantidad inicialmente observada.")
    event = DistributionOperationEvent.objects.create(
        operation=operation, actor=actor, action="close_diff_found",
        reason=location_note.strip()[:500], current=payload,
    )
    # El hallazgo es información de conteo, no una recepción ni un ajuste.
    return operation, event, True
