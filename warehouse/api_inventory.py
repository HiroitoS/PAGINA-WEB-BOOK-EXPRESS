"""API de Inventario y movimientos; separada de Recepción sin cambiar rutas."""
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum, F, Q, OuterRef, Subquery, DecimalField, ExpressionWrapper, Case, When, Value, IntegerField
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from warehouse.models import GoodsReceipt, StockEntry, StockMovement
from warehouse.inventory import registrar_entrada_recepcion
from warehouse.stock_movements import registrar_cortesia, saldo_entrada
from warehouse.valuation import valorizar_por_editorial


class CourtesyInputSerializer(serializers.Serializer):
    stock_entry_id = serializers.IntegerField(min_value=1)
    school_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)
    recipient_name = serializers.CharField(max_length=200)
    recipient_role = serializers.CharField(max_length=80)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)
    idempotency_key = serializers.UUIDField()


class InventoryEntryViewSet(viewsets.ReadOnlyModelViewSet):
    """Ingresos confirmados: una línea de recepción tiene una sola entrada."""

    def get_queryset(self):
        if not usuario_tiene_permiso(self.request.user, "warehouse.view_receiving"):
            raise PermissionDenied("No tienes permiso para consultar inventario.")
        qs = StockEntry.objects.select_related(
            "product__provider", "receipt_line__receipt",
            "receipt_line__order_item__order__school", "posted_by",
        ).order_by("-created_at", "-pk")
        provider = self.request.query_params.get("provider")
        if provider:
            if not provider.isdecimal():
                raise ValidationError({"provider": "Editorial no válida."})
            qs = qs.filter(product__provider_id=int(provider))
        return qs

    @action(detail=False, methods=["post"], url_path="registrar-entrada")
    def post_receipt(self, request):
        raw = request.data.get("receipt_id")
        if isinstance(raw, bool) or not str(raw or "").isdecimal():
            raise ValidationError({"receipt_id": "Selecciona una recepción válida."})
        try:
            result = registrar_entrada_recepcion(
                actor=request.user, receipt_id=int(raw),
            )
        except GoodsReceipt.DoesNotExist:
            raise ValidationError({"receipt_id": "La recepción no existe."})
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response({
            **result,
            "message": ("Ingreso registrado en inventario." if result["new_entries"]
                        else "Esta recepción ya estaba ingresada; no se duplicaron unidades."),
        })

    @staticmethod
    def _item(entry, net_available=None):
        receipt_line = entry.receipt_line
        order_item = receipt_line.order_item
        return {
            "id": entry.pk,
            "product_id": entry.product_id,
            "product": entry.product.name,
            "editorial": entry.product.provider.name,
            "receipt_id": receipt_line.receipt_id,
            "guide": receipt_line.receipt.document_number,
            "order_id": order_item.order_id,
            "school_id": order_item.order.school_id,
            "school": order_item.order.school_name_snapshot or (
                order_item.order.school.name if order_item.order.school_id else "Pedido independiente"
            ),
            "available": entry.quantity_available,
            "net_available": net_available if net_available is not None else entry.quantity_available,
            "nonconforming": entry.quantity_quarantined,
            "extra_included": entry.quantity_extra,
            "on_order": entry.quantity_available - entry.quantity_extra,
            "physical": entry.quantity_available + entry.quantity_quarantined,
            "unit_cost": str(entry.unit_cost_snapshot) if entry.unit_cost_snapshot is not None else None,
            "entry_value": str(entry.quantity_available * entry.unit_cost_snapshot) if entry.unit_cost_snapshot is not None else None,
            "order_value_reference": str((entry.quantity_available - entry.quantity_extra) * entry.unit_cost_snapshot) if entry.unit_cost_snapshot is not None else None,
            "extra_value_reference": str(entry.quantity_extra * entry.unit_cost_snapshot) if entry.unit_cost_snapshot is not None else None,
            "created_at": entry.created_at,
        }

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        entries = list(page if page is not None else qs)
        movement_totals = {
            row["source_entry_id"]: row["total"]
            for row in StockMovement.objects.filter(
                source_entry_id__in=[entry.pk for entry in entries],
            ).values("source_entry_id").annotate(total=Sum("quantity_delta"))
        }
        data = [
            self._item(entry, entry.quantity_available + movement_totals.get(entry.pk, 0))
            for entry in entries
        ]
        return self.get_paginated_response(data) if page is not None else Response(data)

    def retrieve(self, request, *args, **kwargs):
        entry = self.get_object()
        return Response(self._item(entry, saldo_entrada(entry)))

    @action(detail=False, methods=["get"], url_path="entradas-disponibles")
    def eligible_courtesy_entries(self, request):
        """Busqueda paginada por lote y colegio; no limita cortesías a 20 ingresos recientes."""
        query = request.query_params.get("q", "").strip()
        if len(query) > 100:
            raise ValidationError({"q": "La búsqueda es demasiado larga."})
        balance_changes = (
            StockMovement.objects.filter(source_entry_id=OuterRef("pk"))
            .values("source_entry_id")
            .annotate(delta=Sum("quantity_delta"))
            .values("delta")[:1]
        )
        qs = self.get_queryset().filter(
            receipt_line__order_item__order__school__isnull=False,
        ).annotate(
            net_available=F("quantity_available") + Coalesce(Subquery(balance_changes), Value(0)),
        ).filter(net_available__gt=0)
        if query:
            qs = qs.filter(
                Q(product__name__icontains=query)
                | Q(receipt_line__order_item__order__school__name__icontains=query)
                | Q(receipt_line__receipt__document_number__icontains=query)
            )
        qs = qs.order_by("product__name", "pk")
        page = self.paginate_queryset(qs)
        rows = [self._item(entry, entry.net_available) for entry in (
            page if page is not None else qs[:20]
        )]
        return self.get_paginated_response(rows) if page is not None else Response(rows)

    @action(detail=False, methods=["post"], url_path="cortesias")
    def create_courtesy(self, request):
        serializer = CourtesyInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item, created = registrar_cortesia(actor=request.user, **serializer.validated_data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response({
            "id": item.pk,
            "stock_entry_id": item.source_entry_id,
            "school_id": item.school_id,
            "quantity": -item.quantity_delta,
            "recipient_name": item.recipient_name,
            "recipient_role": item.recipient_role,
            "entry_balance": saldo_entrada(item.source_entry),
            "message": "Cortesía registrada y stock actualizado." if created else "Esta cortesía ya estaba registrada.",
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="salidas")
    def outflows(self, request):
        qs = StockMovement.objects.filter(source_entry__in=self.get_queryset()).select_related(
            "source_entry__product", "school", "created_by", "source_entry__receipt_line__receipt",
        ).order_by("-created_at", "-pk")[:100]
        return Response([{
            "id": move.pk,
            "type": move.kind,
            "stock_entry_id": move.source_entry_id,
            "product": move.source_entry.product.name,
            "school": move.school.name,
            "guide": move.source_entry.receipt_line.receipt.document_number,
            "quantity": -move.quantity_delta,
            "recipient_name": move.recipient_name,
            "recipient_role": move.recipient_role,
            "notes": move.notes,
            "cost_unit": str(move.unit_cost_snapshot) if move.unit_cost_snapshot is not None else None,
            "cost_reference": str(-move.quantity_delta * move.unit_cost_snapshot) if move.unit_cost_snapshot is not None else None,
            "created_by": move.created_by_id,
            "created_at": move.created_at,
        } for move in qs])

    @action(detail=False, methods=["get"], url_path="resumen")
    def inventory_summary(self, request):
        """Saldo neto actual, separado del histórico de entradas y cuentas por pagar."""
        qs = self.get_queryset()
        totals = qs.aggregate(
            conforming=Sum("quantity_available"),
            nonconforming=Sum("quantity_quarantined"),
            extra=Sum("quantity_extra"),
            value_reference=Sum(ExpressionWrapper(
                F("quantity_available") * F("unit_cost_snapshot"),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )),
            observed_value_reference=Sum(ExpressionWrapper(
                F("quantity_quarantined") * F("unit_cost_snapshot"),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )),
            unvalued_observed_units=Sum(Case(
                When(unit_cost_snapshot__isnull=True, then=F("quantity_quarantined")),
                default=Value(0), output_field=IntegerField(),
            )),
            unvalued_units=Sum(Case(
                When(unit_cost_snapshot__isnull=True, then=F("quantity_available")),
                default=Value(0), output_field=IntegerField(),
            )),
        )
        movements = StockMovement.objects.filter(source_entry__in=qs).aggregate(
            delta=Sum("quantity_delta"),
            value_delta=Sum(ExpressionWrapper(
                F("quantity_delta") * F("unit_cost_snapshot"),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )),
            unvalued_delta=Sum(Case(
                When(unit_cost_snapshot__isnull=True, then=F("quantity_delta")),
                default=Value(0), output_field=IntegerField(),
            )),
        )
        from decimal import Decimal
        conforming = (totals["conforming"] or 0) + (movements["delta"] or 0)
        nonconforming = totals["nonconforming"] or 0
        unvalued_units = (totals["unvalued_units"] or 0) + (movements["unvalued_delta"] or 0)
        value = (
            (totals["value_reference"] or Decimal("0")) +
            (movements["value_delta"] or Decimal("0"))
        )
        observed_value = totals["observed_value_reference"] or Decimal("0")
        unvalued_observed_units = totals["unvalued_observed_units"] or 0
        return Response({
            "physical": conforming + nonconforming,
            "conforming": conforming,
            "nonconforming": nonconforming,
            "extra_included": totals["extra"] or 0,
            "gross_conforming_received": totals["conforming"] or 0,
            "outflows": -(movements["delta"] or 0),
            "value_reference": str(value) if totals["value_reference"] is not None else None,
            "observed_value_reference": str(observed_value),
            "physical_value_reference": str(value + observed_value),
            "unvalued_observed_units": unvalued_observed_units,
            "physical_valuation_complete": (
                unvalued_units + unvalued_observed_units == 0
            ),
            "unvalued_units": unvalued_units,
            "valuation_complete": unvalued_units == 0,
            "note": "Saldo neto actual tras cortesías. Adicionales históricos incluidos; no representa deuda a editorial.",
        })

    @action(detail=False, methods=["get"], url_path="resumen-por-editorial")
    def summary_by_editorial(self, request):
        """Valorización por editorial, basada en costos históricos y movimientos."""
        return Response(valorizar_por_editorial(self.get_queryset()))

    @action(detail=False, methods=["get"], url_path="existencias")
    def totals(self, request):
        qs = self.get_queryset()
        grouped = qs.values("product_id", "product__name", "product__provider__name").annotate(
            available=Sum("quantity_available"),
            nonconforming=Sum("quantity_quarantined"),
            extra_included=Sum("quantity_extra"),
            value_reference=Sum(ExpressionWrapper(
                F("quantity_available") * F("unit_cost_snapshot"),
                output_field=DecimalField(max_digits=20, decimal_places=2),
            )),
            unvalued_units=Sum(Case(
                When(unit_cost_snapshot__isnull=True, then=F("quantity_available")),
                default=Value(0), output_field=IntegerField(),
            )),
        ).order_by("product__name", "product_id")
        outflows = {
            move["source_entry__product_id"]: move
            for move in StockMovement.objects.filter(source_entry__in=qs).values(
                "source_entry__product_id"
            ).annotate(
                delta=Sum("quantity_delta"),
                value_delta=Sum(ExpressionWrapper(
                    F("quantity_delta") * F("unit_cost_snapshot"),
                    output_field=DecimalField(max_digits=20, decimal_places=2),
                )),
                unvalued_delta=Sum(Case(
                    When(unit_cost_snapshot__isnull=True, then=F("quantity_delta")),
                    default=Value(0), output_field=IntegerField(),
                )),
            )
        }
        from decimal import Decimal
        result = []
        for row in grouped:
            out = outflows.get(row["product_id"], {})
            available = row["available"] + (out.get("delta") or 0)
            value = (row["value_reference"] or Decimal("0")) + (
                out.get("value_delta") or Decimal("0")
            )
            result.append({
                "product_id": row["product_id"],
                "product": row["product__name"],
                "editorial": row["product__provider__name"],
                "available": available,
                "gross_conforming_received": row["available"],
                "nonconforming": row["nonconforming"],
                "extra_included": row["extra_included"],
                "physical": available + row["nonconforming"],
                "value_reference": str(value) if row["value_reference"] is not None else None,
                "unvalued_units": row["unvalued_units"] + (out.get("unvalued_delta") or 0),
            })
        return Response(result)
