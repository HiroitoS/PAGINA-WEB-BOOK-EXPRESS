"""Planificación logística por adopción: punto de venta, feria o consignación.

Una operación de esta API nunca reserva ni mueve existencias. La entrega
física requerirá otro servicio con libro de movimientos y constancia.
"""
from collections import defaultdict

from django.core.paginator import EmptyPage, Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from crm.models import Adoption
from warehouse.models import (
    DistributionOperation, DistributionOperationEvent, DistributionOperationLine,
    WarehouseLocation,
)


class OperationInput(serializers.Serializer):
    idempotency_key = serializers.UUIDField()
    adoption_id = serializers.PrimaryKeyRelatedField(
        source="adoption", queryset=Adoption.objects.filter(is_current=True),
    )
    mode = serializers.ChoiceField(choices=DistributionOperation.Mode.choices)
    source_id = serializers.PrimaryKeyRelatedField(
        source="source", queryset=WarehouseLocation.objects.filter(is_active=True),
    )
    destination_id = serializers.PrimaryKeyRelatedField(
        source="destination", queryset=WarehouseLocation.objects.filter(is_active=True),
    )
    operation_name = serializers.CharField(max_length=180, trim_whitespace=True)
    responsible_name = serializers.CharField(max_length=180, trim_whitespace=True)
    scheduled_on = serializers.DateField(required=False, allow_null=True)
    scheduled_until = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, data):
        if data["source"] == data["destination"]:
            raise serializers.ValidationError({
                "destination_id": "El origen y destino deben ser diferentes.",
            })
        if (
            data.get("scheduled_on") and data.get("scheduled_until")
            and data["scheduled_until"] < data["scheduled_on"]
        ):
            raise serializers.ValidationError({
                "scheduled_until": "La fecha final no puede ser anterior a la inicial.",
            })
        if not data["operation_name"].strip() or not data["responsible_name"].strip():
            raise serializers.ValidationError({
                "detail": "Indica un nombre para la operación y quién es responsable.",
            })
        return data


class OperationUpdate(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=DistributionOperation.Mode.choices, required=False,
    )
    destination_id = serializers.PrimaryKeyRelatedField(
        source="destination", queryset=WarehouseLocation.objects.filter(is_active=True),
        required=False,
    )
    source_id = serializers.PrimaryKeyRelatedField(
        source="source", queryset=WarehouseLocation.objects.filter(is_active=True),
        required=False,
    )
    operation_name = serializers.CharField(max_length=180, required=False)
    responsible_name = serializers.CharField(max_length=180, required=False)
    scheduled_on = serializers.DateField(required=False, allow_null=True)
    scheduled_until = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    reason = serializers.CharField(min_length=8, max_length=500)

    def validate(self, data):
        if not any(key != "reason" for key in data):
            raise serializers.ValidationError({
                "detail": "Indica qué dato de la planificación deseas modificar.",
            })
        if not data["reason"].strip():
            raise serializers.ValidationError({"reason": "Explica el motivo del cambio."})
        for field in ("operation_name", "responsible_name"):
            if field in data and not data[field].strip():
                raise serializers.ValidationError({
                    field: "Este dato no puede quedar vacío.",
                })
        return data


def _state(obj):
    return {
        "mode": obj.mode,
        "source_id": obj.source_id,
        "destination_id": obj.destination_id,
        "operation_name": obj.operation_name,
        "responsible_name": obj.responsible_name,
        "scheduled_on": obj.scheduled_on.isoformat() if obj.scheduled_on else None,
        "scheduled_until": obj.scheduled_until.isoformat() if obj.scheduled_until else None,
        "notes": obj.notes,
        "status": obj.status,
    }


