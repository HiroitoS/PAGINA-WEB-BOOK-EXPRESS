"""Lectura de ubicaciones físicas de almacén (P-08.0).

No permite crear ubicaciones aún: antes deben definirse permisos y flujo de
alta. No asigna existencias históricas ni realiza traslados.
"""
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import WarehouseLocation


class WarehouseLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = WarehouseLocation
        fields = ("id", "code", "name", "kind", "address", "is_active", "notes")
        read_only_fields = fields


class WarehouseLocationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WarehouseLocationSerializer
    pagination_class = None

    def get_queryset(self):
        if not usuario_tiene_permiso(
            self.request.user, "warehouse.view_warehouse_locations"
        ):
            raise PermissionDenied("No tienes permiso para consultar ubicaciones.")
        return WarehouseLocation.objects.all().order_by("name", "pk")
