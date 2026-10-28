"""Administración controlada de ubicaciones físicas (P-08.1a).

No asigna stock, no crea movimientos ni acepta eliminaciones. Los saldos
por ubicación llegarán tras conciliar físicamente cada lote preexistente.
"""
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import BasePermission

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import WarehouseLocation


class WarehouseLocationAccess(BasePermission):
    """Consulta y modificación son permisos funcionales distintos."""

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
        read_only_fields = ("id",)

    def validate_code(self, value):
        code = value.strip().upper()
        if not code:
            raise serializers.ValidationError("Ingresa un código de ubicación.")
        if not all(ch.isalnum() or ch in "-_" for ch in code):
            raise serializers.ValidationError(
                "El código solo permite letras, números, guiones y guiones bajos."
            )
        qs = WarehouseLocation.objects.filter(code__iexact=code)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Este código ya está registrado.")
        return code

    def validate(self, attrs):
        if self.instance is not None:
            # No alterar identificadores usados por futuras integraciones.
            new_code = attrs.get("code")
            if new_code is not None and new_code != self.instance.code:
                raise serializers.ValidationError({
                    "code": "No se puede cambiar el código de una ubicación existente."
                })
        return attrs


class WarehouseLocationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """GET/POST/PATCH protegidos; DELETE siempre deshabilitado."""

    serializer_class = WarehouseLocationSerializer
    permission_classes = (WarehouseLocationAccess,)
    pagination_class = None
    queryset = WarehouseLocation.objects.all().order_by("name", "pk")
