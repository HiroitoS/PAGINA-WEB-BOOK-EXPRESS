"""Planificación logística por adopción: punto de venta, feria o consignación.

Una operación de esta API nunca reserva ni mueve existencias. La entrega
física requerirá otro servicio con libro de movimientos y constancia.
"""
from decimal import Decimal

from django.core.paginator import EmptyPage, Paginator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from crm.models import Adoption
from warehouse.distribution_allocation import (
    allocation_summary, replace_operation_lines, validate_requested_allocation,
)
from warehouse.distribution_preparation import (
    confirmar_preparacion, dividir_entrega_por_disponibilidad,
    liberar_reservas_operacion, reservar_operacion, resumen_preparacion,
)
from warehouse.distribution_dispatch import (
    crear_documento_interno, confirmar_salida, confirmar_recepcion_destino,
    output_dispatch, reportar_diferencia_llegada, resolver_diferencia_por_reconteo,
)
from warehouse.fair_destination_policy import validar_feria_por_colegio
from warehouse.models import (
    DistributionDispatch, DistributionOperation, DistributionOperationEvent,
    DistributionOperationLine, DistributionTransportDraft, WarehouseLocation,
)


class AllocationItemInput(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=2_147_483_647)


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
    items = serializers.ListField(child=AllocationItemInput(), min_length=1)

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
        try:
            validar_feria_por_colegio(
                data["destination"], data["adoption"].school_id,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"destination_id": exc.messages}) from exc
        return data


class PreparedFairDestinationCorrection(serializers.Serializer):
    """Corrección restringida de destinos genéricos, sin tocar lotes ni conteos."""
    destination_id = serializers.PrimaryKeyRelatedField(
        source="destination", queryset=WarehouseLocation.objects.filter(
            is_active=True, kind=WarehouseLocation.Kind.FAIR,
        ),
    )
    reason = serializers.CharField(min_length=12, max_length=500, trim_whitespace=True)
    fair_verified_for_delivery = serializers.BooleanField()

    def validate_fair_verified_for_delivery(self, value):
        if value is not True:
            raise serializers.ValidationError(
                "Confirma que la feria corresponde a la entrega que estás corrigiendo."
            )
        return value


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
    items = serializers.ListField(
        child=AllocationItemInput(), min_length=1, required=False,
    )

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


class InternalDocumentInput(serializers.Serializer):
    idempotency_key = serializers.UUIDField()


class InternalDepartureInput(serializers.Serializer):
    evidence_kind = serializers.ChoiceField(choices=DistributionDispatch.Evidence.choices)
    external_guide_reference = serializers.CharField(
        max_length=120, required=False, allow_blank=True,
    )
    exception_justification = serializers.CharField(
        max_length=500, required=False, allow_blank=True,
    )
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    physical_dispatch_confirmed = serializers.BooleanField()

    def validate_physical_dispatch_confirmed(self, value):
        if value is not True:
            raise serializers.ValidationError(
                "Confirma la salida física solo cuando realmente vaya a efectuarse."
            )
        return value


class InternalReceptionLine(serializers.Serializer):
    line_id = serializers.IntegerField(min_value=1)
    counted = serializers.IntegerField(min_value=0)


class InternalReceptionInput(serializers.Serializer):
    receiver_name = serializers.CharField(max_length=180, trim_whitespace=True)
    counts = InternalReceptionLine(many=True, allow_empty=False)
    arrival_confirmed = serializers.BooleanField()

    def validate_arrival_confirmed(self, value):
        if value is not True:
            raise serializers.ValidationError("Confirma únicamente la llegada física real.")
        return value


class ArrivalIncidentInput(serializers.Serializer):
    receiver_name = serializers.CharField(max_length=180, trim_whitespace=True)
    counts = InternalReceptionLine(many=True, allow_empty=False)
    observations = serializers.CharField(min_length=10, max_length=1000, trim_whitespace=True)


class ArrivalIncidentResolutionInput(serializers.Serializer):
    incident_id = serializers.IntegerField(min_value=1)
    counts = InternalReceptionLine(many=True, allow_empty=False)
    resolution_note = serializers.CharField(min_length=15, max_length=1000, trim_whitespace=True)


