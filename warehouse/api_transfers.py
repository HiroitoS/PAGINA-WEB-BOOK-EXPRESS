"""API de P-08.2: consulta y traslados confirmados entre ubicaciones."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import StockEntry, StockTransfer, WarehouseLocation
from warehouse.transfers import posiciones_lotes, registrar_traslado


class TransferInputSerializer(serializers.Serializer):
    stock_entry_id = serializers.IntegerField(min_value=1)
    source_id = serializers.IntegerField(min_value=1)
    destination_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.UUIDField()
    entrega_confirmada = serializers.BooleanField()
    notes = serializers.CharField(max_length=500, allow_blank=True, required=False)

    def validate_entrega_confirmada(self, value):
        if not value:
            raise serializers.ValidationError(
                "Confirma que el destino recibió físicamente los libros."
            )
        return value


def _pagina(request):
    value = request.query_params.get("page", "1")
    if not value.isdecimal() or int(value) < 1:
        raise ValidationError({"page": "Página no válida."})
    return int(value)


class StockTransferViewSet(viewsets.ViewSet):
    """No permite editar ni borrar movimientos confirmados."""

    def _autorizar(self, request, write=False):
        permiso = ("warehouse.manage_stock_transfers" if write
                   else "warehouse.view_receiving")
        if not usuario_tiene_permiso(request.user, permiso):
            raise PermissionDenied("No tienes permiso para esta operación.")

    def list(self, request):
        self._autorizar(request)
        qs = StockTransfer.objects.select_related(
            "stock_entry__product", "stock_entry__receipt_line__receipt",
            "stock_entry__receipt_line__order_item__order", "source",
            "destination", "created_by",
        ).order_by("-created_at", "-pk")
        page = Paginator(qs, 25)
        try:
            current = page.page(_pagina(request))
        except EmptyPage:
            raise ValidationError({"page": "No existen resultados en esa página."})
        return Response({
            "count": page.count, "page": current.number,
            "pages": page.num_pages,
            "results": [self._movimiento(m) for m in current],
        })

    @staticmethod
    def _movimiento(move):
        entry = move.stock_entry
        order = entry.receipt_line.order_item.order
        return {
            "id": move.pk,
            "stock_entry_id": entry.pk,
            "product": entry.product.name,
            "school": order.school_name_snapshot or "Pedido independiente",
            "guide": entry.receipt_line.receipt.document_number,
            "source": move.source.name,
            "source_id": move.source_id,
            "destination": move.destination.name,
            "destination_id": move.destination_id,
            "quantity": move.quantity,
            "unit_cost": (str(move.unit_cost_snapshot)
                          if move.unit_cost_snapshot is not None else None),
            "value_reference": (str(move.quantity * move.unit_cost_snapshot)
                                if move.unit_cost_snapshot is not None else None),
            "notes": move.notes,
            "created_at": move.created_at,
            "created_by": move.created_by_id,
        }

    @action(detail=False, methods=["get"], url_path="lotes")
    def eligible_lots(self, request):
        self._autorizar(request)
        raw = request.query_params.get("source_id", "")
        if not raw.isdecimal() or int(raw) < 1:
            raise ValidationError({"source_id": "Selecciona un almacén de origen."})
        location_id = int(raw)
        if not WarehouseLocation.objects.filter(pk=location_id, is_active=True).exists():
            raise ValidationError({"source_id": "La ubicación ya no está activa."})
        q = request.query_params.get("q", "").strip()
        if len(q) > 100:
            raise ValidationError({"q": "La búsqueda es demasiado larga."})
        qs = StockEntry.objects.select_related(
            "initial_location", "product__provider",
            "receipt_line__receipt", "receipt_line__order_item__order",
        ).filter(
            Q(initial_location__location_id=location_id)
            | Q(transfers__destination_id=location_id)
        ).distinct().order_by("product__name", "pk")
        if q:
            qs = qs.filter(
                Q(product__name__icontains=q)
                | Q(product__provider__name__icontains=q)
                | Q(receipt_line__receipt__document_number__icontains=q)
                | Q(receipt_line__order_item__order__school_name_snapshot__icontains=q)
            )
        entries = list(qs)
        balances = posiciones_lotes(entries)
        available = [
            entry for entry in entries
            if balances.get((entry.pk, location_id), 0) > 0
        ]
        pages = Paginator(available, 25)
        try:
            current = pages.page(_pagina(request))
        except EmptyPage:
            raise ValidationError({"page": "No existen resultados en esa página."})
        return Response({
            "count": pages.count, "page": current.number,
            "pages": pages.num_pages,
            "results": [{
                "id": e.pk,
                "product": e.product.name,
                "editorial": e.product.provider.name,
                "guide": e.receipt_line.receipt.document_number,
                "school": e.receipt_line.order_item.order.school_name_snapshot,
                "available": balances[(e.pk, location_id)],
                "unit_cost": (str(e.unit_cost_snapshot)
                              if e.unit_cost_snapshot is not None else None),
            } for e in current],
        })

    def create(self, request):
        self._autorizar(request, write=True)
        serializer = TransferInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            move, created = registrar_traslado(
                actor=request.user, **serializer.validated_data
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        move = StockTransfer.objects.select_related(
            "stock_entry__product", "stock_entry__receipt_line__receipt",
            "stock_entry__receipt_line__order_item__order", "source",
            "destination", "created_by",
        ).get(pk=move.pk)
        return Response({
            **self._movimiento(move),
            "message": ("Traslado confirmado: se actualizó el saldo por ubicación."
                        if created else "Este traslado ya había sido registrado."),
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