def _output(obj):
    return {
        "id": obj.pk,
        "reference": str(obj.reference),
        "adoption_id": obj.adoption_id,
        "school_id": obj.school_id,
        "school": obj.school.name,
        "original_mode": obj.original_mode,
        "mode": obj.mode,
        "source_id": obj.source_id,
        "source": obj.source.name,
        "destination_id": obj.destination_id,
        "destination": obj.destination.name,
        "operation_name": obj.operation_name,
        "responsible_name": obj.responsible_name,
        "scheduled_on": obj.scheduled_on,
        "scheduled_until": obj.scheduled_until,
        "notes": obj.notes,
        "status": obj.status,
        "created_at": obj.created_at,
        "items": [
            {
                "product_id": line.product_id,
                "product": line.product_name_snapshot,
                "quantity_planned": line.quantity_planned,
            }
            for line in obj.items.all()
        ],
        "events": [
            {
                "action": event.action, "reason": event.reason,
                "actor": event.actor.get_full_name().strip() or event.actor.get_username(),
                "created_at": event.created_at,
                "previous": event.previous, "current": event.current,
            }
            for event in obj.events.all()
        ],
        "notice": "Planificación: todavía no reserva libros, no registra ventas y no confirma una entrega.",
    }


def _queryset():
    return DistributionOperation.objects.select_related(
        "adoption", "school", "source", "destination", "created_by",
    ).prefetch_related("items", "events__actor")


