"""B3: reserva por lote, conteo y datos previos a GRE, sin duplicar inventario."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from purchasing.order_creation import create_orders_from_adoption
from purchasing.test_integration import GeneracionPedidosAdopcionTests
from warehouse.models import (
    DistributionOperation, DistributionStockReservation,
    DistributionTransportDraft, GoodsReceipt, StockEntry, StockTransfer,
    WarehouseLocation,
)
from warehouse.receiving import crear_borrador_recepcion, validar_recepcion
from warehouse.transfers import registrar_traslado


class DistributionPreparationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        GeneracionPedidosAdopcionTests.setUpTestData.__func__(cls)
        cls.main = WarehouseLocation.objects.create(
            code="B3-MAIN", name="Principal B3", kind=WarehouseLocation.Kind.MAIN,
        )
        cls.fair = WarehouseLocation.objects.create(
            code="B3-FAIR", name="Feria B3", kind=WarehouseLocation.Kind.FAIR,
        )
        cls.employee = get_user_model().objects.create_user(
            username="b3-restricted", password="dummy",
        )

    def setUp(self):
        self.orders = create_orders_from_adoption(
            adoption_id=self.adopcion.pk, actor=self.user,
        )
        for order in self.orders:
            order.status = order.Status.SENT
            order.sent_at = timezone.now()
            order.save(update_fields=["status", "sent_at", "updated_at"])
            item = order.items.first()
            receipt = crear_borrador_recepcion(
                actor=self.user, provider_id=order.provider_id,
                document_type=GoodsReceipt.DocumentType.GUIDE,
                document_number=f"T-B3-{order.pk}",
                received_on=timezone.localdate(),
                lines=[{
                    "order_item_id": item.pk,
                    "quantity_documented": item.quantity_ordered,
                    "quantity_arrived": item.quantity_ordered,
                    "quantity_accepted": item.quantity_ordered,
                    "quantity_observed": 0,
                }],
            )
            validar_recepcion(actor=self.user, receipt_id=receipt.pk)
        self.entries = list(StockEntry.objects.order_by("pk"))

    def api_client(self, actor=None):
        client = APIClient()
        client.force_authenticate(user=actor or self.user)
        return client

    def plan(self, quantities=(5, 5)):
        products = list(self.adopcion.items.order_by("pk"))
        response = self.api_client().post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            {
                "idempotency_key": str(uuid4()),
                "adoption_id": self.adopcion.pk,
                "mode": "fair",
                "source_id": self.main.pk,
                "destination_id": self.fair.pk,
                "operation_name": "Feria de prueba B3",
                "responsible_name": "Responsable de prueba",
                "items": [
                    {"product_id": item.product_id, "quantity": qty}
                    for item, qty in zip(products, quantities)
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def endpoint(self, op_id, action):
        return f"/api/admin/erp/almacen/operaciones-distribucion/{op_id}/{action}/"

    def test_reserva_no_traslada_y_reintento_no_duplica(self):
        op_id = self.plan()
        client = self.api_client()
        preview = client.get(self.endpoint(op_id, "preparacion"))
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["can_reserve"])
        self.assertEqual(len(preview.data["items"]), 2)
        self.assertEqual([r["shortage"] for r in preview.data["items"]], [0, 0])
        posted = client.post(self.endpoint(op_id, "reservar"), {}, format="json")
        self.assertEqual(posted.status_code, 201, posted.data)
        self.assertEqual(posted.data["status"], "reserved")
        self.assertEqual(
            sum(r["quantity"] for r in posted.data["reservations"]), 10,
        )
        duplicate = client.post(self.endpoint(op_id, "reservar"), {}, format="json")
        self.assertEqual(duplicate.status_code, 200, duplicate.data)
        self.assertEqual(DistributionStockReservation.objects.count(), 2)
        self.assertEqual(StockEntry.objects.count(), 2)
        self.assertEqual(StockTransfer.objects.count(), 0)
        self.assertEqual(
            self.api_client().patch(self.endpoint(op_id, "").rstrip("/") + "/", {
                "notes": "Cambiar ahora", "reason": "Ya se reservó",
            }, format="json").status_code, 400,
        )

    def test_reserva_bloquea_traslado_y_cortesia_sobre_cantidad_libre(self):
        op_id = self.plan()
        self.assertEqual(
            self.api_client().post(self.endpoint(op_id, "reservar"), {}, format="json").status_code,
            201,
        )
        reserved = DistributionStockReservation.objects.first()
        # Solo quedan saldo físico menos reserva en el almacén.
        with self.assertRaisesMessage(DjangoValidationError, "unidades libres"):
            registrar_traslado(
                actor=self.user, stock_entry_id=reserved.stock_entry_id,
                source_id=self.main.pk, destination_id=self.fair.pk,
                quantity=reserved.stock_entry.quantity_available,
                idempotency_key=uuid4(), entrega_confirmada=True,
            )
        remaining = reserved.stock_entry.quantity_available - reserved.quantity
        registrar_traslado(
            actor=self.user, stock_entry_id=reserved.stock_entry_id,
            source_id=self.main.pk, destination_id=self.fair.pk,
            quantity=remaining, idempotency_key=uuid4(), entrega_confirmada=True,
        )
        self.assertEqual(StockTransfer.objects.count(), 1)
        record = DistributionOperation.objects.get(pk=op_id)
        self.assertEqual(record.status, "reserved")

    def test_confirmar_conteo_real_no_permite_anulacion_sin_reversion(self):
        op_id = self.plan()
        client = self.api_client()
        saved = client.post(self.endpoint(op_id, "reservar"), {}, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        rows = saved.data["reservations"]
        bad = client.post(self.endpoint(op_id, "confirmar-preparacion"), {
            "counts": [
                {"reservation_id": row["id"], "counted": row["quantity"] - 1}
                for row in rows
            ],
        }, format="json")
        self.assertEqual(bad.status_code, 400, bad.data)
        self.assertEqual(
            DistributionOperation.objects.get(pk=op_id).status, "reserved",
        )
        good = client.post(self.endpoint(op_id, "confirmar-preparacion"), {
            "counts": [
                {"reservation_id": row["id"], "counted": row["quantity"]}
                for row in rows
            ],
        }, format="json")
        self.assertEqual(good.status_code, 200, good.data)
        self.assertEqual(good.data["status"], "prepared")
        self.assertEqual(StockTransfer.objects.count(), 0)
        cancelled = client.post(self.endpoint(op_id, "anular"), {
            "reason": "Operación de prueba cancelada antes de despacho.",
        }, format="json")
        self.assertEqual(cancelled.status_code, 400, cancelled.data)
        self.assertEqual(DistributionOperation.objects.get(pk=op_id).status, "prepared")
        self.assertEqual(DistributionStockReservation.objects.filter(status="active").count(), 2)
        self.assertEqual(StockTransfer.objects.count(), 0)
        self.assertEqual(
            DistributionOperation.objects.get(pk=op_id).events.filter(
                action__in=["stock_reserved", "prepared", "cancelled"],
            ).count(), 2,
        )

    def test_anulacion_de_entrega_solo_reservada_libera_lotes(self):
        op_id = self.plan()
        client = self.api_client()
        saved = client.post(self.endpoint(op_id, "reservar"), {}, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        canceled = client.post(self.endpoint(op_id, "anular"), {
            "reason": "La feria fue reprogramada y se libera la reserva.",
        }, format="json")
        self.assertEqual(canceled.status_code, 200, canceled.data)
        self.assertEqual(canceled.data["status"], "cancelled")
        self.assertFalse(DistributionStockReservation.objects.filter(status="active").exists())
        self.assertEqual(StockTransfer.objects.count(), 0)

    def test_faltante_despues_de_traslado_impide_reservar_sin_efectos(self):
        op_id = self.plan()
        entry = self.entries[0]
        registrar_traslado(
            actor=self.user, stock_entry_id=entry.pk,
            source_id=self.main.pk, destination_id=self.fair.pk,
            quantity=entry.quantity_available, idempotency_key=uuid4(),
            entrega_confirmada=True,
        )
        preview = self.api_client().get(self.endpoint(op_id, "preparacion"))
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["can_reserve"])
        response = self.api_client().post(self.endpoint(op_id, "reservar"), {}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(DistributionStockReservation.objects.exists())
        self.assertEqual(DistributionOperation.objects.get(pk=op_id).status, "planned")

    def test_documento_transporte_es_borrador_no_gre_aceptada(self):
        op_id = self.plan()
        client = self.api_client()
        url = self.endpoint(op_id, "documento-traslado")
        initial = client.get(url)
        self.assertEqual(initial.status_code, 200, initial.data)
        self.assertFalse(initial.data["sunat_issued"])
        self.assertFalse(initial.data["data_complete_for_review"])
        invalid = client.put(url, {"issuer_ruc": "123"}, format="json")
        self.assertEqual(invalid.status_code, 400, invalid.data)
        save = client.put(url, {
            "issuer_ruc": "20601658811", "transport_mode": "private",
            "transfer_reason": "consignment",
            "departure_address": "Dirección de prueba de partida",
            "destination_address": "Dirección de prueba de llegada",
            "destination_name": "Responsable de prueba",
            "destination_id_number": "87654321",
            "departure_on": "2027-02-01",
            "license_plate": "W1A123",
            "driver_document": "12345678",
            "driver_license": "L12345678",
            "gross_weight_kg": "2.000",
        }, format="json")
        self.assertEqual(save.status_code, 200, save.data)
        self.assertTrue(save.data["data_complete_for_review"])
        self.assertFalse(save.data["sunat_issued"])
        self.assertFalse(save.data["sunat_accepted"])
        self.assertEqual(DistributionTransportDraft.objects.count(), 1)
        self.assertEqual(
            self.api_client(self.employee).get(url).status_code, 403,
        )