class SplitByStockInput(serializers.Serializer):
    idempotency_key = serializers.UUIDField()


class ReserveLotInput(serializers.Serializer):
    stock_entry_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class ReserveInput(serializers.Serializer):
    # Ausente: reparto FIFO anterior. Presente: selección explícita de lotes.
    lots = ReserveLotInput(many=True, required=False, allow_empty=False)


class PhysicalCountInput(serializers.Serializer):
    reservation_id = serializers.IntegerField(min_value=1)
    counted = serializers.IntegerField(min_value=0)


class TransportDraftInput(serializers.Serializer):
    issuer_ruc = serializers.RegexField(
        regex=r"^$|^\d{11}$", required=False, allow_blank=True, max_length=11,
    )
    departure_address = serializers.CharField(required=False, allow_blank=True, max_length=300)
    destination_address = serializers.CharField(required=False, allow_blank=True, max_length=300)
    destination_id_number = serializers.CharField(required=False, allow_blank=True, max_length=20)
    destination_name = serializers.CharField(required=False, allow_blank=True, max_length=180)
    transport_mode = serializers.ChoiceField(
        required=False, allow_blank=True, choices=[("", "No definido"), *DistributionTransportDraft.Mode.choices],
    )
    transfer_reason = serializers.ChoiceField(
        required=False, allow_blank=True, choices=[("", "No definido"), *DistributionTransportDraft.Reason.choices],
    )
    departure_on = serializers.DateField(required=False, allow_null=True)
    license_plate = serializers.CharField(required=False, allow_blank=True, max_length=15)
    driver_document = serializers.CharField(required=False, allow_blank=True, max_length=20)
    driver_license = serializers.CharField(required=False, allow_blank=True, max_length=30)
    carrier_ruc = serializers.RegexField(
        regex=r"^$|^\d{11}$", required=False, allow_blank=True, max_length=11,
    )
    gross_weight_kg = serializers.DecimalField(
        required=False, allow_null=True, max_digits=12, decimal_places=3,
        min_value=Decimal("0.001"),
    )
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500)


TRANSPORT_FIELDS = tuple(TransportDraftInput().fields)


def _transport_output(operation):
    record = DistributionTransportDraft.objects.filter(operation=operation).first()
    values = {key: getattr(record, key) if record else None for key in TRANSPORT_FIELDS}
    if not record:
        values.update({
            key: "" for key in TRANSPORT_FIELDS
            if key not in ("departure_on", "gross_weight_kg")
        })
    # Prechequeo interno: SUNAT valida datos adicionales según el caso.
    mandatory = [
        "issuer_ruc", "departure_address", "destination_address",
        "destination_name", "destination_id_number", "transport_mode",
        "transfer_reason", "departure_on", "gross_weight_kg",
    ]
    if values["transport_mode"] == "private":
        mandatory.extend(["license_plate", "driver_document", "driver_license"])
    elif values["transport_mode"] == "public":
        mandatory.append("carrier_ruc")
    missing = [field for field in mandatory if not values[field]]
    return {
        "operation_id": operation.pk,
        "draft": values,
        "missing_fields": missing,
        "data_complete_for_review": not missing,
        "sunat_issued": False,
        "sunat_accepted": False,
        "notice": (
            "Datos preparatorios únicamente. Esto NO es una GRE, no consulta SUNAT "
            "ni autoriza el transporte. La GRE y su CDR aceptada deben verificarse "
            "antes del inicio del traslado, cuando corresponda."
        ),
    }


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
        "items": [
            {"product_id": row.product_id, "quantity": row.quantity_planned}
            for row in obj.items.all()
        ],
    }


