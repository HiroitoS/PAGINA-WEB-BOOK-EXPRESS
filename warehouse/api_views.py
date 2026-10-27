from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.db import IntegrityError
from django.db.models import Q, Sum, F, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from catalog.models import Provider
from purchasing.models import PurchaseOrder, PurchaseOrderItem
from warehouse.api_serializers import CreateReceiptSerializer, GoodsReceiptSerializer
from warehouse.models import GoodsReceipt, ReceivingIncident, StockEntry
from warehouse.inventory import registrar_entrada_recepcion
from warehouse.receiving import (
    actualizar_borrador_recepcion, crear_borrador_recepcion,
    saldos_pedido, seguimiento_recepcion, validar_recepcion,
)


class GoodsReceiptViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = GoodsReceiptSerializer

    def get_queryset(self):
        if not usuario_tiene_permiso(self.request.user, "warehouse.view_receiving"):
            raise PermissionDenied("No tienes permiso para consultar recepciones.")
        queryset = GoodsReceipt.objects.select_related(
            "provider", "created_by", "validated_by",
        ).prefetch_related("lines__order_item__order", "events__actor").order_by("-received_on", "-pk")
        raw = self.request.query_params.get("provider")
        if raw:
            if not raw.isdecimal():
                raise ValidationError({"provider": "Identificador no válido."})
            queryset = queryset.filter(provider_id=int(raw))
        return queryset

    @action(detail=False, methods=["get"], url_path="pedidos-pendientes")
    def pending_orders(self, request):
        if not usuario_tiene_permiso(request.user, "warehouse.view_receiving"):
            raise PermissionDenied("No tienes permiso para consultar recepciones.")
        queryset = PurchaseOrder.objects.filter(
            status__in=[
                PurchaseOrder.Status.SENT,
                PurchaseOrder.Status.PARTIALLY_RECEIVED,
            ],
        ).order_by("provider_name_snapshot", "school_name_snapshot", "pk")
        provider = request.query_params.get("provider", "").strip()
        if provider:
            if not provider.isdecimal():
                raise ValidationError({"provider": "Editorial no válida."})
            queryset = queryset.filter(provider_id=int(provider))
        page = self.paginate_queryset(queryset)
        orders = list(page if page is not None else queryset[:20])
        ids = [order.pk for order in orders]
        lines = PurchaseOrderItem.objects.filter(order_id__in=ids).annotate(
            accepted=Coalesce(
                Sum(
                    "receipt_lines__quantity_accepted",
                    filter=Q(receipt_lines__receipt__status=GoodsReceipt.Status.VALIDATED),
                ), 0,
            ),
        ).order_by("pk")
        items_by_order = {}
        summary_by_order = {}
        for line in lines:
            pending = max(0, line.quantity_ordered - line.accepted)
            summary = summary_by_order.setdefault(
                line.order_id, {"solicitadas": 0, "aceptadas": 0, "pendientes": 0},
            )
            summary["solicitadas"] += line.quantity_ordered
            summary["aceptadas"] += line.accepted
            summary["pendientes"] += pending
            if pending:
                items_by_order.setdefault(line.order_id, []).append({
                    "item_id": line.pk,
                    "producto": line.product_name_snapshot,
                    "codigo": line.product_code_snapshot,
                    "solicitadas": line.quantity_ordered,
                    "aceptadas": line.accepted,
                    "pendientes": pending,
                })
        result = [
            {
                "id": order.pk,
                "editorial_id": order.provider_id,
                "editorial": order.provider_name_snapshot,
                "colegio": order.school_name_snapshot or "Pedido independiente",
                "campania": order.campaign_name_snapshot,
                "referencia": f"BE-OC-{order.pk:06d}",
                "productos": items_by_order.get(order.pk, []),
                "resumen": summary_by_order.get(order.pk, {}),
            }
            for order in orders if items_by_order.get(order.pk)
        ]
        if page is not None:
            return self.get_paginated_response(result)
        return Response(result)

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
        except IntegrityError as exc:
            raise ValidationError({"detail": "El documento ya fue registrado para esta editorial o sus datos están duplicados."}) from exc
        return Response(
            GoodsReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="actualizar")
    def update_draft(self, request, pk=None):
        if not usuario_tiene_permiso(request.user, "warehouse.manage_receiving"):
            raise PermissionDenied("No tienes permiso para modificar recepciones.")
        self.get_object()
        serializer = CreateReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            receipt = actualizar_borrador_recepcion(
                actor=request.user, receipt_id=pk, **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        except IntegrityError as exc:
            raise ValidationError({"detail": "El documento ya fue registrado para esta editorial o sus datos están duplicados."}) from exc
        return Response(GoodsReceiptSerializer(receipt).data)

    @action(detail=True, methods=["post"], url_path="validar")
    def validate_draft(self, request, pk=None):
        if not usuario_tiene_permiso(request.user, "warehouse.validate_receiving"):
            raise PermissionDenied("No tienes permiso para validar recepciones.")
        self.get_object()
        try:
            receipt = validar_recepcion(actor=request.user, receipt_id=pk)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages}) from exc
        except IntegrityError as exc:
            raise ValidationError({"detail": "El documento ya fue registrado para esta editorial o sus datos están duplicados."}) from exc
        return Response(GoodsReceiptSerializer(receipt).data)

    @action(detail=True, methods=["get"], url_path="seguimiento")
    def tracking(self, request, pk=None):
        recepcion = self.get_object()
        return Response(seguimiento_recepcion(actor=request.user, receipt=recepcion))

    @action(detail=False, methods=["get"], url_path="saldos")
    def order_balances(self, request):
        raw = request.query_params.get("pedido", "").strip()
        if not raw.isdecimal() or int(raw) < 1:
            raise ValidationError({"pedido": "Indica el ID del pedido."})
        try:
            return Response(saldos_pedido(actor=request.user, order_id=int(raw)))
        except PurchaseOrder.DoesNotExist as exc:
            raise Http404("Pedido no encontrado.") from exc


