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
from warehouse.models import (
    DistributionOperation, DistributionOperationLine, DistributionDispatch,
    DistributionOperationEvent, DistributionDispatchLine,
    DistributionStockReservation, StockEntry, StockMovement,
    WarehouseFairEvent, WarehouseLocation,
)
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
    fair_event_id = serializers.SerializerMethodField()

    def get_fair_event_id(self, obj):
        event = getattr(obj, "fair_event", None)
        return event.pk if event is not None else None

    class Meta:
        model = WarehouseLocation
        fields = ("id", "code", "name", "kind", "address", "is_active", "notes", "fair_event_id")
        read_only_fields = ("id", "code", "fair_event_id")

    def validate(self, attrs):
        if self.instance is not None and "code" in self.initial_data:
            # Identificador inmutable para documentos e integraciones futuras.
            raise serializers.ValidationError({
                "code": "El identificador interno no puede modificarse."
            })
        if (
            self.instance is not None
            and WarehouseFairEvent.objects.filter(location_id=self.instance.pk).exists()
            and any(
                field in attrs and attrs[field] != getattr(self.instance, field)
                for field in ("name", "kind", "address", "is_active", "notes")
            )
        ):
            raise serializers.ValidationError({
                "detail": (
                    "Esta ubicación pertenece a una feria específica. "
                    "Sus datos se conservarán hasta contar con una corrección auditada."
                ),
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
    queryset = WarehouseLocation.objects.select_related("fair_event").all().order_by("name", "pk")

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
        reservations = {
            (row["stock_entry_id"], row["source_id"]): row["total"]
            for row in DistributionStockReservation.objects.filter(
                stock_entry_id__in=[entry.pk for entry in entries],
                status=DistributionStockReservation.Status.ACTIVE,
            ).values("stock_entry_id", "source_id").annotate(total=Sum("quantity"))
        }
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
        reserved_by_location = {}
        free_by_location = {}
        for (entry_id, location_id), amount in positions.items():
            if amount <= 0:
                continue
            reserved = reservations.get((entry_id, location_id), 0)
            reserved_by_location[location_id] = (
                reserved_by_location.get(location_id, 0) + reserved
            )
            free_by_location[location_id] = (
                free_by_location.get(location_id, 0) + max(0, amount - reserved)
            )
        locations = list(WarehouseLocation.objects.order_by("name", "pk"))
        return Response({
            "locations": [{
                "id": loc.pk, "name": loc.name, "kind": loc.kind,
                **totals.get(loc.pk, {"available": 0, "observed": 0, "lots": 0}),
                "reserved": reserved_by_location.get(loc.pk, 0),
                "free_to_transfer": free_by_location.get(loc.pk, 0),
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

    @action(detail=False, methods=["get"], url_path="retornos-documentacion-pendiente")
    def pending_return_documents(self, request):
        """Auditoría documental: recepciones físicas que requieren revisión.

        Consulta solamente; no modifica movimientos ni presume que un
        documento tributario pendiente haya sido regularizado.
        """
        if not usuario_tiene_permiso(request.user, "warehouse.validate_receiving"):
            raise PermissionDenied("Solo Jefatura puede revisar observaciones documentales.")
        events = list(DistributionOperationEvent.objects.filter(
            action__in=("fair_return_recorded", "consign_return_recorded"),
            current__documentation_followup_required=True,
        ).select_related(
            "operation__school", "operation__destination", "operation__source",
            "actor",
        ).order_by("-created_at", "-pk")[:101])
        records = []
        for event in events[:100]:
            operation = event.operation
            records.append({
                "event_id": event.pk,
                "operation_id": operation.pk,
                "mode": operation.mode,
                "school": operation.school.name,
                "from_location": operation.destination.name,
                "to_location": operation.source.name,
                "received_by": event.current.get("receiver_name", ""),
                "registered_by": event.actor.get_username(),
                "registered_at": event.created_at,
                "quantity": sum(
                    line.get("quantity", 0) for line in event.current.get("lines", [])
                ),
                "documentation_note": event.current.get("documentation_note", ""),
                "documentation_status": "pending_review",
            })
        return Response({
            "results": records,
            "more_records": len(events) > 100,
            "notice": (
                "Documentación pendiente de revisión. No equivale a GRE emitida, "
                "aceptada ni a un trámite tributario concluido."
            ),
        })

    @action(detail=False, methods=["get"], url_path="seguimiento-consignaciones")
    def consignment_tracking(self, request):
        """Seguimiento logístico de consignaciones sin inventar cobros o ventas.

        Un despacho recibido no equivale a una venta. El sistema financiero
        todavía no relaciona abonos, comprobantes ni liquidación final.
        """
        if not usuario_tiene_permiso(request.user, "warehouse.view_receiving"):
            raise PermissionDenied("No tienes permiso para consultar consignaciones.")

        operations = list(DistributionOperation.objects.filter(
            mode=DistributionOperation.Mode.CONSIGNMENT,
        ).exclude(
            status=DistributionOperation.Status.CANCELLED,
        ).select_related(
            "school", "source", "destination",
        ).order_by("-created_at", "-pk")[:60])
        dispatched = {
            row.operation_id: row
            for row in DistributionDispatch.objects.filter(
                operation_id__in=[op.pk for op in operations],
            )
        }
        returned = {}
        for event in DistributionOperationEvent.objects.filter(
            operation_id__in=[op.pk for op in operations],
            action__in=("consign_return_recorded", "fair_return_recorded"),
        ):
            returned[event.operation_id] = returned.get(event.operation_id, 0) + sum(
                item["quantity"] for item in event.current.get("lines", [])
            )
        lines = DistributionOperationLine.objects.filter(
            operation_id__in=[op.pk for op in operations],
        ).values("operation_id").annotate(quantity=Sum("quantity_planned"))
        planned = {row["operation_id"]: row["quantity"] for row in lines}
        dispatched_lines = DistributionDispatchLine.objects.filter(
            dispatch__operation_id__in=[op.pk for op in operations],
        ).values("dispatch__operation_id").annotate(quantity=Sum("quantity"))
        physical_delivery = {
            row["dispatch__operation_id"]: row["quantity"] for row in dispatched_lines
        }
        results = []
        for op in operations:
            dispatch = dispatched.get(op.pk)
            received = bool(dispatch and dispatch.status == DistributionDispatch.Status.RECEIVED)
            results.append({
                "operation_id": op.pk,
                "name": op.operation_name,
                "school": op.school.name,
                "source": op.source.name,
                "destination": op.destination.name,
                "status": op.status,
                "planned_units": planned.get(op.pk, 0),
                "delivered_units": physical_delivery.get(op.pk, 0) if received else None,
                "returned_units": returned.get(op.pk, 0),
                "financial_status": "not_integrated",
            })
        return Response({
            "count": len(results),
            "results": results,
            "limited": len(results) == 60,
            "notice": (
                "Seguimiento logístico, no liquidación comercial. "
                "Los pagos parciales, ventas, comprobantes y deuda por cobrar "
                "se integrarán en Ventas y Tesorería. No infieras ventas desde devoluciones."
            ),
        })

    @action(detail=False, methods=["get"], url_path="alertas-reposicion")
    def replenishment_alerts(self, request):
        """Demanda logística planificada vs stock libre del almacén.

        No confundir con toda la población de adopciones ni generar compras.
        Contamos solo entregas pendientes de preparar, evitando duplicar
        operaciones ya reservadas, preparadas, despachadas o recibidas.
        """
        if not usuario_tiene_permiso(request.user, "warehouse.view_receiving"):
            raise PermissionDenied("No tienes permiso para consultar existencias.")
        raw = request.query_params.get("location_id", "")
        if not raw.isdecimal() or int(raw) < 1:
            raise ValidationError({"location_id": "Selecciona un almacén válido."})
        location = WarehouseLocation.objects.filter(pk=int(raw), is_active=True).first()
        if location is None:
            raise ValidationError({"location_id": "El almacén no está activo."})

        lines = list(DistributionOperationLine.objects.filter(
            operation__source_id=location.pk,
            operation__status=DistributionOperation.Status.PLANNED,
        ).select_related(
            "product__provider", "operation__school", "operation__adoption",
        ).order_by("product_id", "operation_id", "pk"))
        demands = {}
        for line in lines:
            record = demands.setdefault(line.product_id, {
                "product_id": line.product_id,
                "product": line.product.name,
                "editorial": line.product.provider.name,
                "required": 0,
                "operations": [],
            })
            record["required"] += line.quantity_planned
            record["operations"].append({
                "operation_id": line.operation_id,
                "adoption_id": line.operation.adoption_id,
                "school": line.operation.school.name,
                "quantity": line.quantity_planned,
            })

        entries = list(StockEntry.objects.filter(
            product_id__in=demands,
        ).select_related("initial_location"))
        from warehouse.transfers import posiciones_lotes
        positions = posiciones_lotes(entries)
        reservations = {
            row["stock_entry_id"]: row["total"]
            for row in DistributionStockReservation.objects.filter(
                stock_entry_id__in=[entry.pk for entry in entries],
                source_id=location.pk,
                status=DistributionStockReservation.Status.ACTIVE,
            ).values("stock_entry_id").annotate(total=Sum("quantity"))
        }
        free_by_product = {}
        for entry in entries:
            physical = positions.get((entry.pk, location.pk), 0)
            free = max(0, physical - reservations.get(entry.pk, 0))
            free_by_product[entry.product_id] = free_by_product.get(entry.product_id, 0) + free

        alerts = []
        for row in demands.values():
            free = free_by_product.get(row["product_id"], 0)
            missing = max(0, row["required"] - free)
            if missing:
                alerts.append({
                    **row, "free": free, "shortage": missing,
                })
        alerts.sort(key=lambda x: (-x["shortage"], x["editorial"].casefold(), x["product"].casefold()))
        return Response({
            "location_id": location.pk,
            "location": location.name,
            "products_with_shortage": len(alerts),
            "missing_units": sum(row["shortage"] for row in alerts),
            "results": alerts[:30],
            "more_products": max(0, len(alerts) - 30),
            "scope": "Solo entregas por preparar desde este almacén.",
            "notice": (
                "Alerta de planificación, no orden automática de compra. "
                "Contrasta con adopciones y pedidos editoriales antes de solicitar."
            ),
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