def _output(obj):
    return {
        "id": obj.pk,
        "reference": str(obj.reference),
        "adoption_id": obj.adoption_id,
        "school_id": obj.school_id,
        "school": obj.school.name,
        "campaign": obj.adoption.campaign_name_snapshot,
        "campaign_year": obj.adoption.campaign.year,
        "original_mode": obj.original_mode,
        "mode": obj.mode,
        "source_id": obj.source_id,
        "source": obj.source.name,
        "source_kind": obj.source.kind,
        "destination_id": obj.destination_id,
        "destination": obj.destination.name,
        "destination_kind": obj.destination.kind,
        "destination_fair_event_id": (
            obj.destination.fair_event.pk
            if getattr(obj.destination, "fair_event", None) else None
        ),
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
        "adoption__campaign", "school", "source", "destination",
        "destination__fair_event", "created_by",
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
            states = state.split(",")
            if len(states) > 3 or any(
                not code or code not in DistributionOperation.Status.values
                for code in states
            ):
                raise ValidationError({"estado": "Selecciona estados válidos."})
            qs = qs.filter(status__in=states)
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
        """Buscar cualquier adopción vigente por colegio o campaña, sin límite oculto."""
        self._authorize(request)
        search = request.query_params.get("buscar", "").strip()
        year = request.query_params.get("anio", "").strip()
        raw_page = request.query_params.get("page", "1").strip()
        if len(search) > 100:
            raise ValidationError({"buscar": "Busca por un nombre de hasta 100 caracteres."})
        if year and (len(year) != 4 or not year.isdecimal() or int(year) < 2000):
            raise ValidationError({"anio": "Indica un año de campaña válido."})
        if not raw_page.isdecimal() or int(raw_page) < 1:
            raise ValidationError({"page": "Selecciona una página válida."})

        current_adoptions = Adoption.objects.filter(is_current=True)
        years = list(
            current_adoptions.order_by()
            .values_list("campaign__year", flat=True)
            .distinct()
            .order_by("-campaign__year")
        )
        adoptions = current_adoptions.select_related(
            "school", "campaign",
        ).prefetch_related("items").order_by("-confirmed_at", "-pk")
        if search:
            query = (
                Q(school_name_snapshot__icontains=search)
                | Q(school__name__icontains=search)
                | Q(campaign_name_snapshot__icontains=search)
            )
            if search.isdecimal() and len(search) <= 18:
                query |= Q(pk=int(search))
            adoptions = adoptions.filter(query)
        if year:
            adoptions = adoptions.filter(campaign__year=int(year))
        pages = Paginator(adoptions, 20)
        try:
            selected = pages.page(int(raw_page))
        except EmptyPage:
            raise ValidationError({"page": "No existen adopciones en esa página."})
        locations = list(WarehouseLocation.objects.filter(is_active=True).select_related(
            "fair_event",
        ).order_by("name"))
        active_fair_ids = [
            loc.pk for loc in locations
            if loc.kind == WarehouseLocation.Kind.FAIR
            and getattr(loc, "fair_event", None) is not None
        ]
        assigned_school_ids = {loc_id: set() for loc_id in active_fair_ids}
        for location_id, school_id in DistributionOperation.objects.filter(
            destination_id__in=active_fair_ids,
        ).exclude(status=DistributionOperation.Status.CANCELLED).values_list(
            "destination_id", "school_id",
        ).distinct():
            assigned_school_ids[location_id].add(school_id)
        return Response({
            "adoptions": [
                {
                    "id": record.pk,
                    "school": record.school_name_snapshot,
                    "campaign": record.campaign_name_snapshot,
                    "campaign_year": record.campaign.year,
                    "sale_mode": record.sale_mode,
                    "items": [
                        {"product": item.product_name_snapshot, "quantity": item.quantity}
                        for item in record.items.all()
                    ],
                }
                for record in selected
            ],
            "adoptions_meta": {
                "count": pages.count,
                "page": selected.number,
                "pages": pages.num_pages,
            },
            "campaign_years": years,
            "locations": [
                {
                    "id": loc.pk, "name": loc.name, "kind": loc.kind,
                    "fair_event_id": (
                        loc.fair_event.pk if getattr(loc, "fair_event", None) else None
                    ),
                    "assigned_school_ids": sorted(assigned_school_ids.get(loc.pk, [])),
                    "fair_event_name": (
                        loc.fair_event.name if getattr(loc, "fair_event", None) else None
                    ),
                    "fair_venue": (
                        loc.fair_event.venue_name if getattr(loc, "fair_event", None) else None
                    ),
                    "fair_starts_on": (
                        loc.fair_event.starts_on if getattr(loc, "fair_event", None) else None
                    ),
                }
                for loc in locations
            ],
            "modes": [
                {"value": mode, "label": label}
                for mode, label in DistributionOperation.Mode.choices
            ],
        })

    @action(detail=False, methods=["get"], url_path="asignacion")
    def allocation(self, request):
        """Presupuesto de adopción para un alta o edición, sin consulta de stock."""
        self._authorize(request)
        raw_adoption = request.query_params.get("adoption_id", "").strip()
        raw_operation = request.query_params.get("operation_id", "").strip()
        if not raw_adoption.isdecimal() or int(raw_adoption) < 1:
            raise ValidationError({"adoption_id": "Selecciona una adopción válida."})
        if raw_operation and (
            not raw_operation.isdecimal() or int(raw_operation) < 1
        ):
            raise ValidationError({"operation_id": "Selecciona una entrega válida."})
        adoption = get_object_or_404(Adoption, pk=int(raw_adoption))
        operation = None
        if raw_operation:
            operation = get_object_or_404(
                DistributionOperation, pk=int(raw_operation),
                adoption_id=adoption.pk,
            )
        elif not adoption.is_current:
            raise ValidationError({
                "adoption_id": "Selecciona la versión vigente de la adopción.",
            })
        return Response(allocation_summary(adoption, operation))

    def create(self, request):
        self._authorize(request, write=True)
        form = OperationInput(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        with transaction.atomic():
            # Bloquear la misma adopción serializa todos sus planes simultáneos.
            adoption = Adoption.objects.select_for_update().get(
                pk=data["adoption"].pk,
            )
            if not adoption.is_current:
                raise ValidationError({
                    "adoption_id": "Esta adopción cambió de versión; actualiza la lista.",
                })
            old = DistributionOperation.objects.filter(
                idempotency_key=data["idempotency_key"],
            ).first()
            if old:
                existing = {
                    row.product_id: row.quantity_planned for row in old.items.all()
                }
                received = {
                    item["product_id"]: item["quantity"] for item in data["items"]
                }
                if (
                    old.adoption_id != adoption.pk or old.mode != data["mode"]
                    or old.source_id != data["source"].pk
                    or old.destination_id != data["destination"].pk
                    or old.operation_name != data["operation_name"]
                    or old.responsible_name != data["responsible_name"]
                    or old.scheduled_on != data.get("scheduled_on")
                    or old.scheduled_until != data.get("scheduled_until")
                    or old.notes != data.get("notes", "")
                    or len(received) != len(data["items"])
                    or received != existing
                ):
                    raise ValidationError({
                        "detail": "Esta operación ya se registró con otros datos. Actualiza la lista.",
                    })
                return Response(_output(get_object_or_404(_queryset(), pk=old.pk)))

            planned = validate_requested_allocation(adoption, data["items"])
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
            replace_operation_lines(record, planned)
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
        requested_items = values.pop("items", None)
        with transaction.atomic():
            # El orden de bloqueo debe coincidir con crear/anular.
            adoption_id = get_object_or_404(
                DistributionOperation.objects.only("adoption_id"), pk=pk,
            ).adoption_id
            adoption = Adoption.objects.select_for_update().get(pk=adoption_id)
            record = get_object_or_404(
                DistributionOperation.objects.select_for_update(), pk=pk,
            )
            if record.status != DistributionOperation.Status.PLANNED:
                raise ValidationError({
                    "detail": "La entrega ya inició su preparación o fue anulada. No se puede editar.",
                })
            previous = _state(record)
            planned = (
                validate_requested_allocation(
                    adoption, requested_items, operation=record,
                )
                if requested_items is not None else None
            )
            for field, value in values.items():
                setattr(record, field, value)
            if record.source_id == record.destination_id:
                raise ValidationError({
                    "destination_id": "El origen y destino deben ser diferentes.",
                })
            try:
                validar_feria_por_colegio(
                    record.destination, record.school_id, operation_id=record.pk,
                )
            except DjangoValidationError as exc:
                raise ValidationError({"destination_id": exc.messages}) from exc
            if (
                record.scheduled_on and record.scheduled_until
                and record.scheduled_until < record.scheduled_on
            ):
                raise ValidationError({
                    "scheduled_until": "La fecha final no puede ser anterior a la inicial.",
                })
            new_items = (
                [
                    {"product_id": product_id, "quantity": detail["quantity"]}
                    for product_id, detail in planned.items()
                ]
                if planned is not None else previous["items"]
            )
            old_items = sorted(
                previous["items"], key=lambda row: row["product_id"],
            )
            if planned is not None and sorted(
                new_items, key=lambda row: row["product_id"],
            ) != old_items:
                replace_operation_lines(record, planned)
            changed = _state(record) != previous
            if not changed:
                raise ValidationError({"detail": "No se detectaron cambios para guardar."})
            record.save()
            DistributionOperationEvent.objects.create(
                operation=record, actor=request.user, action="updated",
                reason=reason, previous=previous, current=_state(record),
            )
        return Response(_output(get_object_or_404(_queryset(), pk=record.pk)))

    @action(detail=True, methods=["post"], url_path="corregir-destino-feria")
    def correct_prepared_fair_destination(self, request, pk=None):
        """Solo Jefatura corrige feria genérica de una preparación sin orden emitida."""
        self._authorize(request, write=True)
        if not usuario_tiene_permiso(request.user, "warehouse.validate_receiving"):
            raise PermissionDenied("La corrección del destino preparado requiere autorización de Jefatura.")
        form = PreparedFairDestinationCorrection(data=request.data)
        form.is_valid(raise_exception=True)
        target = form.validated_data["destination"]
        reason = form.validated_data["reason"]
        with transaction.atomic():
            record = get_object_or_404(
                DistributionOperation.objects.select_for_update(of=("self",)).select_related(
                    "destination",
                ),
                pk=pk,
            )
            if record.status != DistributionOperation.Status.PREPARED:
                raise ValidationError({
                    "detail": "Solo puedes corregir el destino de una preparación ya verificada."
                })
            if record.mode != DistributionOperation.Mode.FAIR:
                raise ValidationError({"detail": "Esta corrección solo corresponde a ferias."})
            if record.destination.kind != WarehouseLocation.Kind.FAIR or (
                getattr(record.destination, "fair_event", None) is not None
            ):
                raise ValidationError({
                    "detail": "El destino actual no es una feria genérica pendiente de asignación."
                })
            if DistributionDispatch.objects.filter(operation=record).exists():
                raise ValidationError({
                    "detail": "Ya existe una orden interna. Requiere una reversión formal, no edición."
                })
            if target.pk in (record.source_id, record.destination_id):
                raise ValidationError({
                    "destination_id": "Elige una feria específica diferente del lugar actual."
                })
            if not hasattr(target, "fair_event"):
                raise ValidationError({
                    "destination_id": "Selecciona una feria registrada como evento, no un almacén genérico."
                })
            try:
                validar_feria_por_colegio(
                    target, record.school_id, operation_id=record.pk,
                )
            except DjangoValidationError as exc:
                raise ValidationError({"destination_id": exc.messages}) from exc
            previous = _state(record)
            record.destination = target
            record.save(update_fields=["destination", "updated_at"])
            DistributionOperationEvent.objects.create(
                operation=record, actor=request.user,
                action="fair_destination_fixed", reason=reason,
                previous=previous,
                current={**_state(record), "fair_verified_for_delivery": True},
            )
        return Response(_output(get_object_or_404(_queryset(), pk=record.pk)))

    @action(detail=True, methods=["get"], url_path="preparacion")
    def preparation(self, request, pk=None):
        self._authorize(request)
        operation = get_object_or_404(_queryset(), pk=pk)
        return Response(resumen_preparacion(operation))

    @action(detail=True, methods=["post"], url_path="reservar")
    def reserve(self, request, pk=None):
        self._authorize(request, write=True)
        form = ReserveInput(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            operation, created = reservar_operacion(
                pk, request.user, lots=form.validated_data.get("lots"),
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response(resumen_preparacion(operation), status=(
            status.HTTP_201_CREATED if created else status.HTTP_200_OK
        ))

    @action(detail=True, methods=["post"], url_path="separar-disponibles")
    def split_available(self, request, pk=None):
        """Una entrega disponible ahora, otra pendiente; ninguna salida física."""
        self._authorize(request, write=True)
        form = SplitByStockInput(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            operation, pending, created = dividir_entrega_por_disponibilidad(
                pk, request.user, form.validated_data["idempotency_key"],
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response({
            "reserved": resumen_preparacion(operation),
            "pending_operation_id": pending.pk,
            "pending": [
                {
                    "product_id": row.product_id,
                    "product": row.product_name_snapshot,
                    "quantity": row.quantity_planned,
                }
                for row in pending.items.all()
            ],
            "created": created,
            "notice": (
                "Se reservó únicamente el stock conforme disponible. "
                "El saldo quedó planificado para otra entrega. "
                "No se despacharon ni trasladaron libros."
            ),
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="confirmar-preparacion")
    def confirm_preparation(self, request, pk=None):
        self._authorize(request, write=True)
        form = serializers.ListSerializer(
            child=PhysicalCountInput(), allow_empty=False,
            data=request.data.get("counts"),
        )
        form.is_valid(raise_exception=True)
        try:
            operation = confirmar_preparacion(pk, request.user, form.validated_data)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response(resumen_preparacion(operation))

    @action(detail=True, methods=["get", "post"], url_path="documento-interno")
    def internal_document(self, request, pk=None):
        """Orden interna numerada: NO registra salida ni emisión SUNAT."""
        self._authorize(request, write=request.method == "POST")
        if request.method == "GET":
            operation = get_object_or_404(_queryset(), pk=pk)
            return Response(output_dispatch(operation))
        form = InternalDocumentInput(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            operation, created = crear_documento_interno(
                pk, request.user, form.validated_data["idempotency_key"],
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response(
            output_dispatch(operation),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="confirmar-salida")
    def internal_departure(self, request, pk=None):
        """Salida física separada; exige sustento documental verificado por humano."""
        self._authorize(request, write=True)
        if not usuario_tiene_permiso(request.user, "warehouse.manage_stock_transfers"):
            raise PermissionDenied("No tienes autorización para confirmar salidas físicas.")
        form = InternalDepartureInput(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        try:
            operation, created = confirmar_salida(
                pk, request.user, document_basis=data["evidence_kind"],
                guide_ref=data.get("external_guide_reference", ""),
                exemption=data.get("exception_justification", ""),
                note=data.get("notes", ""),
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response(
            output_dispatch(operation),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="confirmar-llegada")
    def internal_arrival(self, request, pk=None):
        """Entrada de destino luego de cotejar todos los lotes, nunca implícita."""
        self._authorize(request, write=True)
        if not usuario_tiene_permiso(request.user, "warehouse.manage_stock_transfers"):
            raise PermissionDenied("No tienes autorización para confirmar recepciones físicas.")
        form = InternalReceptionInput(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            operation = confirmar_recepcion_destino(
                pk, request.user,
                receiver=form.validated_data["receiver_name"],
                counts=form.validated_data["counts"],
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response(output_dispatch(operation))

    @action(detail=True, methods=["post"], url_path="registrar-diferencia-llegada")
    def register_arrival_incident(self, request, pk=None):
        """Registra incidencia sin sumar stock a destino ni cerrar tránsito."""
        self._authorize(request, write=True)
        if not usuario_tiene_permiso(request.user, "warehouse.manage_stock_transfers"):
            raise PermissionDenied("No tienes autorización para registrar diferencias de llegada.")
        form = ArrivalIncidentInput(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        try:
            operation, incident = reportar_diferencia_llegada(
                pk, request.user, receiver=data["receiver_name"],
                counts=data["counts"], observations=data["observations"],
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        response = output_dispatch(operation)
        response["created_incident_id"] = incident.pk
        return Response(response, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="resolver-diferencia-llegada")
    def resolve_arrival_incident(self, request, pk=None):
        """Solo jefatura, únicamente tras nuevo conteo físico conforme completo."""
        self._authorize(request, write=True)
        if not usuario_tiene_permiso(request.user, "warehouse.validate_receiving"):
            raise PermissionDenied("Solo la jefatura autorizada puede resolver esta incidencia.")
        form = ArrivalIncidentResolutionInput(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        try:
            operation, incident = resolver_diferencia_por_reconteo(
                pk, request.user, incident_id=data["incident_id"],
                counts=data["counts"], resolution_note=data["resolution_note"],
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        response = output_dispatch(operation)
        response["resolved_incident_id"] = incident.pk
        return Response(response)

    @action(detail=True, methods=["get", "put"], url_path="documento-traslado")
    def transport_document(self, request, pk=None):
        self._authorize(request, write=request.method == "PUT")
        if request.method == "GET":
            return Response(_transport_output(get_object_or_404(_queryset(), pk=pk)))
        form = TransportDraftInput(data=request.data)
        form.is_valid(raise_exception=True)
        with transaction.atomic():
            operation = get_object_or_404(
                DistributionOperation.objects.select_for_update(), pk=pk,
            )
            if operation.status in (
                DistributionOperation.Status.CANCELLED,
                DistributionOperation.Status.IN_TRANSIT,
                DistributionOperation.Status.DELIVERED,
            ):
                raise ValidationError({
                    "detail": "Una entrega anulada o despachada conserva su documentación histórica.",
                })
            draft, _ = DistributionTransportDraft.objects.get_or_create(
                operation=operation,
                defaults={"updated_by": request.user},
            )
            changes = []
            for field, value in form.validated_data.items():
                if getattr(draft, field) != value:
                    setattr(draft, field, value)
                    changes.append(field)
            if changes:
                draft.updated_by = request.user
                draft.save(update_fields=[*changes, "updated_by", "updated_at"])
                DistributionOperationEvent.objects.create(
                    operation=operation, actor=request.user,
                    action="transport_draft_updated",
                    current={"updated_fields": changes, "sunat_issued": False},
                )
        return Response(_transport_output(operation))

    @action(detail=True, methods=["post"], url_path="anular")
    def cancel(self, request, pk=None):
        self._authorize(request, write=True)
        note = request.data.get("reason", "")
        if not isinstance(note, str) or not 8 <= len(note.strip()) <= 500:
            raise ValidationError({
                "reason": "Indica el motivo de la anulación (mínimo ocho caracteres).",
            })
        with transaction.atomic():
            adoption_id = get_object_or_404(
                DistributionOperation.objects.only("adoption_id"), pk=pk,
            ).adoption_id
            Adoption.objects.select_for_update().get(pk=adoption_id)
            record = get_object_or_404(
                DistributionOperation.objects.select_for_update(), pk=pk,
            )
            if record.status == DistributionOperation.Status.CANCELLED:
                raise ValidationError({"detail": "Esta operación ya fue anulada."})
            if record.status not in (
                DistributionOperation.Status.PLANNED,
                DistributionOperation.Status.RESERVED,
            ):
                raise ValidationError({
                    "detail": (
                        "No se puede anular una entrega preparada, despachada o "
                        "recibida. Requiere un procedimiento de devolución "
                        "o reversión autorizado y auditable."
                    ),
                })
            previous = _state(record)
            liberar_reservas_operacion(record)
            record.status = DistributionOperation.Status.CANCELLED
            record.save(update_fields=["status", "updated_at"])
            DistributionOperationEvent.objects.create(
                operation=record, actor=request.user, action="cancelled",
                reason=note.strip(), previous=previous, current=_state(record),
            )
        return Response(_output(get_object_or_404(_queryset(), pk=pk)))
