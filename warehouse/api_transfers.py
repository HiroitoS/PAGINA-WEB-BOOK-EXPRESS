"""API de traslados confirmados: movimientos, historial y saldos verificables."""
from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import GoodsReceipt, StockEntry, StockTransfer, WarehouseLocation
from warehouse.transfers import posiciones_lotes, registrar_traslado
from warehouse.bulk_transfers import registrar_traslado_por_guia


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


class TransferBatchItemSerializer(serializers.Serializer):
    stock_entry_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class TransferBatchInputSerializer(serializers.Serializer):
    receipt_id = serializers.IntegerField(min_value=1)
    source_id = serializers.IntegerField(min_value=1)
    destination_id = serializers.IntegerField(min_value=1)
    items = TransferBatchItemSerializer(many=True, allow_empty=False)
    idempotency_key = serializers.UUIDField()
    entrega_confirmada = serializers.BooleanField()
    notes = serializers.CharField(max_length=500, allow_blank=True, required=False)

    def validate_entrega_confirmada(self, value):
        if not value:
            raise serializers.ValidationError(
                "Confirma que todos los libros fueron entregados en el destino."
            )
        return value

    def validate_items(self, value):
        if len(value) > 200:
            raise serializers.ValidationError(
                "Selecciona como máximo 200 lotes por operación."
            )
        ids = [item["stock_entry_id"] for item in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Hay lotes repetidos.")
        return value


def _pagina(request):
    value = request.query_params.get("page", "1")
    if not value.isdecimal() or int(value) < 1:
        raise ValidationError({"page": "Página no válida."})
    return int(value)


def _identificador_filtro(request, campo):
    """Devuelve un ID positivo o None; los filtros inválidos no se ignoran."""
    value = request.query_params.get(campo, "").strip()
    if not value:
        return None
    if not value.isdecimal() or int(value) < 1:
        raise ValidationError({campo: "Selecciona un valor válido."})
    return int(value)


def _fecha_filtro(request, campo):
    value = request.query_params.get(campo, "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({campo: "Selecciona una fecha válida."}) from exc


class StockTransferViewSet(viewsets.ViewSet):
    """No permite editar ni borrar movimientos confirmados."""

    def _autorizar(self, request, write=False):
        permiso = ("warehouse.manage_stock_transfers" if write
                   else "warehouse.view_receiving")
        if not usuario_tiene_permiso(request.user, permiso):
            raise PermissionDenied("No tienes permiso para esta operación.")

    def list(self, request):
        """Historial paginado y filtrable, inalterable, con cada línea de cada traslado."""
        self._autorizar(request)
        qs = StockTransfer.objects.select_related(
            "stock_entry__product__provider", "stock_entry__receipt_line__receipt",
            "stock_entry__receipt_line__order_item__order", "source",
            "destination", "created_by",
        ).order_by("-created_at", "-pk")
        source_id = _identificador_filtro(request, "source_id")
        destination_id = _identificador_filtro(request, "destination_id")
        batch_id = _identificador_filtro(request, "batch_id")
        date_from = _fecha_filtro(request, "date_from")
        date_to = _fecha_filtro(request, "date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError({"date_to": "La fecha final debe ser igual o posterior a la inicial."})
        q = request.query_params.get("q", "").strip()
        if len(q) > 100:
            raise ValidationError({"q": "La búsqueda no puede superar 100 caracteres."})
        if source_id:
            qs = qs.filter(source_id=source_id)
        if destination_id:
            qs = qs.filter(destination_id=destination_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        if q:
            qs = qs.filter(
                Q(stock_entry__product__name__icontains=q)
                | Q(stock_entry__product__code__icontains=q)
                | Q(stock_entry__product__provider__name__icontains=q)
                | Q(stock_entry__receipt_line__receipt__document_number__icontains=q)
                | Q(stock_entry__receipt_line__order_item__order__school_name_snapshot__icontains=q)
            )
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
            "batch_id": move.batch_id,
            "operation_reference": (
                f"BE-TG-{move.batch_id:06d}" if move.batch_id
                else f"BE-TI-{move.pk:06d}"
            ),
            "operation_type": "guia" if move.batch_id else "individual",
            "product": entry.product.name,
            "editorial": entry.product.provider.name,
            "product_code": entry.product.code,
            "school": order.school_name_snapshot or "Pedido independiente",
            "guide": entry.receipt_line.receipt.document_number,
            "receipt_id": entry.receipt_line.receipt_id,
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
            "created_by_name": move.created_by.get_full_name().strip() or move.created_by.username,
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
                "receipt_id": e.receipt_line.receipt_id,
                "school": e.receipt_line.order_item.order.school_name_snapshot,
                "available": balances[(e.pk, location_id)],
                "unit_cost": (str(e.unit_cost_snapshot)
                              if e.unit_cost_snapshot is not None else None),
            } for e in current],
        })

    @action(detail=False, methods=["get"], url_path="guia")
    def guide_lots(self, request):
        """Lista completa y actualizada de los lotes trasladables de una guía."""
        self._autorizar(request)
        receipt_raw = request.query_params.get("receipt_id", "")
        source_raw = request.query_params.get("source_id", "")
        if not receipt_raw.isdecimal() or int(receipt_raw) < 1:
            raise ValidationError({"receipt_id": "Selecciona una guía válida."})
        if not source_raw.isdecimal() or int(source_raw) < 1:
            raise ValidationError({"source_id": "Selecciona el almacén de origen."})
        receipt_id, source_id = int(receipt_raw), int(source_raw)
        receipt = GoodsReceipt.objects.select_related("provider").filter(
            pk=receipt_id, status=GoodsReceipt.Status.VALIDATED,
            document_type=GoodsReceipt.DocumentType.GUIDE,
        ).first()
        if receipt is None:
            raise ValidationError({"receipt_id": "La guía ya no está disponible."})
        if not WarehouseLocation.objects.filter(pk=source_id, is_active=True).exists():
            raise ValidationError({"source_id": "El almacén de origen no está activo."})
        entries = list(StockEntry.objects.select_related(
            "initial_location", "product__provider",
            "receipt_line__order_item__order",
        ).filter(
            receipt_line__receipt_id=receipt_id,
        ).filter(
            Q(initial_location__location_id=source_id)
            | Q(transfers__destination_id=source_id)
        ).distinct().order_by("product__name", "pk"))
        balances = posiciones_lotes(entries)
        rows = [{
            "id": entry.pk, "product": entry.product.name,
            "editorial": entry.product.provider.name,
            "school": entry.receipt_line.order_item.order.school_name_snapshot,
            "available": balances.get((entry.pk, source_id), 0),
            "unit_cost": (
                str(entry.unit_cost_snapshot)
                if entry.unit_cost_snapshot is not None else None
            ),
        } for entry in entries if balances.get((entry.pk, source_id), 0) > 0]
        if len(rows) > 200:
            raise ValidationError({
                "detail": (
                    "Esta guía supera 200 lotes. Coordina su división en "
                    "operaciones controladas antes de trasladar."
                ),
            })
        return Response({
            "receipt_id": receipt.pk,
            "guide": receipt.document_number,
            "editorial": receipt.provider.name,
            "source_id": source_id,
            "results": rows,
        })

    @action(detail=False, methods=["post"], url_path="por-guia")
    def create_batch(self, request):
        """Traslada la selección completa o parcial de una guía en una transacción."""
        self._autorizar(request, write=True)
        serializer = TransferBatchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            batch, movements, created = registrar_traslado_por_guia(
                actor=request.user, **serializer.validated_data
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        qs = StockTransfer.objects.filter(
            pk__in=[move.pk for move in movements]
        ).select_related(
            "stock_entry__product", "stock_entry__receipt_line__receipt",
            "stock_entry__receipt_line__order_item__order", "source",
            "destination", "created_by",
        ).order_by("stock_entry_id")
        return Response({
            "batch_id": batch.pk,
            "guide": batch.receipt.document_number,
            "count": len(movements),
            "results": [self._movimiento(move) for move in qs],
            "message": (
                "Guía trasladada: se actualizaron los saldos por almacén."
                if created else "Este traslado de guía ya estaba confirmado."
            ),
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

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
