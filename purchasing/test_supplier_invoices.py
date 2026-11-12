"""Conciliación preliminar de facturas: sin entradas duplicadas ni CxP ficticia."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from purchasing.models import (
    SupplierInvoice, SupplierInvoiceEvent, SupplierInvoiceLine,
    PurchaseOrderItem,
)
from purchasing.order_creation import create_orders_from_adoption
from purchasing.test_integration import GeneracionPedidosAdopcionTests
from warehouse.models import GoodsReceipt, GoodsReceiptLine, StockEntry


class SupplierInvoiceAPITests(GeneracionPedidosAdopcionTests):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.orders = create_orders_from_adoption(
            adoption_id=self.adopcion.pk, actor=self.user,
        )
        for order in self.orders:
            order.status = order.Status.SENT
            order.save(update_fields=["status"])
        self.order = next(
            order for order in self.orders
            if "Santillana" in order.provider_name_snapshot
        )
        self.line = PurchaseOrderItem.objects.get(order=self.order)
        self.base = reverse("factura-editorial-list")

    def payload(self, **overrides):
        result = {
            "provider_id": self.order.provider_id,
            "document_number": "F001-1234",
            "issued_on": date(2027, 3, 10).isoformat(),
            "total_document": "1000.00",
            "notes": "Documento recibido por Administración",
            "items": [{
                "order_item_id": self.line.pk,
                "quantity_billed": 10,
                "unit_cost_billed": "76.00",
            }],
        }
        result.update(overrides)
        return result

    def test_registro_muestra_diferencia_y_no_crea_stock(self):
        before = (GoodsReceipt.objects.count(), StockEntry.objects.count())
        created = self.client.post(self.base, self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["status"], "draft")
        self.assertEqual(created.data["items"][0]["quantity_ordered"], 100)
        self.assertEqual(created.data["items"][0]["quantity_received"], 0)
        self.assertEqual(created.data["items"][0]["quantity_billed"], 10)
        self.assertEqual(created.data["items"][0]["expected_unit_cost"], "75.00")
        self.assertEqual(created.data["items"][0]["cost_difference_unit"], "1.00")
        self.assertTrue(created.data["items"][0]["review_required"])
        self.assertEqual(SupplierInvoiceEvent.objects.count(), 1)
        self.assertEqual((GoodsReceipt.objects.count(), StockEntry.objects.count()), before)
        self.assertEqual(self.client.get(self.base).status_code, 200)

    def test_misma_factura_no_se_duplica_por_cambio_mayusculas(self):
        result = self.client.post(self.base, self.payload(), format="json")
        self.assertEqual(result.status_code, 201, result.data)
        second = self.client.post(
            self.base,
            self.payload(document_number=" f001-1234 "),
            format="json",
        )
        self.assertEqual(second.status_code, 400)
        self.assertEqual(SupplierInvoice.objects.count(), 1)

    def test_una_factura_admite_pedidos_distintos_de_la_misma_editorial(self):
        # Dos líneas pueden pertenecer a pedidos de colegios diferentes.
        another_order = self.order
        from purchasing.models import PurchaseOrder, PurchaseOrderItem
        another_order = PurchaseOrder.objects.create(
            origin=PurchaseOrder.Origin.MANUAL,
            provider=self.order.provider,
            campaign=self.campania,
            status=PurchaseOrder.Status.SENT,
            provider_name_snapshot=self.order.provider_name_snapshot,
            campaign_name_snapshot=self.campania.name,
            created_by=self.user,
        )
        another = PurchaseOrderItem.objects.create(
            order=another_order,
            product=self.line.product,
            product_name_snapshot=self.line.product_name_snapshot,
            product_code_snapshot=self.line.product_code_snapshot,
            quantity_ordered=20,
            unit_supplier_cost=Decimal("75.00"),
        )
        items = [
            {"order_item_id": self.line.pk, "quantity_billed": 10, "unit_cost_billed": "75.00"},
            {"order_item_id": another.pk, "quantity_billed": 20, "unit_cost_billed": "75.00"},
        ]
        response = self.client.post(self.base, self.payload(items=items), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data["items"]), 2)
        self.assertEqual({row["order_id"] for row in response.data["items"]},
                         {self.order.pk, another_order.pk})

    def test_bloquea_mezclar_editoriales_repetir_lineas_y_pedidos_borrador(self):
        second = next(order for order in self.orders if order.pk != self.order.pk)
        line_other = PurchaseOrderItem.objects.get(order=second)
        checks = [
            self.payload(items=[
                {"order_item_id": self.line.pk, "quantity_billed": 10, "unit_cost_billed": "75.00"},
                {"order_item_id": line_other.pk, "quantity_billed": 1, "unit_cost_billed": "50.00"},
            ]),
            self.payload(items=[
                {"order_item_id": self.line.pk, "quantity_billed": 10, "unit_cost_billed": "75.00"},
                {"order_item_id": self.line.pk, "quantity_billed": 1, "unit_cost_billed": "75.00"},
            ]),
            self.payload(items=[{"order_item_id": self.line.pk,
                                 "quantity_billed": 0, "unit_cost_billed": "75.00"}]),
        ]
        for data in checks:
            with self.subTest(data=data):
                self.assertEqual(
                    self.client.post(self.base, data, format="json").status_code, 400,
                )
        self.order.status = self.order.Status.DRAFT
        self.order.save(update_fields=["status"])
        self.assertEqual(
            self.client.post(self.base, self.payload(), format="json").status_code,
            400,
        )
        self.assertFalse(SupplierInvoice.objects.exists())

    def test_correccion_guarda_antes_despues_motivo_y_no_cambia_recepcion(self):
        receipt = GoodsReceipt.objects.create(
            provider=self.order.provider,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number="T001-TEST",
            received_on=date(2027, 3, 10),
            status=GoodsReceipt.Status.VALIDATED,
            created_by=self.user, validated_by=self.user,
        )
        GoodsReceiptLine.objects.create(
            receipt=receipt, order_item=self.line,
            quantity_arrived=10, quantity_accepted=10, quantity_observed=0,
            quantity_extra=0, quantity_documented=10,
        )
        created = self.client.post(
            self.base, self.payload(), format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["items"][0]["quantity_received"], 10)
        pk = created.data["id"]
        url = reverse("factura-editorial-detail", args=[pk])
        bad = self.client.patch(url, self.payload(
            items=[{"order_item_id": self.line.pk, "quantity_billed": 10,
                    "unit_cost_billed": "75.00"}],
        ), format="json")
        self.assertEqual(bad.status_code, 400)
        changed = self.client.patch(url, {
            **self.payload(
                total_document="950.00",
                items=[{
                    "order_item_id": self.line.pk,
                    "quantity_billed": 10, "unit_cost_billed": "75.00",
                }],
            ),
            "change_reason": "Editorial corrigió su precio por escrito.",
        }, format="json")
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["items"][0]["cost_difference_unit"], "0.00")
        self.assertEqual(changed.data["items"][0]["quantity_received"], 10)
        self.assertEqual(SupplierInvoiceLine.objects.count(), 1)
        self.assertEqual(SupplierInvoiceEvent.objects.count(), 2)
        event = SupplierInvoiceEvent.objects.filter(action="corrected").get()
        self.assertEqual(event.detail["previous"]["items"][0]["unit_cost_billed"], "76.00")
        self.assertEqual(event.detail["current"]["items"][0]["unit_cost_billed"], "75.00")
        self.assertEqual(GoodsReceipt.objects.count(), 1)
        self.assertFalse(StockEntry.objects.exists())

    def test_nueva_factura_muestra_lineas_ya_facturadas(self):
        first = self.client.post(self.base, self.payload(
            items=[{"order_item_id": self.line.pk, "quantity_billed": 8,
                    "unit_cost_billed": "75.00"}],
        ), format="json")
        self.assertEqual(first.status_code, 201, first.data)
        next_invoice = self.client.post(
            self.base, self.payload(
                document_number="F001-1235",
                items=[{"order_item_id": self.line.pk, "quantity_billed": 6,
                        "unit_cost_billed": "75.00"}],
            ), format="json",
        )
        self.assertEqual(next_invoice.status_code, 201, next_invoice.data)
        self.assertEqual(next_invoice.data["items"][0]["quantity_other_invoices"], 8)
        self.assertTrue(next_invoice.data["items"][0]["review_required"])

    def test_usuario_sin_permiso_no_ve_facturas_y_delete_no_existe(self):
        viewer = get_user_model().objects.create_user(username="sin-facturas")
        self.client.force_authenticate(user=viewer)
        self.assertEqual(self.client.get(self.base).status_code, 403)
        self.assertEqual(
            self.client.post(self.base, self.payload(), format="json").status_code,
            403,
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.base, self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            self.client.delete(
                reverse("factura-editorial-detail", args=[response.data["id"]]),
            ).status_code, 405,
        )
