from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from crm.models import Adoption
from purchasing.api_serializers import (GenerateFromAdoptionSerializer, PurchaseOrderSerializer,
    ChangeQuantitySerializer, DispatchEvidenceSerializer)
from purchasing.order_management import actualizar_cantidad_borrador, aprobar_pedido, registrar_envio_pedido
from purchasing.models import PurchaseOrder
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

    @action(detail=False, methods=["post"], url_path="generar-desde-adopcion")
    def generate_from_adoption(self, request):
        if not usuario_tiene_permiso(request.user, "purchasing.manage_purchasing"):
            raise PermissionDenied("No tienes permiso para generar pedidos.")
        serializer = GenerateFromAdoptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            orders = create_orders_from_adoption(
                adoption_id=serializer.validated_data["adoption_id"], actor=request.user,
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        except Adoption.DoesNotExist as exc:
            raise Http404("Adopción no encontrada.") from exc
        return Response(PurchaseOrderSerializer(orders, many=True).data, status=status.HTTP_200_OK)

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
