"""B3.2: registro de ferias concretas y su ubicación de custodia interna.

No mueve mercadería, no crea existencias, no emite guías ni determina SUNAT.
"""
from django.db import IntegrityError, transaction
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from warehouse.api_locations import (
    WarehouseLocationAccess, WarehouseLocationSerializer,
)
from warehouse.models import WarehouseFairEvent, WarehouseLocation


class FairEventInput(serializers.Serializer):
    idempotency_key = serializers.UUIDField()
    name = serializers.CharField(max_length=150, trim_whitespace=True)
    venue_name = serializers.CharField(max_length=180, trim_whitespace=True)
    venue_address = serializers.CharField(max_length=255, trim_whitespace=True)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    responsible_name = serializers.CharField(max_length=180, trim_whitespace=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["ends_on"] < attrs["starts_on"]:
            raise serializers.ValidationError({
                "ends_on": "La fecha final debe ser igual o posterior a la inicial.",
            })
        return attrs


def fair_output(event):
    return {
        "id": event.pk,
        "reference": str(event.reference),
        "name": event.name,
        "venue_name": event.venue_name,
        "venue_address": event.venue_address,
        "starts_on": event.starts_on,
        "ends_on": event.ends_on,
        "responsible_name": event.responsible_name,
        "notes": event.notes,
        "location_id": event.location_id,
        "location_name": event.location.name,
        "location_code": event.location.code,
        "is_active": event.location.is_active,
        "created_at": event.created_at,
        "notice": (
            "Feria registrada con ubicación propia. Aún no tiene mercadería "
            "asignada ni se ha efectuado un traslado."
        ),
    }


def _payload_equals(event, data):
    return all(
        getattr(event, key) == value
        for key, value in data.items()
        if key != "idempotency_key"
    ) and str(event.idempotency_key) == str(data["idempotency_key"])


class WarehouseFairEventViewSet(viewsets.ViewSet):
    permission_classes = (WarehouseLocationAccess,)

    def list(self, request):
        events = WarehouseFairEvent.objects.select_related(
            "location",
        ).order_by("-starts_on", "-pk")[:200]
        return Response([fair_output(event) for event in events])

    def retrieve(self, request, pk=None):
        from django.shortcuts import get_object_or_404

        event = get_object_or_404(
            WarehouseFairEvent.objects.select_related("location"), pk=pk,
        )
        return Response(fair_output(event))

    def create(self, request):
        form = FairEventInput(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        # Si el navegador reintenta una creación exitosa, devolver exactamente
        # el mismo evento sin abrir otra ubicación física.
        old = WarehouseFairEvent.objects.select_related("location").filter(
            idempotency_key=data["idempotency_key"],
        ).first()
        if old is not None:
            if not _payload_equals(old, data):
                raise ValidationError({
                    "idempotency_key": "La referencia ya fue usada con otros datos.",
                })
            return Response(fair_output(old), status=status.HTTP_200_OK)

        try:
            with transaction.atomic():
                # El nombre identifica una ubicación única por evento, no el
                # almacén genérico compartido entre múltiples ferias.
                location_form = WarehouseLocationSerializer(data={
                    "name": data["name"],
                    "kind": WarehouseLocation.Kind.FAIR,
                    "address": data["venue_address"],
                    "notes": f"Recinto: {data['venue_name']}. Ubicación exclusiva de feria.",
                    "is_active": True,
                })
                location_form.is_valid(raise_exception=True)
                location = location_form.save()
                event = WarehouseFairEvent.objects.create(
                    location=location,
                    created_by=request.user,
                    **data,
                )
        except IntegrityError:
            # UNIQUE idempotency_key: dos peticiones simultáneas se resuelven
            # sin dos ubicaciones; la perdedora revierte toda su transacción.
            old = WarehouseFairEvent.objects.select_related("location").filter(
                idempotency_key=data["idempotency_key"],
            ).first()
            if old is None:
                raise
            if not _payload_equals(old, data):
                raise ValidationError({
                    "idempotency_key": "La referencia ya fue usada con otros datos.",
                })
            return Response(fair_output(old), status=status.HTTP_200_OK)
        return Response(fair_output(event), status=status.HTTP_201_CREATED)
