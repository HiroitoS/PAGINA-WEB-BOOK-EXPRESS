"""Solicitudes internas de mercadería: autorización sin reservas ni salida de stock."""
from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from catalog.models import Product
from warehouse.models import (
    InternalStockRequest, InternalStockRequestEvent, InternalStockRequestItem,
    WarehouseLocation,
)


class RequestLineInput(serializers.Serializer):
    product_id = serializers.PrimaryKeyRelatedField(
        source="product", queryset=Product.objects.filter(is_active=True),
    )
    quantity = serializers.IntegerField(min_value=1, max_value=100000)


class RequestInput(serializers.Serializer):
    source_id = serializers.PrimaryKeyRelatedField(
        source="source", queryset=WarehouseLocation.objects.filter(is_active=True),
    )
    destination_id = serializers.PrimaryKeyRelatedField(
        source="destination", queryset=WarehouseLocation.objects.filter(is_active=True),
    )
    responsible_name = serializers.CharField(max_length=180, trim_whitespace=True)
    operation_name = serializers.CharField(
        max_length=180, allow_blank=True, required=False, trim_whitespace=True,
    )
    needed_on = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, allow_blank=True, required=False)
    items = RequestLineInput(many=True, allow_empty=False)

    def validate_items(self, value):
        if len(value) > 100:
            raise serializers.ValidationError("Selecciona como máximo 100 libros por solicitud.")
        ids = [line["product"].pk for line in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("No repitas el mismo libro. Ajusta su cantidad.")
        return value

    def validate(self, attrs):
        if attrs["source"] == attrs["destination"]:
            raise serializers.ValidationError({
                "destination_id": "Selecciona un destino diferente del almacén de origen.",
            })
        if (
            attrs["destination"].kind in (
                WarehouseLocation.Kind.FAIR,
                WarehouseLocation.Kind.CONSIGNMENT,
            )
            and not attrs.get("operation_name", "").strip()
        ):
            raise serializers.ValidationError({
                "operation_name": "Indica la feria o el colegio que recibirá la mercadería.",
            })
        if not attrs["responsible_name"].strip():
            raise serializers.ValidationError({
                "responsible_name": "Indica quién recibirá o gestionará el pedido.",
            })
        return attrs


class RequestLineOutput(serializers.ModelSerializer):
    product_id = serializers.IntegerField(read_only=True)
    class Meta:
        model = InternalStockRequestItem
        fields = ("id", "product_id", "product_name_snapshot",
                  "product_code_snapshot", "quantity_requested")


class RequestEventOutput(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = InternalStockRequestEvent
        fields = ("id", "action", "from_status", "to_status",
                  "note", "actor_name", "created_at")

    def get_actor_name(self, obj):
        return obj.actor.get_full_name().strip() or obj.actor.get_username()


class RequestOutput(serializers.ModelSerializer):
    items = RequestLineOutput(many=True, read_only=True)
    events = RequestEventOutput(many=True, read_only=True)
    source_name = serializers.CharField(source="source.name", read_only=True)
    destination_name = serializers.CharField(source="destination.name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    reference = serializers.UUIDField(read_only=True)

    class Meta:
        model = InternalStockRequest
        fields = (
            "id", "reference", "source", "source_name", "destination",
            "destination_name", "operation_name", "responsible_name",
            "needed_on", "notes", "status", "created_at", "updated_at",
            "approved_at", "created_by_name", "approved_by_name", "items", "events",
        )

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name().strip() or obj.created_by.get_username()

    def get_approved_by_name(self, obj):
        if not obj.approved_by_id:
            return ""
        return obj.approved_by.get_full_name().strip() or obj.approved_by.get_username()


class InternalRequestViewSet(viewsets.ViewSet):
    """La aprobación NO modifica existencias; solo autoriza la preparación."""

    def _require(self, user, codename):
        if not usuario_tiene_permiso(user, f"warehouse.{codename}"):
            raise PermissionDenied("No tienes autorización para realizar esta operación.")

    def _queryset(self):
        return InternalStockRequest.objects.select_related(
            "source", "destination", "created_by", "approved_by",
        ).prefetch_related("items", "events__actor")

    def _get(self, pk):
        from django.shortcuts import get_object_or_404
        return get_object_or_404(self._queryset(), pk=pk)

    def list(self, request):
        self._require(request.user, "view_internal_stock_requests")
        qs = self._queryset()
        state = request.query_params.get("status", "").strip()
        if state:
            if state not in InternalStockRequest.Status.values:
                raise ValidationError({"status": "Selecciona un estado válido."})
            qs = qs.filter(status=state)
        page = request.query_params.get("page", "1")
        if not page.isdecimal() or int(page) < 1:
            raise ValidationError({"page": "Página no válida."})
        pages = Paginator(qs, 20)
        try:
            current = pages.page(int(page))
        except EmptyPage:
            current = []
        return Response({
            "count": pages.count, "pages": max(1, pages.num_pages),
            "results": RequestOutput(current, many=True).data,
        })

    def retrieve(self, request, pk=None):
        self._require(request.user, "view_internal_stock_requests")
        return Response(RequestOutput(self._get(pk)).data)

    @action(detail=False, methods=["get"], url_path="productos")
    def products(self, request):
        self._require(request.user, "view_internal_stock_requests")
        q = request.query_params.get("q", "").strip()
        if len(q) < 2 or len(q) > 100:
            raise ValidationError({"q": "Escribe entre 2 y 100 caracteres para buscar libros."})
        results = Product.objects.filter(is_active=True).filter(
            Q(name__icontains=q) | Q(code__icontains=q)
            | Q(provider__name__icontains=q)
        ).select_related("provider").order_by("name", "pk")[:20]
        return Response([
            {
                "id": product.pk,
                "name": product.name,
                "code": product.code,
                "editorial": product.provider.name,
            }
            for product in results
        ])

    def create(self, request):
        self._require(request.user, "manage_internal_stock_requests")
        serializer = RequestInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        items = values.pop("items")
        with transaction.atomic():
            record = InternalStockRequest.objects.create(
                **values, created_by=request.user,
            )
            InternalStockRequestItem.objects.bulk_create([
                InternalStockRequestItem(
                    request=record, product=row["product"],
                    product_name_snapshot=row["product"].name,
                    product_code_snapshot=row["product"].code,
                    quantity_requested=row["quantity"],
                )
                for row in items
            ])
            InternalStockRequestEvent.objects.create(
                request=record, actor=request.user,
                action="created", to_status=record.status,
                note="Solicitud registrada para revisión.",
            )
        return Response(RequestOutput(self._get(record.pk)).data, status=status.HTTP_201_CREATED)

    def _transition(self, request, pk, action_name):
        permission = (
            "approve_internal_stock_requests"
            if action_name in ("approved", "rejected")
            else "manage_internal_stock_requests"
        )
        self._require(request.user, permission)
        note = str(request.data.get("note", "")).strip()
        if len(note) > 500:
            raise ValidationError({"note": "La observación no puede superar 500 caracteres."})
        if action_name == "rejected" and len(note) < 5:
            raise ValidationError({"note": "Indica el motivo de rechazo."})
        with transaction.atomic():
            from django.shortcuts import get_object_or_404
            record = get_object_or_404(
                InternalStockRequest.objects.select_for_update(), pk=pk,
            )
            if record.status != InternalStockRequest.Status.SUBMITTED:
                raise ValidationError({
                    "detail": "Esta solicitud ya fue atendida y no puede modificarse.",
                })
            if action_name == "cancelled" and (
                record.created_by_id != request.user.pk
                and not usuario_tiene_permiso(
                    request.user, "warehouse.approve_internal_stock_requests",
                )
            ):
                raise PermissionDenied("Solo quien registró la solicitud o un responsable autorizado puede anularla.")
            previous = record.status
            record.status = action_name
            if action_name == "approved":
                record.approved_by = request.user
                record.approved_at = timezone.now()
            record.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
            InternalStockRequestEvent.objects.create(
                request=record, actor=request.user,
                action=action_name, from_status=previous,
                to_status=record.status, note=note,
            )
        return Response(RequestOutput(self._get(record.pk)).data)

    @action(detail=True, methods=["post"], url_path="aprobar")
    def approve(self, request, pk=None):
        return self._transition(request, pk, InternalStockRequest.Status.APPROVED)

    @action(detail=True, methods=["post"], url_path="rechazar")
    def reject(self, request, pk=None):
        return self._transition(request, pk, InternalStockRequest.Status.REJECTED)

    @action(detail=True, methods=["post"], url_path="anular")
    def cancel(self, request, pk=None):
        return self._transition(request, pk, InternalStockRequest.Status.CANCELLED)
