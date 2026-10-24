from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from catalog.models import Provider
from purchasing.models import PurchaseOrder
from warehouse.api_serializers import CreateReceiptSerializer, GoodsReceiptSerializer
from warehouse.models import GoodsReceipt
from warehouse.receiving import crear_borrador_recepcion, saldos_pedido, validar_recepcion


class GoodsReceiptViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = GoodsReceiptSerializer

    def get_queryset(self):
        if not usuario_tiene_permiso(self.request.user, "warehouse.view_receiving"):
            raise PermissionDenied("No tienes permiso para consultar recepciones.")
        queryset = GoodsReceipt.objects.select_related(
            "provider", "created_by", "validated_by",
        ).prefetch_related("lines__order_item").order_by("-received_on", "-pk")
        raw = self.request.query_params.get("provider")
        if raw:
            if not raw.isdecimal():
                raise ValidationError({"provider": "Identificador no válido."})
            queryset = queryset.filter(provider_id=int(raw))
        return queryset

    @action(detail=False, methods=["post"], url_path="crear")
    def create_draft(self, request):
        if not usuario_tiene_permiso(request.user, "warehouse.manage_receiving"):
            raise PermissionDenied("No tienes permiso para registrar recepciones.")
        serializer = CreateReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            receipt = crear_borrador_recepcion(
                actor=request.user, **serializer.validated_data,
            )
        except Provider.DoesNotExist as exc:
            raise Http404("Editorial no encontrada.") from exc
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response(
            GoodsReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="validar")
    def validate_draft(self, request, pk=None):
        if not usuario_tiene_permiso(request.user, "warehouse.validate_receiving"):
            raise PermissionDenied("No tienes permiso para validar recepciones.")
        self.get_object()
        try:
            receipt = validar_recepcion(actor=request.user, receipt_id=pk)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        return Response(GoodsReceiptSerializer(receipt).data)

    @action(detail=False, methods=["get"], url_path="saldos")
    def order_balances(self, request):
        raw = request.query_params.get("pedido", "").strip()
        if not raw.isdecimal() or int(raw) < 1:
            raise ValidationError({"pedido": "Indica el ID del pedido."})
        try:
            return Response(saldos_pedido(actor=request.user, order_id=int(raw)))
        except PurchaseOrder.DoesNotExist as exc:
            raise Http404("Pedido no encontrado.") from exc