class DistributionOperationViewSet(viewsets.ViewSet):
    """Operaciones planificadas con cambios auditables de las tres modalidades."""

    def _authorize(self, request, write=False):
        code = (
            "warehouse.manage_distribution_operations" if write
            else "warehouse.view_distribution_operations"
        )
        if not usuario_tiene_permiso(request.user, code):
            raise PermissionDenied("No tienes autorización para esta operación.")

    def list(self, request):
        self._authorize(request)
        qs = _queryset()
        state = request.query_params.get("estado", "").strip()
        if state:
            if state not in DistributionOperation.Status.values:
                raise ValidationError({"estado": "Selecciona un estado válido."})
            qs = qs.filter(status=state)
        raw_page = request.query_params.get("page", "1")
        if not raw_page.isdecimal() or int(raw_page) < 1:
            raise ValidationError({"page": "Selecciona una página válida."})
        pages = Paginator(qs, 20)
        try:
            page = pages.page(int(raw_page))
        except EmptyPage:
            raise ValidationError({"page": "No existen operaciones en esa página."})
        return Response({
            "count": pages.count, "page": page.number, "pages": pages.num_pages,
            "results": [_output(record) for record in page],
        })

    def retrieve(self, request, pk=None):
        self._authorize(request)
        return Response(_output(get_object_or_404(_queryset(), pk=pk)))

    @action(detail=False, methods=["get"], url_path="opciones")
    def options(self, request):
        self._authorize(request)
        # Solo adopciones confirmadas y vigentes, sin exponer precios internos.
        adoptions = Adoption.objects.filter(is_current=True).select_related(
            "school",
        ).prefetch_related("items").order_by("-confirmed_at", "-pk")[:100]
        locations = WarehouseLocation.objects.filter(is_active=True).order_by("name")
        return Response({
            "adoptions": [
                {
                    "id": record.pk,
                    "school": record.school_name_snapshot,
                    "campaign": record.campaign_name_snapshot,
                    "sale_mode": record.sale_mode,
                    "items": [
                        {"product": item.product_name_snapshot, "quantity": item.quantity}
                        for item in record.items.all()
                    ],
                }
                for record in adoptions
            ],
            "locations": [
                {"id": loc.pk, "name": loc.name, "kind": loc.kind}
                for loc in locations
            ],
            "modes": [
                {"value": mode, "label": label}
                for mode, label in DistributionOperation.Mode.choices
            ],
        })

    def create(self, request):
        self._authorize(request, write=True)
        form = OperationInput(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        with transaction.atomic():
            old = DistributionOperation.objects.filter(
                idempotency_key=data["idempotency_key"],
            ).first()
            if old:
                if (
                    old.adoption_id != data["adoption"].pk or old.mode != data["mode"]
                    or old.source_id != data["source"].pk
                    or old.destination_id != data["destination"].pk
                    or old.operation_name != data["operation_name"]
                    or old.responsible_name != data["responsible_name"]
                    or old.scheduled_on != data.get("scheduled_on")
                    or old.scheduled_until != data.get("scheduled_until")
                    or old.notes != data.get("notes", "")
                ):
                    raise ValidationError({
                        "detail": "Esta operación ya se registró con otros datos. Actualiza la lista.",
                    })
                return Response(_output(get_object_or_404(_queryset(), pk=old.pk)))

            adoption = data["adoption"]
            quantities = defaultdict(int)
            names = {}
            for item in adoption.items.all():
                quantities[item.product_id] += item.quantity
                names[item.product_id] = item.product_name_snapshot
            if not quantities:
                raise ValidationError({
                    "adoption_id": "Esta adopción no tiene libros para preparar.",
                })
            record = DistributionOperation.objects.create(
                idempotency_key=data["idempotency_key"],
                adoption=adoption, school=adoption.school,
                original_mode=adoption.sale_mode or "",
                mode=data["mode"], source=data["source"],
                destination=data["destination"],
                operation_name=data["operation_name"],
                responsible_name=data["responsible_name"],
                scheduled_on=data.get("scheduled_on"),
                scheduled_until=data.get("scheduled_until"),
                notes=data.get("notes", ""), created_by=request.user,
            )
            DistributionOperationLine.objects.bulk_create([
                DistributionOperationLine(
                    operation=record, product_id=product_id,
                    product_name_snapshot=names[product_id],
                    quantity_planned=quantity,
                )
                for product_id, quantity in quantities.items()
            ])
            DistributionOperationEvent.objects.create(
                operation=record, actor=request.user,
                action="created", current=_state(record),
            )
        return Response(
            _output(get_object_or_404(_queryset(), pk=record.pk)),
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, pk=None):
        self._authorize(request, write=True)
        form = OperationUpdate(data=request.data)
        form.is_valid(raise_exception=True)
        values = dict(form.validated_data)
        reason = values.pop("reason")
        with transaction.atomic():
            record = get_object_or_404(
                DistributionOperation.objects.select_for_update(), pk=pk,
            )
            if record.status != DistributionOperation.Status.PLANNED:
                raise ValidationError({
                    "detail": "Esta operación ya fue anulada. No puedes modificarla.",
                })
            prev = _state(record)
            for field, value in values.items():
                setattr(record, field, value)
            if record.source_id == record.destination_id:
                raise ValidationError({
                    "destination_id": "El origen y destino deben ser diferentes.",
                })
            if (
                record.scheduled_on and record.scheduled_until
                and record.scheduled_until < record.scheduled_on
            ):
                raise ValidationError({
                    "scheduled_until": "La fecha final no puede ser anterior a la inicial.",
                })
            changed = _state(record) != prev
            if not changed:
                raise ValidationError({"detail": "No se detectaron cambios para guardar."})
            record.save()
            DistributionOperationEvent.objects.create(
                operation=record, actor=request.user, action="updated",
                reason=reason, previous=prev, current=_state(record),
            )
        return Response(_output(get_object_or_404(_queryset(), pk=record.pk)))

    @action(detail=True, methods=["post"], url_path="anular")
    def cancel(self, request, pk=None):
        self._authorize(request, write=True)
        note = request.data.get("reason", "")
        if not isinstance(note, str) or not 8 <= len(note.strip()) <= 500:
            raise ValidationError({
                "reason": "Indica el motivo de la anulación (mínimo ocho caracteres).",
            })
        with transaction.atomic():
            record = get_object_or_404(
                DistributionOperation.objects.select_for_update(), pk=pk,
            )
            if record.status != DistributionOperation.Status.PLANNED:
                raise ValidationError({"detail": "Esta operación ya fue anulada."})
            previous = _state(record)
            record.status = DistributionOperation.Status.CANCELLED
            record.save(update_fields=["status", "updated_at"])
            DistributionOperationEvent.objects.create(
                operation=record, actor=request.user, action="cancelled",
                reason=note.strip(), previous=previous, current=_state(record),
            )
        return Response(_output(get_object_or_404(_queryset(), pk=pk)))