class ReceivingIncidentViewSet(viewsets.ReadOnlyModelViewSet):
    """Consulta interna de incidencias; su resolución tendrá un flujo propio."""

    def get_queryset(self):
        if not usuario_tiene_permiso(self.request.user, "warehouse.view_receiving"):
            raise PermissionDenied("No tienes permiso para consultar incidencias.")
        return ReceivingIncident.objects.select_related(
            "receipt_line__receipt__provider",
            "receipt_line__order_item__order",
            "detected_by",
        ).order_by("-created_at", "-pk")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        records = page if page is not None else queryset
        data = [self._as_dict(item) for item in records]
        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        return Response(self._as_dict(self.get_object()))

    @action(detail=False, methods=["get"], url_path="alertas-liquidacion")
    def settlement_alerts(self, request):
        """Control interno previo a liquidar; no crea ni aprueba pagos."""
        queryset = self.get_queryset().filter(status=ReceivingIncident.Status.OPEN)
        provider = request.query_params.get("provider")
        if provider:
            if not provider.isdecimal():
                raise ValidationError({"provider": "Editorial no válida."})
            queryset = queryset.filter(receipt_line__receipt__provider_id=int(provider))
        records = list(queryset)
        totals = {
            "shortage": sum(x.quantity for x in records if x.kind == ReceivingIncident.Kind.SHORTAGE),
            "nonconforming": sum(x.quantity for x in records if x.kind == ReceivingIncident.Kind.NONCONFORMING),
        }
        return Response({
            "requires_review": bool(records),
            "message": (
                "Hay faltantes o productos no conformes sin resolver. "
                "Revisa las incidencias antes de liquidar a la editorial."
                if records else "No hay incidencias abiertas registradas en este control."
            ),
            "open_incidents": len(records),
            "quantities": totals,
            "items": [self._as_dict(x) for x in records],
            "scope": "Incidencias registradas; no sustituye conciliación de facturas, pagos ni saldos de pedidos.",
        })

    @staticmethod
    def _as_dict(item):
        line = item.receipt_line
        order_item = line.order_item
        receipt = line.receipt
        return {
            "id": item.pk,
            "type": item.kind,
            "type_label": item.get_kind_display(),
            "status": item.status,
            "quantity": item.quantity,
            "receipt_id": receipt.pk,
            "document_number": receipt.document_number,
            "editorial": receipt.provider.name,
            "order_id": order_item.order_id,
            "school": order_item.order.school_name_snapshot or "Pedido independiente",
            "product": order_item.product_name_snapshot,
            "detected_by": item.detected_by.get_username(),
            "created_at": item.created_at,
        }


class InventoryEntryViewSet(viewsets.ReadOnlyModelViewSet):
    """Ingresos confirmados: una línea de recepción tiene una sola entrada."""

    def get_queryset(self):
        if not usuario_tiene_permiso(self.request.user, "warehouse.view_receiving"):
            raise PermissionDenied("No tienes permiso para consultar inventario.")
        qs = StockEntry.objects.select_related(
            "product__provider", "receipt_line__receipt",
            "receipt_line__order_item__order", "posted_by",
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
    def _item(entry):
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
            "school": order_item.order.school_name_snapshot or "Pedido independiente",
            "available": entry.quantity_available,
            "nonconforming": entry.quantity_quarantined,
            "extra_included": entry.quantity_extra,
            "physical": entry.quantity_available + entry.quantity_quarantined,
            "unit_cost": str(entry.unit_cost_snapshot) if entry.unit_cost_snapshot is not None else None,
            "entry_value": str(entry.quantity_available * entry.unit_cost_snapshot) if entry.unit_cost_snapshot is not None else None,
            "created_at": entry.created_at,
        }

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        data = [self._item(item) for item in (page if page is not None else qs)]
        return self.get_paginated_response(data) if page is not None else Response(data)

    def retrieve(self, request, *args, **kwargs):
        return Response(self._item(self.get_object()))

    @action(detail=False, methods=["get"], url_path="existencias")
    def totals(self, request):
        qs = self.get_queryset()
        grouped = qs.values("product_id", "product__name", "product__provider__name").annotate(
            available=Sum("quantity_available"),
            nonconforming=Sum("quantity_quarantined"),
            extra_included=Sum("quantity_extra"),
        ).order_by("product__name", "product_id")
        return Response([
            {
                "product_id": row["product_id"],
                "product": row["product__name"],
                "editorial": row["product__provider__name"],
                "available": row["available"],
                "nonconforming": row["nonconforming"],
                "extra_included": row["extra_included"],
                "physical": row["available"] + row["nonconforming"],
            }
            for row in grouped
        ])
