"""Registro preliminar de factura editorial; concilia documentación sin tocar stock/CxP."""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import usuario_tiene_permiso
from catalog.models import Provider
from purchasing.models import (
    PurchaseOrder, PurchaseOrderItem, SupplierInvoice,
    SupplierInvoiceEvent, SupplierInvoiceLine,
)
from warehouse.models import GoodsReceipt, GoodsReceiptLine


class SupplierInvoiceItemInput(serializers.Serializer):
    order_item_id = serializers.IntegerField(min_value=1)
    quantity_billed = serializers.IntegerField(min_value=1, max_value=1000000)
    unit_cost_billed = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00"),
    )


class SupplierInvoiceInput(serializers.Serializer):
    provider_id = serializers.PrimaryKeyRelatedField(
        source="provider", queryset=Provider.objects.all(),
    )
    document_number = serializers.CharField(max_length=80, trim_whitespace=True)
    issued_on = serializers.DateField()
    total_document = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.00"),
    )
    notes = serializers.CharField(max_length=1000, allow_blank=True, required=False)
    items = SupplierInvoiceItemInput(many=True, allow_empty=False)

    def validate_document_number(self, value):
        number = value.strip().upper()
        if not number:
            raise serializers.ValidationError("Indica la serie y número de la factura.")
        return number

    def validate_items(self, rows):
        if len(rows) > 150:
            raise serializers.ValidationError("Selecciona como máximo 150 líneas por factura.")
        identifiers = [row["order_item_id"] for row in rows]
        if len(identifiers) != len(set(identifiers)):
            raise serializers.ValidationError("No repitas el mismo producto del pedido en una factura.")
        return rows

    def validate(self, attrs):
        provider = attrs["provider"]
        if (
            SupplierInvoice.objects.filter(
                provider=provider,
                document_number__iexact=attrs["document_number"],
            ).exclude(pk=self.instance.pk if self.instance else None).exists()
        ):
            raise serializers.ValidationError({
                "document_number": "Esa factura ya está registrada para la editorial.",
            })
        item_ids = [row["order_item_id"] for row in attrs["items"]]
        found = {
            item.pk: item
            for item in PurchaseOrderItem.objects.select_related("order").filter(
                pk__in=item_ids,
            )
        }
        if len(found) != len(item_ids):
            raise serializers.ValidationError({
                "items": "Hay productos de pedidos que no existen. Actualiza la selección.",
            })
        valid_states = {
            PurchaseOrder.Status.APPROVED,
            PurchaseOrder.Status.SENT,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
            PurchaseOrder.Status.RECEIVED,
            PurchaseOrder.Status.CLOSED_PARTIAL,
        }
        for item in found.values():
            if item.order.provider_id != provider.pk:
                raise serializers.ValidationError({
                    "items": "Todos los pedidos de la factura deben ser de la misma editorial.",
                })
            if item.order.status not in valid_states:
                raise serializers.ValidationError({
                    "items": "Selecciona pedidos aprobados que no estén anulados.",
                })
            if item.currency != "PEN":
                raise serializers.ValidationError({
                    "items": "Este registro preliminar admite pedidos en soles.",
                })
        attrs["resolved_items"] = found
        return attrs


def _invoice_snapshot(record):
    return {
        "provider": record.provider_id,
        "document_number": record.document_number,
        "issued_on": record.issued_on.isoformat(),
        "total_document": str(record.total_document),
        "notes": record.notes,
        "items": [
            {
                "order_item_id": line.order_item_id,
                "quantity_billed": line.quantity_billed,
                "unit_cost_billed": str(line.unit_cost_billed),
                "expected_unit_cost_snapshot": str(line.expected_unit_cost_snapshot),
            }
            for line in record.items.all()
        ],
    }


