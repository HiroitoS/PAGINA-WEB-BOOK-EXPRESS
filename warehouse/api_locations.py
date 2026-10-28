"""Administración de ubicaciones físicas (P-08).

Crear una ubicación NO registra entradas ni asigna saldos históricos.
El código interno es estable, único y generado por el servidor; nunca se
solicita al responsable de almacén.
"""
import uuid

from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q, Sum
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import BasePermission

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import StockEntry, StockMovement, WarehouseLocation
from warehouse.location_assignment import conciliar_lotes


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
            # Identificador inmutable para documentos e integraciones futuras.
            raise serializers.ValidationError({
                "code": "El identificador interno no puede modificarse."
            })
        kind = attrs.get("kind", self.instance.kind if self.instance else None)
        is_active = attrs.get(
            "is_active", self.instance.is_active if self.instance else True,
        )
        if kind == WarehouseLocation.Kind.MAIN and is_active:
            main_qs = WarehouseLocation.objects.filter(
                kind=WarehouseLocation.Kind.MAIN, is_active=True,
            )
            if self.instance is not None:
                main_qs = main_qs.exclude(pk=self.instance.pk)
            if main_qs.exists():
                raise serializers.ValidationError({
                    "kind": "Ya existe un almacén principal activo. Usa otro tipo de ubicación.",
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


class InitialLocationAssignmentSerializer(serializers.Serializer):
    entry_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=100,
    )
    confirmado_fisicamente = serializers.BooleanField()
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate_confirmado_fisicamente(self, value):
        if not value:
            raise serializers.ValidationError(
                "Confirma que todos los lotes seleccionados están físicamente en este lugar."
            )
        return value


def _saldos_entradas(entries):
    """Lista de saldos netos en una consulta, sin crear unidades ficticias."""
    ids = [entry.pk for entry in entries]
    salidas = {
        row["source_entry_id"]: row["quantity"]
        for row in StockMovement.objects.filter(
            source_entry_id__in=ids
        ).values("source_entry_id").annotate(quantity=Sum("quantity_delta"))
    }
    return {
        entry.pk: entry.quantity_available + salidas.get(entry.pk, 0)
        for entry in entries
    }


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

    @action(detail=False, methods=["get"], url_path="pendientes-asignacion")
    def pending_assignments(self, request):
        if not usuario_tiene_permiso(request.user, "warehouse.view_receiving"):
            raise PermissionDenied("No tienes permiso para consultar las existencias.")
        from django.core.paginator import Paginator, EmptyPage
        qs = StockEntry.objects.filter(initial_location__isnull=True).select_related(
            "product__provider", "receipt_line__receipt",
            "receipt_line__order_item__order",
        ).order_by("pk")
        q = request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(product__name__icontains=q) |
                Q(product__provider__name__icontains=q) |
                Q(receipt_line__receipt__document_number__icontains=q) |
                Q(receipt_line__order_item__order__school_name_snapshot__icontains=q)
            )
        paginator = Paginator(qs, 25)
        raw = request.query_params.get("page", "1")
        if not raw.isdecimal() or int(raw) < 1:
            raise ValidationError({"page": "Página no válida."})
        try:
            page = paginator.page(int(raw))
        except EmptyPage:
            raise ValidationError({"page": "No existen resultados en esa página."})
        entries = list(page.object_list)
        saldos = _saldos_entradas(entries)
        data = []
        for entry in entries:
            order = entry.receipt_line.order_item.order
            data.append({
                "id": entry.pk,
                "product": entry.product.name,
                "editorial": entry.product.provider.name,
                "school": order.school_name_snapshot or "Pedido independiente",
                "guide": entry.receipt_line.receipt.document_number,
                "available": saldos[entry.pk],
                "observed": entry.quantity_quarantined,
                "unit_cost": (
                    str(entry.unit_cost_snapshot)
                    if entry.unit_cost_snapshot is not None else None
                ),
            })
        return Response({
            "count": paginator.count,
            "page": page.number,
            "pages": paginator.num_pages,
            "results": data,
        })

    @action(detail=False, methods=["get"], url_path="resumen-ubicaciones")
    def location_summary(self, request):
        if not usuario_tiene_permiso(request.user, "warehouse.view_receiving"):
            raise PermissionDenied("No tienes permiso para consultar las existencias.")
        from warehouse.transfers import posiciones_lotes

        entries = list(StockEntry.objects.select_related(
            "initial_location", "product",
        ).all())
        balances = _saldos_entradas(entries)
        positions = posiciones_lotes(entries)
        totals = {}
        unassigned = {"available": 0, "observed": 0, "lots": 0}
        for entry in entries:
            assignment = getattr(entry, "initial_location", None)
            if assignment is None:
                unassigned["available"] += balances[entry.pk]
                unassigned["observed"] += entry.quantity_quarantined
                unassigned["lots"] += 1
                continue
            item = totals.setdefault(assignment.location_id, {
                "available": 0, "observed": 0, "lots": 0,
            })
            item["observed"] += entry.quantity_quarantined
        for (entry_id, loc_id), quantity in positions.items():
            item = totals.setdefault(loc_id, {
                "available": 0, "observed": 0, "lots": 0,
            })
            item["available"] += quantity
            if quantity > 0:
                item["lots"] += 1
        # Valoración por lugar al costo histórico del lote; sin inventar costos.
        from decimal import Decimal
        entries_by_id = {entry.pk: entry for entry in entries}
        values = {}
        for (entry_id, location_id), quantity in positions.items():
            if quantity <= 0:
                continue
            amount = values.setdefault(location_id, {
                "value": Decimal("0.00"), "missing_cost": 0,
            })
            cost = entries_by_id[entry_id].unit_cost_snapshot
            if cost is None:
                amount["missing_cost"] += quantity
            else:
                amount["value"] += cost * quantity
        locations = list(WarehouseLocation.objects.order_by("name", "pk"))
        return Response({
            "locations": [{
                "id": loc.pk, "name": loc.name, "kind": loc.kind,
                **totals.get(loc.pk, {"available": 0, "observed": 0, "lots": 0}),
                "available_value_reference": str(
                    values.get(loc.pk, {}).get("value", Decimal("0.00"))
                ),
                "unvalued_available_units": values.get(loc.pk, {}).get("missing_cost", 0),
            } for loc in locations],
            "unassigned": unassigned,
            "global": {
                "available": sum(balances.values()),
                "observed": sum(e.quantity_quarantined for e in entries),
                "lots": len(entries),
            },
            "note": "Los traslados redistribuyen saldos por ubicación sin alterar el total global.",
        })

    @action(detail=True, methods=["post"], url_path="conciliar")
    def reconcile_location(self, request, pk=None):
        if not usuario_tiene_permiso(request.user, "warehouse.validate_receiving"):
            raise PermissionDenied("No tienes permiso para conciliar existencias.")
        location = self.get_object()
        serializer = InitialLocationAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = conciliar_lotes(
                location=location,
                entry_ids=serializer.validated_data["entry_ids"],
                actor=request.user,
                notes=serializer.validated_data.get("notes", ""),
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response({
            **result,
            "location_id": location.pk,
            "message": "La ubicación física de los lotes quedó registrada; no se generaron nuevas existencias.",
        })
