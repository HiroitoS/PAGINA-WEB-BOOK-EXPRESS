"""Administración de ubicaciones físicas (P-08).

Crear una ubicación NO registra entradas ni asigna saldos históricos.
El código interno es estable, único y generado por el servidor; nunca se
solicita al responsable de almacén.
"""
import uuid

from django.db import IntegrityError, transaction
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import BasePermission

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import WarehouseLocation


def generar_codigo_ubicacion():
    """Identificador interno opaco, independiente del nombre y del tipo."""
    return f"UBI-{uuid.uuid4().hex[:24].upper()}"


class WarehouseLocationAccess(BasePermission):
    """Consulta y modificación están protegidas por permisos distintos."""

    def has_permission(self, request, view):
        permiso = (
            "warehouse.view_warehouse_locations"
            if request.method in ("GET", "HEAD", "OPTIONS")
            else "warehouse.manage_warehouse_locations"
        )
        return usuario_tiene_permiso(request.user, permiso)


class WarehouseLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = WarehouseLocation
        fields = ("id", "code", "name", "kind", "address", "is_active", "notes")
        read_only_fields = ("id", "code")

    def validate(self, attrs):
        if self.instance is not None and "code" in self.initial_data:
            # El código de un lugar registrado no cambia, aunque cambie el
            # nombre, el tipo de custodia o la dirección.
            raise serializers.ValidationError({
                "code": "El identificador interno no puede modificarse."
            })
        return attrs

    def create(self, validated_data):
        # El campo tiene UNIQUE en PostgreSQL. Una colisión muy improbable
        # se recupera con un nuevo UUID y un savepoint por intento.
        for _ in range(5):
            code = generar_codigo_ubicacion()
            try:
                with transaction.atomic():
                    return WarehouseLocation.objects.create(
                        code=code, **validated_data
                    )
            except IntegrityError:
                if not WarehouseLocation.objects.filter(code=code).exists():
                    raise  # No ocultar errores de integridad no relacionados.
        raise serializers.ValidationError({
            "detail": "No se pudo asignar un identificador. Intenta nuevamente."
        })


class WarehouseLocationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """GET/POST/PATCH protegidos. No se admiten eliminaciones."""

    serializer_class = WarehouseLocationSerializer
    permission_classes = (WarehouseLocationAccess,)
    pagination_class = None
    queryset = WarehouseLocation.objects.all().order_by("name", "pk")