def _serialize(record):
    """Desglose de cantidades pedidas, recibidas y facturadas por línea."""
    lines = list(record.items.all())
    keys = [line.order_item_id for line in lines]
    physical = {
        row["order_item_id"]: row["total"] or 0
        for row in GoodsReceiptLine.objects.filter(
            order_item_id__in=keys,
            receipt__status=GoodsReceipt.Status.VALIDATED,
        ).values("order_item_id").annotate(total=Sum("quantity_accepted"))
    }
    other_billed = {
        row["order_item_id"]: row["total"] or 0
        for row in SupplierInvoiceLine.objects.filter(
            order_item_id__in=keys,
        ).exclude(invoice=record).values("order_item_id").annotate(
            total=Sum("quantity_billed"),
        )
    }
    detail = []
    for line in lines:
        item = line.order_item
        physical_qty = physical.get(line.order_item_id, 0)
        previously_billed = other_billed.get(line.order_item_id, 0)
        detail.append({
            "id": line.pk,
            "order_item_id": item.pk,
            "order_id": item.order_id,
            "product_name": item.product_name_snapshot,
            "product_code": item.product_code_snapshot,
            "quantity_ordered": item.quantity_ordered,
            "quantity_received": physical_qty,
            "quantity_billed": line.quantity_billed,
            "quantity_other_invoices": previously_billed,
            "expected_unit_cost": str(line.expected_unit_cost_snapshot),
            "unit_cost_billed": str(line.unit_cost_billed),
            "cost_difference_unit": str(
                line.unit_cost_billed - line.expected_unit_cost_snapshot
            ),
            "subtotal_billed": str(line.unit_cost_billed * line.quantity_billed),
            "review_required": (
                physical_qty < line.quantity_billed + previously_billed
                or line.unit_cost_billed != line.expected_unit_cost_snapshot
                or line.quantity_billed + previously_billed > item.quantity_ordered
            ),
        })
    return {
        "id": record.pk,
        "reference": str(record.reference),
        "provider_id": record.provider_id,
        "provider_name": record.provider.name,
        "document_number": record.document_number,
        "issued_on": record.issued_on.isoformat(),
        "total_document": str(record.total_document),
        "currency": record.currency,
        "status": record.status,
        "notes": record.notes,
        "items": detail,
        "created_by": record.created_by.get_username(),
        "created_at": record.created_at,
        "events": [
            {
                "action": event.action,
                "actor": event.actor.get_username(),
                "created_at": event.created_at,
                "detail": event.detail,
            }
            for event in record.events.all()
        ],
    }


