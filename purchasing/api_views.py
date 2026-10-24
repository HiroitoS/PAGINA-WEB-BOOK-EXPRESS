from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404, HttpResponse
from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from crm.models import Adoption
from purchasing.api_serializers import (GenerateFromAdoptionSerializer, PurchaseOrderSerializer,
    ChangeQuantitySerializer, DispatchEvidenceSerializer)
from purchasing.order_management import actualizar_cantidad_borrador, aprobar_pedido, registrar_envio_pedido
from purchasing.models import PurchaseOrder, PurchaseOrderEvent
from purchasing.order_pdf import generar_orden_compra_pdf
from purchasing.order_creation import create_orders_from_adoption


class PurchaseOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PurchaseOrderSerializer

    def get_queryset(self):
        if not usuario_tiene_permiso(self.request.user, "purchasing.view_purchasing"):
            raise PermissionDenied("No tienes permiso para consultar pedidos.")
        queryset = PurchaseOrder.objects.select_related(
            "provider", "school", "campaign", "adoption"
        ).prefetch_related("items").order_by("-created_at", "-pk")
        for key in ("provider", "school", "campaign"):
            raw = self.request.query_params.get(key)
            if raw is not None:
                if not raw.isdecimal():
                    raise ValidationError({key: "Debe indicar un identificador numérico."})
                queryset = queryset.filter(**{f"{key}_id": int(raw)})
        state = self.request.query_params.get("status")
        if state:
            valid = {value for value, _ in PurchaseOrder.Status.choices}
            if state not in valid:
                raise ValidationError({"status": "Estado no válido."})
            queryset = queryset.filter(status=state)
        return queryset

    @action(detail=False, methods=["get"], url_path="adopciones-confirmadas")
    def confirmed_adoptions(self, request):
        if not usuario_tiene_permiso(request.user, "purchasing.manage_purchasing"):
            raise PermissionDenied("No tienes permiso para preparar pedidos.")
        queryset = (
            Adoption.objects.filter(is_current=True, confirmed_at__isnull=False)
            .select_related("school", "campaign")
            .annotate(items_count=Count("items", distinct=True))
            .filter(items_count__gt=0)
            .order_by("-confirmed_at", "-pk")
        )
        search = request.query_params.get("buscar", "").strip()
        if search:
            queryset = queryset.filter(
                Q(school__name__icontains=search)
                | Q(school_name_snapshot__icontains=search)
            )
        campaign = request.query_params.get("campania", "").strip()
        if campaign:
            if not campaign.isdecimal():
                raise ValidationError({"campania": "Campaña no válida."})
            queryset = queryset.filter(campaign_id=int(campaign))
        page = self.paginate_queryset(queryset)
        records = page if page is not None else queryset[:50]
        data = [
            {
                "id": adoption.pk,
                "colegio": adoption.school_name_snapshot,
                "campania": adoption.campaign_name_snapshot,
                "version": adoption.version,
                "productos": adoption.items_count,
                "confirmada": adoption.confirmed_at,
                "pedidos_existentes": PurchaseOrder.objects.filter(adoption=adoption).count(),
            }
            for adoption in records
        ]
        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)

    @action(detail=False, methods=["get"], url_path="adopciones-por-editorial")
    def adoptions_by_editorial(self, request):
        if not usuario_tiene_permiso(request.user, "purchasing.manage_purchasing"):
            raise PermissionDenied("No tienes permiso para preparar pedidos.")
        search = request.query_params.get("buscar", "").strip()
        adoptions = (
            Adoption.objects.filter(is_current=True, confirmed_at__isnull=False)
            .select_related("campaign")
            .prefetch_related("items__product__provider", "purchase_orders")
            .order_by("-confirmed_at", "-pk")
        )
        if search:
            adoptions = adoptions.filter(school_name_snapshot__icontains=search)
        groups = {}
        for adoption in adoptions[:200]:
            existing = {order.provider_id: order for order in adoption.purchase_orders.all()}
            providers = {}
            for line in adoption.items.all():
                if line.quantity < 1 or not line.product.provider_id:
                    continue
                provider = line.product.provider
                record = providers.setdefault(provider.pk, {
                    "editorial_id": provider.pk,
                    "editorial": provider.name,
                    "lineas": 0,
                    "unidades": 0,
                })
                record["lineas"] += 1
                record["unidades"] += line.quantity
            for provider_id, detail in providers.items():
                group = groups.setdefault(provider_id, {
                    "editorial_id": provider_id,
                    "editorial": detail["editorial"],
                    "adopciones": [],
                })
                order = existing.get(provider_id)
                group["adopciones"].append({
                    "id": adoption.pk,
                    "colegio": adoption.school_name_snapshot,
                    "campania": adoption.campaign_name_snapshot,
                    "confirmada": adoption.confirmed_at,
                    "lineas": detail["lineas"],
                    "unidades": detail["unidades"],
                    "pedido_id": order.pk if order else None,
                    "estado_pedido": order.status if order else "pendiente",
                })
        return Response(sorted(groups.values(), key=lambda group: group["editorial"].casefold()))

    @action(detail=False, methods=["post"], url_path="generar-desde-adopcion")
    def generate_from_adoption(self, request):
        if not usuario_tiene_permiso(request.user, "purchasing.manage_purchasing"):
            raise PermissionDenied("No tienes permiso para generar pedidos.")
        serializer = GenerateFromAdoptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            orders = create_orders_from_adoption(
                adoption_id=serializer.validated_data["adoption_id"], actor=request.user,
                provider_id=serializer.validated_data.get("provider_id"),
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        except Adoption.DoesNotExist as exc:
            raise Http404("Adopción no encontrada.") from exc
        return Response(PurchaseOrderSerializer(orders, many=True).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="orden-pdf")
    def export_purchase_order(self, request, pk=None):
        pedido = self.get_object()
        if pedido.status not in {
            PurchaseOrder.Status.APPROVED,
            PurchaseOrder.Status.SENT,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
            PurchaseOrder.Status.RECEIVED,
            PurchaseOrder.Status.CLOSED_PARTIAL,
        }:
            return Response(
                {"detail": "Solo los pedidos aprobados pueden exportarse como orden de compra."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            contenido = generar_orden_compra_pdf(pedido)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        PurchaseOrderEvent.objects.create(
            order=pedido, actor=request.user, event_type="document_exported",
            from_status=pedido.status, to_status=pedido.status,
            notes="Descarga del PDF de orden de compra.",
        )
        respuesta = HttpResponse(contenido, content_type="application/pdf")
        respuesta["Content-Disposition"] = (
            f'attachment; filename="BE-OC-{pedido.pk:06d}.pdf"'
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta

    @action(detail=True, methods=["post"], url_path="cambiar-cantidad")
    def change_quantity(self, request, pk=None):
        data = ChangeQuantitySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            pedido = actualizar_cantidad_borrador(
                pedido_id=pk, detalle_id=data.validated_data["item_id"],
                cantidad=data.validated_data["quantity"], actor=request.user,
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response(PurchaseOrderSerializer(pedido).data)

    @action(detail=True, methods=["post"], url_path="aprobar")
    def approve(self, request, pk=None):
        try:
            pedido = aprobar_pedido(pedido_id=pk, actor=request.user)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response(PurchaseOrderSerializer(pedido).data)

    @action(detail=True, methods=["post"], url_path="registrar-envio")
    def record_dispatch(self, request, pk=None):
        data = DispatchEvidenceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            pedido = registrar_envio_pedido(
                pedido_id=pk, actor=request.user, evidencia=data.validated_data["evidence"],
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response(PurchaseOrderSerializer(pedido).data)
