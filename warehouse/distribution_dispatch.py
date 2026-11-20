"""B4: documento interno, salida física y recepción por lote de adopción.

Esta capa NO emite comprobantes tributarios, GRE ni reconoce ventas. La
documentación tributaria real debe verificarse fuera del sistema cuando aplique.
"""
from collections import defaultdict
import re

from django.core.exceptions import ValidationError as BusinessError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404

from accounts.permissions import usuario_tiene_permiso
from django.utils import timezone

from warehouse.models import (
    DistributionArrivalIncident, DistributionDispatch, DistributionDispatchLine,
    DistributionOperation, DistributionOperationEvent, DistributionStockReservation,
    StockEntry,
)
from warehouse.transfers import posiciones_lotes
from warehouse.fair_destination_policy import validar_feria_por_colegio


GRE_REFERENCE_PATTERN = re.compile(r"EG[A-Z0-9]{2}-[0-9]{1,8}\Z")
RECEIVER_PATTERN = re.compile(
    r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+(?:[ '-][A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)+\Z"
)


def validate_receiver_name(value):
    name = " ".join(value.strip().split())
    if len(name) < 6 or len(name) > 180 or not RECEIVER_PATTERN.fullmatch(name):
        raise BusinessError(
            "Indica nombres y apellidos reales de quien recibe (mínimo dos palabras, "
            "sin números ni símbolos). El registro queda auditado."
        )
    return name


def _operation_locked(operation_id):
    return get_object_or_404(
        DistributionOperation.objects.select_for_update().select_related(
            "source", "destination", "school", "adoption",
        ),
        pk=operation_id,
    )


def output_dispatch(operation):
    dispatch = DistributionDispatch.objects.select_related(
        "operation", "operation__source", "operation__destination",
        "document_by", "dispatched_by", "received_by",
    ).filter(operation_id=operation.pk).first()
    if dispatch is None:
        return {
            "exists": False, "operation_id": operation.pk,
            "operation_status": operation.status,
            "can_create": operation.status == DistributionOperation.Status.PREPARED,
            "message": "El documento interno se crea cuando la entrega está preparada.",
        }
    lines = list(dispatch.lines.select_related(
        "reservation__stock_entry__product",
        "reservation__stock_entry__receipt_line__receipt",
    ))
    diagnosis_events = DistributionOperationEvent.objects.filter(
        operation=operation, action="arrival_diagnosed",
    ).select_related("actor").order_by("created_at", "pk")
    diagnoses = [{
        "incident_id": event.current.get("incident_id"),
        "details": event.current.get("details", []),
        "note": event.reason, "recorded_at": event.created_at,
        "recorded_by": event.actor.get_username(),
    } for event in diagnosis_events]
    incident_rows = list(dispatch.arrival_incidents.select_related(
        "reported_by", "resolved_by",
    ).order_by("-created_at", "-pk"))
    return {
        "exists": True, "id": dispatch.pk, "operation_id": operation.pk,
        "document_number": dispatch.document_number,
        "status": dispatch.status, "operation_status": operation.status,
        "mode": operation.mode, "school": operation.school.name,
        "operation_name": operation.operation_name,
        "source": operation.source.name, "source_id": operation.source_id,
        "destination": operation.destination.name, "destination_id": operation.destination_id,
        "planned_on": operation.scheduled_on, "created_at": dispatch.created_at,
        "dispatched_at": dispatch.dispatched_at, "received_at": dispatch.received_at,
        "recipient_name": dispatch.recipient_name,
        "responsible_name": operation.responsible_name,
        "document_by": dispatch.document_by.get_full_name().strip()
        or dispatch.document_by.get_username(),
        "dispatched_by": (
            dispatch.dispatched_by.get_full_name().strip()
            or dispatch.dispatched_by.get_username()
        ) if dispatch.dispatched_by_id else None,
        "received_by": (
            dispatch.received_by.get_full_name().strip()
            or dispatch.received_by.get_username()
        ) if dispatch.received_by_id else None,
        "evidence_kind": dispatch.evidence_kind,
        "external_guide_reference": dispatch.external_guide_reference,
        "exception_justification": dispatch.exception_justification,
        "notes": dispatch.notes,
        "lines": [{
            "id": row.pk,
            "reservation_id": row.reservation_id,
            "product": row.reservation.stock_entry.product.name,
            "receipt_number": row.reservation.stock_entry.receipt_line.receipt.document_number,
            "quantity": row.quantity,
            "stock_entry_id": row.reservation.stock_entry_id,
        } for row in lines],
        "total": sum(line.quantity for line in lines),
        "arrival_diagnoses": diagnoses,
        "arrival_incidents": [
            {
                "id": item.pk, "status": item.status,
                "receiver_name": item.receiver_name,
                "observations": item.observations,
                "counts": item.counts_snapshot,
                "reported_at": item.created_at,
                "reported_by": item.reported_by.get_username(),
                "resolved_at": item.resolved_at,
                "resolved_by": item.resolved_by.get_username()
                if item.resolved_by_id else None,
                "resolution_note": item.resolution_note,
            }
            for item in incident_rows
        ],
        "open_incident": any(item.status == DistributionArrivalIncident.Status.OPEN
                             for item in incident_rows),
        "notice": (
            "Documento INTERNO de control de mercadería, no es una GRE ni prueba "
            "de emisión/aceptación SUNAT. La salida y la recepción son acciones separadas."
        ),
    }


@transaction.atomic
def crear_documento_interno(operation_id, actor, key):
    operation = _operation_locked(operation_id)
    existing = DistributionDispatch.objects.filter(operation_id=operation.pk).first()
    if existing:
        return operation, False
    if operation.status != DistributionOperation.Status.PREPARED:
        raise BusinessError("Primero reserva y confirma el conteo físico de esta entrega.")
    if not operation.source.is_active or not operation.destination.is_active:
        raise BusinessError("Origen y destino deben permanecer activos.")
    if (
        operation.mode == DistributionOperation.Mode.FAIR
        and not hasattr(operation.destination, "fair_event")
    ):
        raise BusinessError(
            "Esta entrega utiliza un almacén genérico de feria. "
            "Selecciona una feria específica mediante una revisión supervisada antes del despacho."
        )
    validar_feria_por_colegio(
        operation.destination, operation.school_id, operation_id=operation.pk,
    )
    reservations = list(operation.stock_reservations.filter(
        status=DistributionStockReservation.Status.ACTIVE,
    ).order_by("pk"))
    planned = defaultdict(int)
    for line in operation.items.all():
        planned[line.product_id] += line.quantity_planned
    counted = defaultdict(int)
    for row in reservations:
        if row.counted_quantity != row.quantity or row.counted_at is None:
            raise BusinessError("Debe constar el conteo conforme de todos los lotes.")
        counted[row.stock_entry.product_id] += row.quantity
    if not reservations or dict(planned) != dict(counted):
        raise BusinessError("Los lotes preparados no coinciden con la planificación.")

    dispatch = DistributionDispatch.objects.create(
        operation=operation, document_by=actor, idempotency_key=key,
        document_number=f"BE-SI-{key.hex.upper()}",
    )
    dispatch.document_number = f"BE-SI-{dispatch.pk:07d}"
    dispatch.save(update_fields=["document_number", "updated_at"])
    DistributionDispatchLine.objects.bulk_create([
        DistributionDispatchLine(
            dispatch=dispatch, reservation=row, quantity=row.quantity,
        )
        for row in reservations
    ])
    DistributionOperationEvent.objects.create(
        operation=operation, actor=actor, action="dispatch_document",
        current={"document_number": dispatch.document_number, "status": "documented"},
    )
    return operation, True


@transaction.atomic
def confirmar_salida(operation_id, actor, *, document_basis, guide_ref="", exemption="", note=""):
    operation = _operation_locked(operation_id)
    dispatch = get_object_or_404(
        DistributionDispatch.objects.select_for_update(), operation=operation,
    )
    if dispatch.status == DistributionDispatch.Status.IN_TRANSIT:
        return operation, False
    if dispatch.status != DistributionDispatch.Status.DOCUMENTED:
        raise BusinessError("La salida no puede confirmarse desde el estado actual.")
    if operation.status != DistributionOperation.Status.PREPARED:
        raise BusinessError("La entrega debe continuar preparada antes de su despacho.")
    if not operation.source.is_active or not operation.destination.is_active:
        raise BusinessError("El origen y el destino deben estar activos.")
    validar_feria_por_colegio(
        operation.destination, operation.school_id, operation_id=operation.pk,
    )

    # Declaración responsable: NO se consulta ni se confirma aceptación de SUNAT.
    if document_basis == DistributionDispatch.Evidence.EXTERNAL_GUIDE:
        guide_ref = guide_ref.strip().upper()
        if not GRE_REFERENCE_PATTERN.fullmatch(guide_ref) or int(guide_ref.split("-")[1]) == 0:
            raise BusinessError(
                "Indica una referencia de GRE con formato EG01-00000001. "
                "El formato no comprueba su existencia ni aceptación ante SUNAT."
            )
        exemption = ""
    elif document_basis == DistributionDispatch.Evidence.EXCEPTION:
        if not usuario_tiene_permiso(actor, "warehouse.validate_receiving"):
            raise BusinessError(
                "Solo Jefatura autorizada puede registrar una excepción legal revisada."
            )
        if len(exemption.strip()) < 60 or len(exemption.strip().split()) < 9:
            raise BusinessError(
                "Describe el supuesto legal aplicable y las evidencias revisadas "
                "(mínimo 60 caracteres y 9 palabras). No se admite texto de relleno."
            )
        guide_ref = ""
    else:
        raise BusinessError("Indica el sustento documental válido del traslado.")

    lines = list(dispatch.lines.select_related("reservation").order_by("reservation_id"))
    if not lines:
        raise BusinessError("No existe detalle físico del documento interno.")
    reservations = [line.reservation for line in lines]
    if any(
        row.status != DistributionStockReservation.Status.ACTIVE
        or row.quantity != line.quantity
        or row.counted_quantity != line.quantity
        or row.source_id != operation.source_id
        or row.operation_id != operation.pk
        for row, line in zip(reservations, lines)
    ):
        raise BusinessError("La preparación cambió. Revisa el estado de los lotes.")

    ids = sorted({row.stock_entry_id for row in reservations})
    entries = list(StockEntry.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if len(entries) != len(ids):
        raise BusinessError("Uno de los lotes ya no existe.")
    position = posiciones_lotes(entries)
    reserved_total = {
        row["stock_entry_id"]: row["total"] for row in
        DistributionStockReservation.objects.filter(
            stock_entry_id__in=ids, source_id=operation.source_id,
            status=DistributionStockReservation.Status.ACTIVE,
        ).values("stock_entry_id").annotate(total=Sum("quantity"))
    }
    for row in reservations:
        physical = position.get((row.stock_entry_id, operation.source_id), 0)
        if physical < reserved_total.get(row.stock_entry_id, 0):
            raise BusinessError(
                f"El lote {row.stock_entry_id} no cubre todas sus reservas. "
                "No se puede despachar hasta conciliar el stock real."
            )

    dispatch.evidence_kind = document_basis
    dispatch.external_guide_reference = guide_ref.strip()
    dispatch.exception_justification = exemption.strip()
    dispatch.notes = note.strip()
    dispatch.status = DistributionDispatch.Status.IN_TRANSIT
    dispatch.dispatched_by = actor
    dispatch.dispatched_at = timezone.now()
    dispatch.save(update_fields=[
        "evidence_kind", "external_guide_reference", "exception_justification",
        "notes", "status", "dispatched_by", "dispatched_at", "updated_at",
    ])
    DistributionStockReservation.objects.filter(
        pk__in=[row.pk for row in reservations],
        status=DistributionStockReservation.Status.ACTIVE,
    ).update(status=DistributionStockReservation.Status.RELEASED, updated_at=timezone.now())
    operation.status = DistributionOperation.Status.IN_TRANSIT
    operation.save(update_fields=["status", "updated_at"])
    DistributionOperationEvent.objects.create(
        operation=operation, actor=actor, action="dispatched",
        current={"document_number": dispatch.document_number, "status": operation.status},
    )
    return operation, True


@transaction.atomic
def confirmar_recepcion_destino(operation_id, actor, *, receiver, counts):
    receiver = validate_receiver_name(receiver)
    operation = _operation_locked(operation_id)
    dispatch = get_object_or_404(
        DistributionDispatch.objects.select_for_update(), operation=operation,
    )
    if dispatch.status != DistributionDispatch.Status.IN_TRANSIT:
        raise BusinessError("La entrega debe estar despachada y en tránsito.")
    if operation.status != DistributionOperation.Status.IN_TRANSIT:
        raise BusinessError("El estado de la entrega no coincide con el despacho.")
    if not operation.destination.is_active:
        raise BusinessError("El destino debe estar activo para confirmar la recepción.")
    expected, given = _validar_conteo_lineas(dispatch, counts)
    if any(given[key] != value for key, value in expected.items()):
        raise BusinessError(
            "Existe una diferencia en la recepción. No se registrará ingreso conforme "
            "hasta documentar y resolver la incidencia con Jefatura."
        )
    if dispatch.arrival_incidents.filter(
        status=DistributionArrivalIncident.Status.OPEN,
    ).exists():
        raise BusinessError(
            "Existe una incidencia de recepción abierta. Debe revisarse y "
            "cerrarse mediante recuento conforme supervisado antes de confirmar la llegada."
        )
    # Bloqueo compartido con movimientos directos y cortesías.
    lines = list(dispatch.lines.select_related("reservation__stock_entry").order_by("pk"))
    stock_ids = sorted(set(
        row.reservation.stock_entry_id for row in lines
    ))
    list(StockEntry.objects.select_for_update().filter(pk__in=stock_ids).order_by("pk"))
    dispatch.status = DistributionDispatch.Status.RECEIVED
    dispatch.received_by = actor
    dispatch.recipient_name = receiver
    dispatch.received_at = timezone.now()
    dispatch.save(update_fields=[
        "status", "received_by", "recipient_name", "received_at", "updated_at",
    ])
    operation.status = DistributionOperation.Status.DELIVERED
    operation.save(update_fields=["status", "updated_at"])
    DistributionOperationEvent.objects.create(
        operation=operation, actor=actor, action="received_destination",
        current={"document_number": dispatch.document_number, "status": operation.status,
                 "quantity": sum(expected.values()), "recipient": receiver},
    )
    return operation


def _validar_conteo_lineas(dispatch, counts):
    """Valida identidad y unicidad de líneas contra despacho (nunca otra entrega)."""
    lines = list(dispatch.lines.order_by("pk"))
    expected = {line.pk: line.quantity for line in lines}
    given = {item["line_id"]: item["counted"] for item in counts}
    if not expected or len(given) != len(counts) or set(given) != set(expected):
        raise BusinessError("Registra exactamente un conteo por lote de esta entrega.")
    # Defensa en profundidad: no depender únicamente del serializer HTTP.
    # El servicio también es invocable desde tareas y procesos internos.
    if any(type(value) is not int or value < 0 for value in given.values()):
        raise BusinessError("Las cantidades recibidas deben ser enteros no negativos.")
    return expected, given


@transaction.atomic
def reportar_diferencia_llegada(operation_id, actor, *, receiver, counts, observations):
    """Registra el desacuerdo físico sin mover stock ni alterar el estado en tránsito."""
    receiver = validate_receiver_name(receiver)
    operation = _operation_locked(operation_id)
    dispatch = get_object_or_404(
        DistributionDispatch.objects.select_for_update(), operation=operation,
    )
    if dispatch.status != DistributionDispatch.Status.IN_TRANSIT:
        raise BusinessError("Solo puedes registrar diferencias de una entrega en tránsito.")
    if operation.status != DistributionOperation.Status.IN_TRANSIT:
        raise BusinessError("El estado de la entrega no corresponde a un despacho en tránsito.")
    if dispatch.arrival_incidents.filter(status=DistributionArrivalIncident.Status.OPEN).exists():
        raise BusinessError("Ya existe una incidencia pendiente de revisión para esta entrega.")
    expected, given = _validar_conteo_lineas(dispatch, counts)
    if all(given[key] == value for key, value in expected.items()):
        raise BusinessError("El conteo coincide. Puedes confirmar la recepción normalmente.")
    if len(observations.strip()) < 10 or not receiver.strip():
        raise BusinessError("Identifica al receptor y explica la diferencia (mínimo 10 caracteres).")
    snapshot = [
        {
            "line_id": key,
            "expected": expected[key],
            "counted": given[key],
            "difference": given[key] - expected[key],
        }
        for key in sorted(expected)
    ]
    incident = DistributionArrivalIncident.objects.create(
        dispatch=dispatch, receiver_name=receiver,
        observations=observations.strip(), counts_snapshot=snapshot,
        reported_by=actor,
    )
    DistributionOperationEvent.objects.create(
        operation=operation, actor=actor, action="arrival_incident_opened",
        current={"incident_id": incident.pk, "document_number": dispatch.document_number,
                 "status": "open", "lines_with_difference": sum(
                     row["difference"] != 0 for row in snapshot)},
    )
    return operation, incident


@transaction.atomic
def documentar_diferencia_persistente(operation_id, actor, *, incident_id, breakdown, note):
    """Clasificación auditada B5.2, sin liquidar faltantes ni ingresar stock.

    Es una constatación de lo recibido físicamente. La regularización y
    recepción parcial requieren un movimiento específico posterior.
    """
    operation = _operation_locked(operation_id)
    dispatch = get_object_or_404(
        DistributionDispatch.objects.select_for_update(), operation=operation,
    )
    if (
        dispatch.status != DistributionDispatch.Status.IN_TRANSIT
        or operation.status != DistributionOperation.Status.IN_TRANSIT
    ):
        raise BusinessError("Solo se documentan diferencias de entregas en tránsito.")
    incident = get_object_or_404(
        DistributionArrivalIncident.objects.select_for_update(),
        pk=incident_id, dispatch=dispatch,
        status=DistributionArrivalIncident.Status.OPEN,
    )
    note = str(note or "").strip()
    if len(note) < 20:
        raise BusinessError("Explica la verificación física realizada (mínimo 20 caracteres).")
    if DistributionOperationEvent.objects.filter(
        operation=operation, action="arrival_diagnosed",
        current__incident_id=incident.pk,
    ).exists():
        raise BusinessError("La clasificación de esta incidencia ya fue documentada.")
    expected, observed = _validar_conteo_lineas(
        dispatch, [
            {"line_id": row["line_id"], "counted": row["conforming"] + row["damaged"] + row["extra"]}
            for row in breakdown
        ],
    )
    # Comprobar contra el conteo inicial, para no sustituir silenciosamente
    # las evidencias existentes por nuevas cantidades.
    snapshot = {row["line_id"]: row["counted"] for row in incident.counts_snapshot}
    if snapshot != observed:
        raise BusinessError(
            "El desglose no coincide con la incidencia registrada. "
            "Si hubo un nuevo conteo, debe conservarse una nueva evidencia auditada."
        )
    detail = []
    for row in sorted(breakdown, key=lambda item: item["line_id"]):
        line_id = row["line_id"]
        good, damaged, extra = row["conforming"], row["damaged"], row["extra"]
        if any(type(qty) is not int or qty < 0 for qty in (good, damaged, extra)):
            raise BusinessError("Solo se admiten cantidades enteras no negativas.")
        if good + damaged > expected[line_id]:
            raise BusinessError(
                "Las unidades conformes y dañadas no pueden superar lo despachado; "
                "registra los sobrantes por separado."
            )
        detail.append({
            "line_id": line_id, "dispatched": expected[line_id],
            "conforming": good, "damaged": damaged,
            "missing": expected[line_id] - good - damaged,
            "extra": extra,
        })
    event = DistributionOperationEvent.objects.create(
        operation=operation, actor=actor, action="arrival_diagnosed",
        reason=note[:500],
        current={"incident_id": incident.pk, "details": detail,
                 "document_number": dispatch.document_number},
    )
    return operation, event


@transaction.atomic
def resolver_diferencia_por_reconteo(
    operation_id, actor, *, incident_id, counts, resolution_note,
):
    """Solo jefatura: cierra incidencia si un recuento real es totalmente conforme.

    No confirma recepción ni altera los saldos. Incidencias con diferencias
    persistentes requieren el futuro flujo de resolución y recepción parcial.
    """
    operation = _operation_locked(operation_id)
    dispatch = get_object_or_404(
        DistributionDispatch.objects.select_for_update(), operation=operation,
    )
    if dispatch.status != DistributionDispatch.Status.IN_TRANSIT:
        raise BusinessError("La entrega debe continuar en tránsito.")
    incident = get_object_or_404(
        DistributionArrivalIncident.objects.select_for_update(),
        pk=incident_id, dispatch=dispatch,
    )
    if incident.status != DistributionArrivalIncident.Status.OPEN:
        raise BusinessError("La incidencia ya está resuelta; no puede cerrarse nuevamente.")
    expected, given = _validar_conteo_lineas(dispatch, counts)
    if any(given[key] != expected[key] for key in expected):
        raise BusinessError(
            "El recuento todavía tiene diferencias. No puede cerrarse como conforme; "
            "se necesita una resolución de faltantes o daños supervisada."
        )
    if len(resolution_note.strip()) < 15:
        raise BusinessError("Explica la verificación realizada (mínimo 15 caracteres).")
    incident.status = DistributionArrivalIncident.Status.RESOLVED
    incident.resolved_by = actor
    incident.resolution_note = resolution_note.strip()
    incident.recount_snapshot = [
        {"line_id": key, "expected": expected[key], "counted": given[key]}
        for key in sorted(expected)
    ]
    incident.resolved_at = timezone.now()
    incident.save(update_fields=[
        "status", "resolved_by", "resolution_note", "recount_snapshot",
        "resolved_at", "updated_at",
    ])
    DistributionOperationEvent.objects.create(
        operation=operation, actor=actor, action="arrival_incident_closed",
        current={"incident_id": incident.pk, "document_number": dispatch.document_number,
                 "status": "resolved", "resolution": "supervised_matching_recount"},
    )
    return operation, incident