class SupplierInvoiceViewSet(viewsets.ViewSet):
    """La factura se registra una vez; no genera ni duplica entradas físicas."""

    def _require(self, request, permission):
        if not usuario_tiene_permiso(request.user, f"purchasing.{permission}"):
            raise PermissionDenied("No tienes autorización para realizar esta operación.")

    def _base(self):
        return SupplierInvoice.objects.select_related(
            "provider", "created_by",
        ).prefetch_related(
            "items__order_item__order", "events__actor",
        )

    def list(self, request):
        self._require(request, "view_supplier_invoices")
        records = self._base()
        provider = request.query_params.get("provider")
        if provider is not None:
            if not provider.isdecimal():
                raise ValidationError({"provider": "Selecciona una editorial válida."})
            records = records.filter(provider_id=int(provider))
        return Response([_serialize(record) for record in records[:100]])

    def retrieve(self, request, pk=None):
        self._require(request, "view_supplier_invoices")
        return Response(_serialize(get_object_or_404(self._base(), pk=pk)))

    @action(detail=False, methods=["get"], url_path="pedidos-disponibles")
    def available_orders(self, request):
        self._require(request, "view_supplier_invoices")
        provider = request.query_params.get("provider")
        if not provider or not provider.isdecimal():
            raise ValidationError({"provider": "Selecciona una editorial."})
        orders = PurchaseOrder.objects.filter(
            provider_id=int(provider),
            status__in=[
                PurchaseOrder.Status.APPROVED,
                PurchaseOrder.Status.SENT,
                PurchaseOrder.Status.PARTIALLY_RECEIVED,
                PurchaseOrder.Status.RECEIVED,
                PurchaseOrder.Status.CLOSED_PARTIAL,
            ],
        ).prefetch_related("items").order_by("-pk")[:100]
        return Response([
            {
                "id": order.pk,
                "school": order.school_name_snapshot,
                "status": order.status,
                "items": [
                    {
                        "id": line.pk,
                        "product_name": line.product_name_snapshot,
                        "product_code": line.product_code_snapshot,
                        "quantity_ordered": line.quantity_ordered,
                        "expected_unit_cost": str(line.unit_supplier_cost),
                    }
                    for line in order.items.all()
                ],
            }
            for order in orders
        ])

    def _save_items(self, record, rows, resolved):
        SupplierInvoiceLine.objects.bulk_create([
            SupplierInvoiceLine(
                invoice=record, order_item=resolved[row["order_item_id"]],
                quantity_billed=row["quantity_billed"],
                unit_cost_billed=row["unit_cost_billed"],
                expected_unit_cost_snapshot=resolved[row["order_item_id"]].unit_supplier_cost,
            )
            for row in rows
        ])

    def create(self, request):
        self._require(request, "manage_supplier_invoices")
        serializer = SupplierInvoiceInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        resolved = values.pop("resolved_items")
        items = values.pop("items")
        try:
            with transaction.atomic():
                record = SupplierInvoice.objects.create(
                    **values, created_by=request.user,
                )
                self._save_items(record, items, resolved)
                SupplierInvoiceEvent.objects.create(
                    invoice=record, actor=request.user,
                    action="created", detail={"new": _invoice_snapshot(record)},
                )
        except IntegrityError:
            raise ValidationError({
                "document_number": "Esa factura ya está registrada para esta editorial.",
            }) from None
        return Response(
            _serialize(get_object_or_404(self._base(), pk=record.pk)),
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, pk=None):
        self._require(request, "manage_supplier_invoices")
        # Se reemplaza TODO el borrador: se conserva el antes/después auditado.
        with transaction.atomic():
            record = get_object_or_404(
                SupplierInvoice.objects.select_for_update(), pk=pk,
            )
            serializer = SupplierInvoiceInput(
                instance=record, data=request.data,
            )
            serializer.is_valid(raise_exception=True)
            if record.status != SupplierInvoice.Status.DRAFT:
                raise ValidationError({
                    "detail": "Esta factura ya no puede editarse. Solicita una corrección autorizada.",
                })
            values = dict(serializer.validated_data)
            resolved = values.pop("resolved_items")
            items = values.pop("items")
            if values["provider"].pk != record.provider_id:
                raise ValidationError({
                    "provider_id": "No puedes cambiar la editorial de una factura existente.",
                })
            note = str(request.data.get("change_reason", "")).strip()
            if len(note) < 8 or len(note) > 500:
                raise ValidationError({
                    "change_reason": "Explica la corrección en al menos ocho caracteres.",
                })
            previous = _invoice_snapshot(record)
            record.document_number = values["document_number"]
            record.issued_on = values["issued_on"]
            record.total_document = values["total_document"]
            record.notes = values.get("notes", "")
            try:
                record.save(update_fields=[
                    "document_number", "issued_on", "total_document",
                    "notes", "updated_at",
                ])
                record.items.all().delete()
                self._save_items(record, items, resolved)
            except IntegrityError:
                raise ValidationError({
                    "document_number": "Esa factura ya está registrada para esta editorial.",
                }) from None
            SupplierInvoiceEvent.objects.create(
                invoice=record, actor=request.user, action="corrected",
                detail={
                    "reason": note,
                    "previous": previous,
                    "current": _invoice_snapshot(record),
                },
            )
        return Response(_serialize(get_object_or_404(self._base(), pk=pk)))
