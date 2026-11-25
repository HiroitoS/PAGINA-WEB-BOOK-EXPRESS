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
    DistributionDispatch, DistributionDispatchLine, DistributionTransportDraft,
    GoodsReceipt, StockEntry, StockTransfer, WarehouseFairEvent, WarehouseLocation,
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
        WarehouseFairEvent.objects.create(
            location=cls.fair, idempotency_key=uuid4(),
            name="Feria técnica de pruebas", venue_name="Recinto DEMO",
            venue_address="Dirección DEMO (no real)",
            starts_on="2027-02-01", ends_on="2027-02-02",
            responsible_name="Operador DEMO", created_by=cls.user,
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

    def test_alerta_reposicion_refleja_demanda_planificada_sin_crear_pedido(self):
        from unittest.mock import patch

        client = self.api_client()
        url = (
            "/api/admin/erp/almacen/ubicaciones/alertas-reposicion/"
            f"?location_id={self.main.pk}"
        )
        empty = client.get(url)
        self.assertEqual(empty.status_code, 200, empty.data)
        self.assertEqual(empty.data["products_with_shortage"], 0)

        operation_id = self.plan()
        entries_before = StockEntry.objects.count()
        transfers_before = StockTransfer.objects.count()
        with patch("warehouse.transfers.posiciones_lotes", return_value={}):
            response = client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["products_with_shortage"], 2)
        self.assertEqual(response.data["missing_units"], 10)
        self.assertEqual(
            {row["operations"][0]["operation_id"] for row in response.data["results"]},
            {operation_id},
        )
        self.assertTrue(all(row["free"] == 0 for row in response.data["results"]))
        self.assertEqual(StockEntry.objects.count(), entries_before)
        self.assertEqual(StockTransfer.objects.count(), transfers_before)

        denied = self.api_client(self.employee).get(url)
        self.assertEqual(denied.status_code, 403)
        invalid = client.get(
            "/api/admin/erp/almacen/ubicaciones/alertas-reposicion/?location_id=abc"
        )
        self.assertEqual(invalid.status_code, 400, invalid.data)

    def test_seguimiento_consignaciones_no_infiere_ventas_ni_abonos(self):
        client = self.api_client()
        location = WarehouseLocation.objects.create(
            code=f"CONS-READ-{uuid4().hex[:8]}", name="Consignación de prueba",
            kind=WarehouseLocation.Kind.CONSIGNMENT,
        )
        item = self.adopcion.items.order_by("pk").first()
        response = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            {
                "idempotency_key": str(uuid4()),
                "adoption_id": self.adopcion.pk,
                "mode": "consignment",
                "source_id": self.main.pk,
                "destination_id": location.pk,
                "operation_name": "Consignación sin cobros de prueba",
                "responsible_name": "Responsable de prueba",
                "items": [{"product_id": item.product_id, "quantity": 5}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        url = "/api/admin/erp/almacen/ubicaciones/seguimiento-consignaciones/"
        result = client.get(url)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["count"], 1)
        record = result.data["results"][0]
        self.assertEqual(record["operation_id"], response.data["id"])
        self.assertEqual(record["planned_units"], 5)
        self.assertIsNone(record["delivered_units"])
        self.assertEqual(record["returned_units"], 0)
        self.assertEqual(record["financial_status"], "not_integrated")
        self.assertEqual(StockTransfer.objects.count(), 0)
        denied = self.api_client(self.employee).get(url)
        self.assertEqual(denied.status_code, 403)

    def test_feria_se_agrupa_por_colegio_sin_duplicar_custodia(self):
        operation_id = self.plan()
        client = self.api_client()
        response = client.get("/api/admin/erp/almacen/ferias/")
        self.assertEqual(response.status_code, 200, response.data)
        fair = next(row for row in response.data if row["location_id"] == self.fair.pk)
        self.assertEqual(fair["schools"], [self.adopcion.school.name])
        self.assertFalse(fair["school_conflict"])
        self.assertEqual(DistributionOperation.objects.count(), 1)
        self.assertEqual(DistributionOperation.objects.get(pk=operation_id).destination_id, self.fair.pk)
        self.assertEqual(StockTransfer.objects.count(), 0)

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
        summary = client.get("/api/admin/erp/almacen/ubicaciones/resumen-ubicaciones/")
        self.assertEqual(summary.status_code, 200, summary.data)
        main_summary = next(
            row for row in summary.data["locations"] if row["id"] == self.main.pk
        )
        self.assertEqual(main_summary["reserved"], 10)
        self.assertEqual(
            main_summary["free_to_transfer"],
            main_summary["available"] - 10,
        )
        self.assertGreaterEqual(main_summary["available"], 10)
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

    def test_seleccion_manual_por_guia_reserva_exacto_y_no_mueve_stock(self):
        op_id = self.plan()
        client = self.api_client()
        preview = client.get(self.endpoint(op_id, "preparacion"))
        self.assertEqual(preview.status_code, 200, preview.data)
        chosen = [
            {"stock_entry_id": item["lots"][0]["stock_entry_id"],
             "quantity": item["planned"]}
            for item in preview.data["items"]
        ]
        response = client.post(
            self.endpoint(op_id, "reservar"), {"lots": chosen}, format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "reserved")
        self.assertEqual(DistributionStockReservation.objects.count(), 2)
        self.assertEqual(
            sorted(r["stock_entry_id"] for r in response.data["reservations"]),
            sorted(row["stock_entry_id"] for row in chosen),
        )
        self.assertEqual(StockTransfer.objects.count(), 0)
        self.assertEqual(StockEntry.objects.count(), 2)
        repeat = client.post(
            self.endpoint(op_id, "reservar"), {"lots": chosen}, format="json",
        )
        self.assertEqual(repeat.status_code, 200, repeat.data)
        self.assertEqual(DistributionStockReservation.objects.count(), 2)

    def test_seleccion_manual_invalida_no_deja_reservas_parciales(self):
        op_id = self.plan()
        client = self.api_client()
        preview = client.get(self.endpoint(op_id, "preparacion"))
        valid = [
            {"stock_entry_id": item["lots"][0]["stock_entry_id"],
             "quantity": item["planned"]}
            for item in preview.data["items"]
        ]
        invalid_cases = [
            {"lots": []},
            {"lots": [valid[0], valid[0], valid[1]]},
            {"lots": [valid[0]]},
            {"lots": [{**valid[0], "quantity": 2147483647}, valid[1]]},
            {"lots": [{**valid[0], "quantity": 0}, valid[1]]},
            {"lots": [{**valid[0], "stock_entry_id": 9999999}, valid[1]]},
        ]
        for data in invalid_cases:
            with self.subTest(data=data):
                rejected = client.post(
                    self.endpoint(op_id, "reservar"), data, format="json",
                )
                self.assertEqual(rejected.status_code, 400, rejected.data)
                self.assertFalse(DistributionStockReservation.objects.exists())
                self.assertEqual(
                    DistributionOperation.objects.get(pk=op_id).status, "planned",
                )
        # Trasladar físicamente un lote y tratar de reservarlo en origen
        # tampoco permite usar cantidades que ya no están disponibles.
        registrar_traslado(
            actor=self.user, stock_entry_id=valid[0]["stock_entry_id"],
            source_id=self.main.pk, destination_id=self.fair.pk,
            quantity=self.entries[0].quantity_available, idempotency_key=uuid4(),
            entrega_confirmada=True,
        )
        rejected = client.post(
            self.endpoint(op_id, "reservar"), {"lots": valid}, format="json",
        )
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertFalse(DistributionStockReservation.objects.exists())

    def test_dividir_entrega_reserva_disponibles_y_deja_saldo_pendiente(self):
        """Separar parcialmente no pierde compromisos ni mueve mercadería."""
        operation_id = self.plan()
        entry = self.entries[0]
        registrar_traslado(
            actor=self.user, stock_entry_id=entry.pk,
            source_id=self.main.pk, destination_id=self.fair.pk,
            quantity=entry.quantity_available - 2, idempotency_key=uuid4(),
            entrega_confirmada=True,
        )
        client = self.api_client()
        original = client.get(self.endpoint(operation_id, "preparacion"))
        self.assertEqual(original.status_code, 200, original.data)
        self.assertFalse(original.data["can_reserve"])
        self.assertEqual(original.data["items"][0]["free_at_origin"], 2)
        before_transfers = StockTransfer.objects.count()
        before_entries = StockEntry.objects.count()
        key = str(uuid4())
        split = client.post(
            self.endpoint(operation_id, "separar-disponibles"),
            {"idempotency_key": key}, format="json",
        )
        self.assertEqual(split.status_code, 201, split.data)
        self.assertEqual(split.data["reserved"]["status"], "reserved")
        self.assertEqual(
            sum(row["quantity"] for row in split.data["reserved"]["reservations"]), 7,
        )
        pending_id = split.data["pending_operation_id"]
        self.assertEqual(len(split.data["pending"]), 1)
        self.assertEqual(split.data["pending"][0]["quantity"], 3)
        self.assertEqual(
            dict(DistributionOperation.objects.get(
                pk=operation_id,
            ).items.values_list("product_id", "quantity_planned")),
            {
                original.data["items"][0]["product_id"]: 2,
                original.data["items"][1]["product_id"]: 5,
            },
        )
        self.assertEqual(
            list(DistributionOperation.objects.get(
                pk=pending_id,
            ).items.values_list("quantity_planned", flat=True)), [3],
        )
        self.assertEqual(
            DistributionOperation.objects.get(pk=pending_id).status, "planned",
        )
        self.assertIsNone(DistributionOperation.objects.get(pk=pending_id).scheduled_on)
        self.assertEqual(StockEntry.objects.count(), before_entries)
        self.assertEqual(StockTransfer.objects.count(), before_transfers)
        self.assertEqual(
            self.api_client().patch(self.endpoint(operation_id, "").rstrip("/") + "/", {
                "notes": "Intento de cambio", "reason": "Separación ya iniciada",
            }, format="json").status_code, 400,
        )
        retried = client.post(
            self.endpoint(operation_id, "separar-disponibles"),
            {"idempotency_key": key}, format="json",
        )
        self.assertEqual(retried.status_code, 200, retried.data)
        self.assertFalse(retried.data["created"])
        self.assertEqual(retried.data["pending_operation_id"], pending_id)
        self.assertEqual(DistributionOperation.objects.count(), 2)
        self.assertEqual(
            DistributionOperation.objects.get(pk=operation_id).events.filter(
                action="split_by_stock",
            ).count(), 1,
        )

    def test_division_no_admite_sin_stock_o_sin_faltante(self):
        operation_id = self.plan()
        client = self.api_client()
        all_ready = client.post(
            self.endpoint(operation_id, "separar-disponibles"),
            {"idempotency_key": str(uuid4())}, format="json",
        )
        self.assertEqual(all_ready.status_code, 400, all_ready.data)
        self.assertFalse(DistributionStockReservation.objects.exists())
        self.assertEqual(DistributionOperation.objects.count(), 1)
        for entry in self.entries:
            registrar_traslado(
                actor=self.user, stock_entry_id=entry.pk,
                source_id=self.main.pk, destination_id=self.fair.pk,
                quantity=entry.quantity_available, idempotency_key=uuid4(),
                entrega_confirmada=True,
            )
        without_stock = client.post(
            self.endpoint(operation_id, "separar-disponibles"),
            {"idempotency_key": str(uuid4())}, format="json",
        )
        self.assertEqual(without_stock.status_code, 400, without_stock.data)
        self.assertFalse(DistributionStockReservation.objects.exists())
        self.assertEqual(DistributionOperation.objects.count(), 1)

    def test_motivo_itinerante_es_borrador_y_no_habilita_salida(self):
        """Una feria permite estudiar el motivo, no autoriza despacho ni SUNAT."""
        op_id = self.plan()
        url = self.endpoint(op_id, "documento-traslado")
        response = self.api_client().put(url, {
            "transfer_reason": "itinerant",
            "transport_mode": "private",
            "notes": "Se revisara la aplicabilidad tributaria antes del traslado.",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["draft"]["transfer_reason"], "itinerant")
        self.assertFalse(response.data["sunat_issued"])
        self.assertFalse(response.data["sunat_accepted"])
        self.assertFalse(response.data["data_complete_for_review"])
        self.assertEqual(StockTransfer.objects.count(), 0)
        self.assertEqual(
            DistributionOperation.objects.get(pk=op_id).status, "planned",
        )

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

    def test_b4_documento_interno_no_mueve_libros_y_salida_recepcion_son_dos_etapas(self):
        from warehouse.transfers import posiciones_lotes

        operation_id = self.plan()
        client = self.api_client()
        url = self.endpoint(operation_id, "documento-interno")
        self.assertEqual(client.get(url).data["exists"], False)
        early = client.post(url, {"idempotency_key": str(uuid4())}, format="json")
        self.assertEqual(early.status_code, 400, early.data)
        reserved = client.post(self.endpoint(operation_id, "reservar"), {}, format="json")
        self.assertEqual(reserved.status_code, 201, reserved.data)
        counted = client.post(self.endpoint(operation_id, "confirmar-preparacion"), {
            "counts": [{
                "reservation_id": row["id"], "counted": row["quantity"],
            } for row in reserved.data["reservations"]],
        }, format="json")
        self.assertEqual(counted.status_code, 200, counted.data)
        before = posiciones_lotes(self.entries)
        stock_before = StockEntry.objects.count()
        doc = client.post(url, {"idempotency_key": str(uuid4())}, format="json")
        self.assertEqual(doc.status_code, 201, doc.data)
        self.assertEqual(doc.data["status"], "documented")
        self.assertTrue(doc.data["document_number"].startswith("BE-SI-"))
        self.assertEqual(posiciones_lotes(self.entries), before)
        self.assertEqual(StockTransfer.objects.count(), 0)
        retry = client.post(url, {"idempotency_key": str(uuid4())}, format="json")
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(retry.data["id"], doc.data["id"])
        self.assertEqual(DistributionDispatch.objects.count(), 1)

        invalid = client.post(self.endpoint(operation_id, "confirmar-salida"), {
            "evidence_kind": "external_guide",
            "external_guide_reference": "", "physical_dispatch_confirmed": True,
        }, format="json")
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertEqual(posiciones_lotes(self.entries), before)
        bogus_guide = client.post(self.endpoint(operation_id, "confirmar-salida"), {
            "evidence_kind": "external_guide",
            "external_guide_reference": "asdasdas",
            "physical_dispatch_confirmed": True,
        }, format="json")
        self.assertEqual(bogus_guide.status_code, 400, bogus_guide.data)
        self.assertEqual(posiciones_lotes(self.entries), before)

        out = client.post(self.endpoint(operation_id, "confirmar-salida"), {
            "evidence_kind": "external_guide",
            "external_guide_reference": "EG01-00000051",
            "physical_dispatch_confirmed": True,
        }, format="json")
        self.assertEqual(out.status_code, 201, out.data)
        self.assertEqual(out.data["status"], "in_transit")
        self.assertEqual(out.data["operation_status"], "in_transit")
        self.assertEqual(StockEntry.objects.count(), stock_before)
        self.assertEqual(StockTransfer.objects.count(), 0)
        transit = posiciones_lotes(self.entries)
        for line in out.data["lines"]:
            entry_id = line["stock_entry_id"]
            self.assertEqual(
                transit[(entry_id, self.main.pk)],
                before[(entry_id, self.main.pk)] - line["quantity"],
            )
            self.assertEqual(transit.get((entry_id, self.fair.pk), 0), 0)
        self.assertEqual(sum(line["quantity"] for line in out.data["lines"]), 10)
        from warehouse.consolidated import consultar_consolidado
        consolidated_out = consultar_consolidado(grupo="almacen")
        self.assertEqual(consolidated_out["resumen"]["unidades_en_transito"], 10)
        self.assertEqual(consolidated_out["resumen"]["unidades_sin_ubicacion"], 0)
        self.assertIn(
            "En tránsito (pendiente de recepción)",
            [row["grupo_nombre"] for row in consolidated_out["resultados"]],
        )
        self.assertEqual(
            client.post(self.endpoint(operation_id, "confirmar-salida"), {
                "evidence_kind": "external_guide",
                "external_guide_reference": "EG01-00000051",
                "physical_dispatch_confirmed": True,
            }, format="json").status_code, 200,
        )
        self.assertEqual(DistributionDispatchLine.objects.count(), 2)

        bad_arrival = client.post(self.endpoint(operation_id, "confirmar-llegada"), {
            "receiver_name": "Responsable DEMO", "arrival_confirmed": True,
            "counts": [
                {"line_id": line["id"], "counted": line["quantity"] - 1}
                for line in out.data["lines"]
            ],
        }, format="json")
        self.assertEqual(bad_arrival.status_code, 400, bad_arrival.data)
        self.assertEqual(posiciones_lotes(self.entries), transit)
        invalid_name = client.post(self.endpoint(operation_id, "confirmar-llegada"), {
            "receiver_name": "shamir", "arrival_confirmed": True,
            "counts": [
                {"line_id": line["id"], "counted": line["quantity"]}
                for line in out.data["lines"]
            ],
        }, format="json")
        self.assertEqual(invalid_name.status_code, 400, invalid_name.data)
        self.assertEqual(posiciones_lotes(self.entries), transit)
        good_arrival = client.post(self.endpoint(operation_id, "confirmar-llegada"), {
            "receiver_name": "Responsable DEMO", "arrival_confirmed": True,
            "counts": [
                {"line_id": line["id"], "counted": line["quantity"]}
                for line in out.data["lines"]
            ],
        }, format="json")
        self.assertEqual(good_arrival.status_code, 200, good_arrival.data)
        self.assertEqual(good_arrival.data["status"], "received")
        self.assertEqual(good_arrival.data["recipient_name"], "Responsable DEMO")
        self.assertTrue(good_arrival.data["received_by"])
        self.assertIsNotNone(good_arrival.data["received_at"])
        self.assertEqual(good_arrival.data["operation_status"], "delivered")
        final = posiciones_lotes(self.entries)
        for line in good_arrival.data["lines"]:
            entry_id = line["stock_entry_id"]
            self.assertEqual(final[(entry_id, self.main.pk)], transit[(entry_id, self.main.pk)])
            self.assertEqual(final[(entry_id, self.fair.pk)], line["quantity"])
        self.assertEqual(StockEntry.objects.count(), stock_before)
        self.assertEqual(StockTransfer.objects.count(), 0)
        consolidated_received = consultar_consolidado(grupo="almacen")
        self.assertEqual(consolidated_received["resumen"]["unidades_en_transito"], 0)
        self.assertEqual(consolidated_received["resumen"]["unidades_sin_ubicacion"], 0)
        available_destination = client.get(
            f"/api/admin/erp/almacen/traslados/lotes/?source_id={self.fair.pk}"
        )
        self.assertEqual(available_destination.status_code, 200, available_destination.data)
        self.assertEqual(
            sum(row["available"] for row in available_destination.data["results"]), 10,
        )
        self.assertEqual(
            client.post(self.endpoint(operation_id, "confirmar-llegada"), {
                "receiver_name": "Responsable DEMO", "arrival_confirmed": True,
                "counts": [{"line_id": row["id"], "counted": row["quantity"]}
                           for row in good_arrival.data["lines"]],
            }, format="json").status_code, 400,
        )

    def test_b4_feria_generica_no_puede_despacharse(self):
        operation_id = self.plan()
        op = DistributionOperation.objects.get(pk=operation_id)
        other_fair = WarehouseLocation.objects.create(
            code=f"OLD-F-{uuid4().hex[:8]}", name="ALMACEN FERIA HISTORICO",
            kind=WarehouseLocation.Kind.FAIR,
        )
        op.destination = other_fair
        op.save(update_fields=["destination", "updated_at"])
        client = self.api_client()
        reserved = client.post(self.endpoint(operation_id, "reservar"), {}, format="json")
        self.assertEqual(reserved.status_code, 201, reserved.data)
        counted = client.post(self.endpoint(operation_id, "confirmar-preparacion"), {
            "counts": [{"reservation_id": row["id"], "counted": row["quantity"]}
                       for row in reserved.data["reservations"]],
        }, format="json")
        self.assertEqual(counted.status_code, 200, counted.data)
        doc = client.post(self.endpoint(operation_id, "documento-interno"), {
            "idempotency_key": str(uuid4()),
        }, format="json")
        self.assertEqual(doc.status_code, 400, doc.data)
        self.assertFalse(DistributionDispatch.objects.exists())

    def test_b4_usuario_sin_permiso_no_puede_documentar_o_despachar(self):
        operation_id = self.plan()
        limited = self.api_client(self.employee)
        self.assertEqual(limited.get(self.endpoint(operation_id, "documento-interno")).status_code, 403)
        self.assertEqual(limited.post(self.endpoint(operation_id, "documento-interno"), {
            "idempotency_key": str(uuid4()),
        }, format="json").status_code, 403)

    def test_b5_diferencia_llegada_no_mueve_stock_y_reconteo_conforme_requiere_jefatura(self):
        from warehouse.models import DistributionArrivalIncident
        from warehouse.transfers import posiciones_lotes

        operation_id = self.plan()
        client = self.api_client()
        reserve = client.post(self.endpoint(operation_id, "reservar"), {}, format="json")
        self.assertEqual(reserve.status_code, 201, reserve.data)
        preparation = client.post(
            self.endpoint(operation_id, "confirmar-preparacion"),
            {"counts": [
                {"reservation_id": row["id"], "counted": row["quantity"]}
                for row in reserve.data["reservations"]
            ]}, format="json",
        )
        self.assertEqual(preparation.status_code, 200, preparation.data)
        internal = client.post(
            self.endpoint(operation_id, "documento-interno"),
            {"idempotency_key": str(uuid4())}, format="json",
        )
        self.assertEqual(internal.status_code, 201, internal.data)
        out = client.post(
            self.endpoint(operation_id, "confirmar-salida"),
            {
                "evidence_kind": "external_guide",
                "external_guide_reference": "EG01-00000052",
                "physical_dispatch_confirmed": True,
            }, format="json",
        )
        self.assertEqual(out.status_code, 201, out.data)
        lines = out.data["lines"]
        self.assertEqual(len(lines), 2)
        transit_before = posiciones_lotes(self.entries)
        count_before = StockEntry.objects.count()
        difference_counts = [
            {"line_id": line["id"], "counted": line["quantity"] - (1 if idx == 0 else 0)}
            for idx, line in enumerate(lines)
        ]
        url = self.endpoint(operation_id, "registrar-diferencia-llegada")
        incident = client.post(url, {
            "receiver_name": "Encargado de la feria",
            "observations": "En el primer lote se observa un libro faltante.",
            "counts": difference_counts,
        }, format="json")
        self.assertEqual(incident.status_code, 201, incident.data)
        self.assertEqual(incident.data["operation_status"], "in_transit")
        self.assertTrue(incident.data["open_incident"])
        self.assertEqual(len(incident.data["arrival_incidents"]), 1)
        self.assertEqual(incident.data["arrival_incidents"][0]["counts"][0]["difference"], -1)
        incident_id = incident.data["created_incident_id"]
        self.assertEqual(DistributionArrivalIncident.objects.count(), 1)
        self.assertEqual(posiciones_lotes(self.entries), transit_before)
        self.assertEqual(StockEntry.objects.count(), count_before)

        # B5.2: documentar faltantes persistentes sin registrar recepción parcial
        # ni mover existencias. El desglose pertenece a la incidencia original.
        diagnosis_url = self.endpoint(operation_id, "documentar-diferencia-persistente")
        breakdown = [{
            "line_id": line["id"],
            "conforming": line["quantity"] - (1 if idx == 0 else 0),
            "damaged": 0, "extra": 0,
        } for idx, line in enumerate(lines)]
        invalid_diagnosis = client.post(diagnosis_url, {
            "incident_id": incident_id, "breakdown": [
                {**breakdown[0], "conforming": breakdown[0]["conforming"] + 1},
                *breakdown[1:],
            ],
            "note": "Se realizó la verificación física del lote faltante.",
        }, format="json")
        self.assertEqual(invalid_diagnosis.status_code, 400, invalid_diagnosis.data)
        documented = client.post(diagnosis_url, {
            "incident_id": incident_id, "breakdown": breakdown,
            "note": "Se confirmó el faltante durante el conteo de llegada.",
        }, format="json")
        self.assertEqual(documented.status_code, 201, documented.data)
        self.assertEqual(documented.data["arrival_diagnoses"][0]["details"][0]["missing"], 1)
        self.assertTrue(documented.data["open_incident"])
        self.assertEqual(documented.data["operation_status"], "in_transit")
        self.assertEqual(posiciones_lotes(self.entries), transit_before)
        self.assertEqual(StockEntry.objects.count(), count_before)
        repeated = client.post(diagnosis_url, {
            "incident_id": incident_id, "breakdown": breakdown,
            "note": "No debe documentarse una segunda vez la misma incidencia.",
        }, format="json")
        self.assertEqual(repeated.status_code, 400, repeated.data)

        duplicate = client.post(url, {
            "receiver_name": "Encargado de la feria",
            "observations": "Diferencia duplicada por doble pulsación.",
            "counts": difference_counts,
        }, format="json")
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertEqual(DistributionArrivalIncident.objects.count(), 1)

        correct = [
            {"line_id": line["id"], "counted": line["quantity"]}
            for line in lines
        ]
        blocked = client.post(self.endpoint(operation_id, "confirmar-llegada"), {
            "receiver_name": "Encargado de la feria",
            "arrival_confirmed": True, "counts": correct,
        }, format="json")
        self.assertEqual(blocked.status_code, 400, blocked.data)
        self.assertEqual(posiciones_lotes(self.entries), transit_before)

        bad_resolution = client.post(
            self.endpoint(operation_id, "resolver-diferencia-llegada"),
            {
                "incident_id": incident_id,
                "counts": difference_counts,
                "resolution_note": "Recuento parcial, todavía no coincide.",
            }, format="json",
        )
        self.assertEqual(bad_resolution.status_code, 400, bad_resolution.data)
        self.assertEqual(DistributionArrivalIncident.objects.get(pk=incident_id).status, "open")
        resolved = client.post(
            self.endpoint(operation_id, "resolver-diferencia-llegada"),
            {
                "incident_id": incident_id, "counts": correct,
                "resolution_note": "El encargado revisó y encontró físicamente el libro faltante.",
            }, format="json",
        )
        self.assertEqual(resolved.status_code, 200, resolved.data)
        self.assertFalse(resolved.data["open_incident"])
        self.assertEqual(resolved.data["arrival_incidents"][0]["status"], "resolved")
        self.assertEqual(posiciones_lotes(self.entries), transit_before)
        self.assertEqual(
            client.post(self.endpoint(operation_id, "resolver-diferencia-llegada"), {
                "incident_id": incident_id, "counts": correct,
                "resolution_note": "No se puede cerrar dos veces la misma incidencia.",
            }, format="json").status_code, 400,
        )
        finished = client.post(self.endpoint(operation_id, "confirmar-llegada"), {
            "receiver_name": "Encargado de la feria",
            "arrival_confirmed": True, "counts": correct,
        }, format="json")
        self.assertEqual(finished.status_code, 200, finished.data)
        self.assertEqual(finished.data["status"], "received")
        self.assertEqual(finished.data["arrival_incidents"][0]["status"], "resolved")
        self.assertEqual(StockEntry.objects.count(), count_before)
        self.assertEqual(StockTransfer.objects.count(), 0)
        self.assertNotEqual(posiciones_lotes(self.entries), transit_before)

    def test_b5_3_retorno_parcial_de_feria_no_duplica_saldos(self):
        from warehouse.transfers import posiciones_lotes

        operation_id = self.plan()
        client = self.api_client()
        reserve = client.post(
            self.endpoint(operation_id, "reservar"), {}, format="json",
        )
        self.assertEqual(reserve.status_code, 201, reserve.data)
        prepared = client.post(
            self.endpoint(operation_id, "confirmar-preparacion"),
            {"counts": [
                {"reservation_id": row["id"], "counted": row["quantity"]}
                for row in reserve.data["reservations"]
            ]}, format="json",
        )
        self.assertEqual(prepared.status_code, 200, prepared.data)
        created = client.post(
            self.endpoint(operation_id, "documento-interno"),
            {"idempotency_key": str(uuid4())}, format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        out = client.post(
            self.endpoint(operation_id, "confirmar-salida"),
            {"evidence_kind": "external_guide",
             "external_guide_reference": "EG01-00000124",
             "physical_dispatch_confirmed": True}, format="json",
        )
        self.assertEqual(out.status_code, 201, out.data)
        arrival = client.post(
            self.endpoint(operation_id, "confirmar-llegada"),
            {
                "receiver_name": "Responsable Feria",
                "arrival_confirmed": True,
                "counts": [
                    {"line_id": row["id"], "counted": row["quantity"]}
                    for row in out.data["lines"]
                ],
            }, format="json",
        )
        self.assertEqual(arrival.status_code, 200, arrival.data)
        # El recuento y hallazgo posterior son eventos auditables sin stock ficticio.
        line = arrival.data["lines"][0]
        difference_url = self.endpoint(operation_id, "registrar-diferencia-cierre")
        report_payload = {
            "idempotency_key": str(uuid4()),
            "line_id": line["id"],
            "quantity": 2,
            "category": "not_found",
            "note": "En el conteo de cierre no se localizaron dos ejemplares.",
        }
        stock_before_note = posiciones_lotes(self.entries)
        report = client.post(difference_url, report_payload, format="json")
        self.assertEqual(report.status_code, 201, report.data)
        report_id = report.data["close_incident_id"]
        self.assertEqual(posiciones_lotes(self.entries), stock_before_note)
        repeated_report = client.post(difference_url, report_payload, format="json")
        self.assertEqual(repeated_report.status_code, 200, repeated_report.data)
        self.assertEqual(repeated_report.data["close_incident_id"], report_id)
        # Un nuevo reporte no puede duplicar la misma cantidad física del lote.
        over_report = client.post(difference_url, {
            **report_payload,
            "idempotency_key": str(uuid4()),
            "quantity": line["quantity"],
        }, format="json")
        self.assertEqual(over_report.status_code, 400, over_report.data)
        self.assertEqual(posiciones_lotes(self.entries), stock_before_note)
        finding_url = self.endpoint(operation_id, "registrar-hallazgo-cierre")
        finding_payload = {
            "idempotency_key": str(uuid4()),
            "report_id": report_id, "quantity": 1,
            "location_note": "Un ejemplar apareció debajo de una mesa durante segundo conteo.",
        }
        found = client.post(finding_url, finding_payload, format="json")
        self.assertEqual(found.status_code, 201, found.data)
        self.assertEqual(found.data["close_incidents"][0]["found_quantity"], 1)
        self.assertEqual(posiciones_lotes(self.entries), stock_before_note)
        repeat_found = client.post(finding_url, finding_payload, format="json")
        self.assertEqual(repeat_found.status_code, 200, repeat_found.data)
        over_found = client.post(finding_url, {
            **finding_payload, "idempotency_key": str(uuid4()), "quantity": 2,
        }, format="json")
        self.assertEqual(over_found.status_code, 400, over_found.data)
        self.assertFalse(found.data["reconciliation"]["can_close"])

        entry_id = line["stock_entry_id"]
        before = posiciones_lotes(self.entries)
        main_before = before[(entry_id, self.main.pk)]
        fair_before = before[(entry_id, self.fair.pk)]
        # Constancia BE-RI: preparación interna independiente del sustento legal.
        # No puede mover stock ni autorizar transporte por sí misma.
        prepare_url = self.endpoint(operation_id, "preparar-retorno-destino")
        prepare_key = str(uuid4())
        preparation_payload = {
            "idempotency_key": prepare_key,
            "reason": "Preparación documentada de sobrantes de feria",
            "lines": [{"line_id": line["id"], "quantity": 2}],
        }
        transfer_before_preparing = StockTransfer.objects.count()
        prep = client.post(prepare_url, preparation_payload, format="json")
        self.assertEqual(prep.status_code, 201, prep.data)
        self.assertRegex(prep.data["internal_return_number"], r"^BE-RI-[0-9]{7}$")
        self.assertEqual(len(prep.data["internal_return_plans"]), 1)
        self.assertEqual(StockTransfer.objects.count(), transfer_before_preparing)
        self.assertEqual(posiciones_lotes(self.entries), before)
        repeated_prep = client.post(prepare_url, preparation_payload, format="json")
        self.assertEqual(repeated_prep.status_code, 200, repeated_prep.data)
        self.assertEqual(repeated_prep.data["internal_return_number"],
                         prep.data["internal_return_number"])
        self.assertEqual(StockTransfer.objects.count(), transfer_before_preparing)
        # Doble clic o reintento con clave nueva no crea otra numeración BE-RI
        # si el documento previo sigue pendiente y los datos son idénticos.
        repeated_new_key = client.post(prepare_url, {
            **preparation_payload, "idempotency_key": str(uuid4()),
        }, format="json")
        self.assertEqual(repeated_new_key.status_code, 200, repeated_new_key.data)
        self.assertEqual(
            repeated_new_key.data["internal_return_number"],
            prep.data["internal_return_number"],
        )
        self.assertEqual(len(repeated_new_key.data["internal_return_plans"]), 1)
        self.assertEqual(posiciones_lotes(self.entries), before)
        invalid_prep = client.post(prepare_url, {
            **preparation_payload, "idempotency_key": str(uuid4()),
            "lines": [{"line_id": line["id"], "quantity": line["quantity"] + 1}],
        }, format="json")
        self.assertEqual(invalid_prep.status_code, 400, invalid_prep.data)
        self.assertEqual(posiciones_lotes(self.entries), before)

        key = str(uuid4())
        request = {
            "idempotency_key": key,
            "receiver_name": "Responsable Almacen",
            "transport_reference": "EG01-00000125",
            "reason": "Retorno parcial de sobrantes de la feria escolar",
            "received_confirmed": True,
            "lines": [{"line_id": line["id"], "quantity": 2}],
        }
        endpoint = self.endpoint(operation_id, "registrar-retorno-feria")
        count_before = StockTransfer.objects.count()
        from unittest.mock import patch
        with patch(
            "warehouse.distribution_dispatch.feria_compartida_entre_colegios",
            return_value=True,
        ):
            blocked = client.post(endpoint, request, format="json")
        self.assertEqual(blocked.status_code, 400, blocked.data)
        self.assertEqual(StockTransfer.objects.count(), count_before)
        posted = client.post(endpoint, request, format="json")
        self.assertEqual(posted.status_code, 201, posted.data)
        self.assertEqual(len(posted.data["fair_returns"]), 1)
        self.assertEqual(StockTransfer.objects.count(), count_before + 1)
        after = posiciones_lotes(self.entries)
        self.assertEqual(after[(entry_id, self.main.pk)], main_before + 2)
        self.assertEqual(after[(entry_id, self.fair.pk)], fair_before - 2)
        summary = posted.data["reconciliation"]
        self.assertEqual(summary["delivered"], sum(row["quantity"] for row in arrival.data["lines"]))
        self.assertEqual(summary["returned"], 2)
        receipt = posted.data["fair_returns"][-1]
        self.assertTrue(receipt["receipt_number"].startswith("BE-RC-"))
        self.assertEqual(sum(line["quantity"] for line in receipt["details"]), 2)
        self.assertEqual(receipt["source_document"], posted.data["document_number"])
        self.assertTrue(receipt["reason"])
        self.assertEqual(receipt["received_by"], "Responsable Almacen")
        self.assertEqual(summary["not_returned"], sum(row["quantity"] for row in arrival.data["lines"]) - 2)
        self.assertIsNone(summary["sold"])
        self.assertIsNone(summary["difference"])
        self.assertEqual(summary["status"], "sales_not_integrated")
        self.assertFalse(summary["can_close"])

        retry = client.post(endpoint, request, format="json")
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(StockTransfer.objects.count(), count_before + 1)
        changed = client.post(endpoint, {**request, "lines": [
            {"line_id": line["id"], "quantity": 1},
        ]}, format="json")
        self.assertEqual(changed.status_code, 400, changed.data)
        self.assertEqual(StockTransfer.objects.count(), count_before + 1)

        excess = client.post(endpoint, {**request,
            "idempotency_key": str(uuid4()),
            "lines": [{"line_id": line["id"], "quantity": line["quantity"]}],
        }, format="json")
        self.assertEqual(excess.status_code, 400, excess.data)
        self.assertEqual(StockTransfer.objects.count(), count_before + 1)
        self.assertEqual(posiciones_lotes(self.entries), after)

        restricted = self.api_client(self.employee).post(endpoint, {
            **request, "idempotency_key": str(uuid4()),
        }, format="json")
        self.assertEqual(restricted.status_code, 403)

        # La recepción física observada no inventa GRE: deja seguimiento abierto.
        # Solo Jefatura registra lo ocurrido, sin fingir cumplimiento tributario.
        observed = {
            **request,
            "idempotency_key": str(uuid4()),
            "transport_reference": "",
            "documentation_status": "pending_review",
            "documentation_note": (
                "Mercadería recibida físicamente al cierre de feria; la guía "
                "de transporte no fue presentada y se remitió el caso a Jefatura."
            ),
            "lines": [{"line_id": line["id"], "quantity": 1}],
        }
        invalid_note = client.post(endpoint, {
            **observed, "documentation_note": "sin guia",
        }, format="json")
        self.assertEqual(invalid_note.status_code, 400, invalid_note.data)
        self.assertEqual(StockTransfer.objects.count(), count_before + 1)
        recorded = client.post(endpoint, observed, format="json")
        self.assertEqual(recorded.status_code, 201, recorded.data)
        self.assertEqual(StockTransfer.objects.count(), count_before + 2)
        self.assertTrue(recorded.data["fair_returns"][-1]["documentation_followup_required"])
        self.assertEqual(recorded.data["fair_returns"][-1]["documentation_status"], "pending_review")
        self.assertEqual(recorded.data["fair_returns"][-1]["reference"], "")
        final = posiciones_lotes(self.entries)
        self.assertEqual(final[(entry_id, self.main.pk)], main_before + 3)
        self.assertEqual(final[(entry_id, self.fair.pk)], fair_before - 3)
        repeat_observed = client.post(endpoint, observed, format="json")
        self.assertEqual(repeat_observed.status_code, 200, repeat_observed.data)
        self.assertEqual(StockTransfer.objects.count(), count_before + 2)
        # Cierre interno: feria sin GRE ficticia, pero no falsifica cumplimiento.
        internal = client.post(endpoint, {
            **request,
            "idempotency_key": str(uuid4()),
            "transport_reference": "",
            "documentation_status": "internal_control",
            "documentation_note": "",
            "lines": [{"line_id": line["id"], "quantity": 1}],
        }, format="json")
        self.assertEqual(internal.status_code, 201, internal.data)
        self.assertEqual(StockTransfer.objects.count(), count_before + 3)
        internal_record = internal.data["fair_returns"][-1]
        self.assertEqual(internal_record["documentation_status"], "internal_control")
        self.assertTrue(internal_record["documentation_followup_required"])
        self.assertEqual(internal_record["reference"], "")
        self.assertGreaterEqual(len(internal_record["documentation_note"]), 40)
        self.assertEqual(posiciones_lotes(self.entries)[(entry_id, self.main.pk)], main_before + 4)
        followup_url = "/api/admin/erp/almacen/ubicaciones/retornos-documentacion-pendiente/"
        followup = client.get(followup_url)
        self.assertEqual(followup.status_code, 200, followup.data)
        item = next(
            record for record in followup.data["results"]
            if record["operation_id"] == operation_id
        )
        self.assertEqual(item["quantity"], 1)
        self.assertEqual(item["documentation_status"], "pending_review")
        self.assertFalse("external_guide_reference" in item)
        denied_followup = self.api_client(self.employee).get(followup_url)
        self.assertEqual(denied_followup.status_code, 403)

    def test_b5_retorno_directo_punto_venta_con_be_rc_y_saldos_sin_ventas_inferidas(self):
        from warehouse.transfers import posiciones_lotes

        store = WarehouseLocation.objects.create(
            code=f"B5-PV-{uuid4().hex[:8]}",
            name="Punto de venta de ensayo",
            kind=WarehouseLocation.Kind.STORE,
        )
        client = self.api_client()
        products = list(self.adopcion.items.order_by("pk"))
        operation = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            {
                "idempotency_key": str(uuid4()),
                "adoption_id": self.adopcion.pk,
                "mode": "point_of_sale",
                "source_id": self.main.pk,
                "destination_id": store.pk,
                "operation_name": "Punto de venta de ensayo",
                "responsible_name": "Responsable de ensayo",
                "items": [{"product_id": item.product_id, "quantity": 5}
                          for item in products],
            }, format="json",
        )
        self.assertEqual(operation.status_code, 201, operation.data)
        op_id = operation.data["id"]
        reserve = client.post(self.endpoint(op_id, "reservar"), {}, format="json")
        self.assertEqual(reserve.status_code, 201, reserve.data)
        prepared = client.post(self.endpoint(op_id, "confirmar-preparacion"), {
            "counts": [{"reservation_id": row["id"], "counted": row["quantity"]}
                       for row in reserve.data["reservations"]],
        }, format="json")
        self.assertEqual(prepared.status_code, 200, prepared.data)
        doc = client.post(self.endpoint(op_id, "documento-interno"), {
            "idempotency_key": str(uuid4()),
        }, format="json")
        self.assertEqual(doc.status_code, 201, doc.data)
        dispatched = client.post(self.endpoint(op_id, "confirmar-salida"), {
            "evidence_kind": "external_guide",
            "external_guide_reference": "EG01-00000215",
            "physical_dispatch_confirmed": True,
        }, format="json")
        self.assertEqual(dispatched.status_code, 201, dispatched.data)
        arrival = client.post(self.endpoint(op_id, "confirmar-llegada"), {
            "receiver_name": "Responsable Tienda",
            "arrival_confirmed": True,
            "counts": [{"line_id": row["id"], "counted": row["quantity"]}
                       for row in dispatched.data["lines"]],
        }, format="json")
        self.assertEqual(arrival.status_code, 200, arrival.data)
        line = arrival.data["lines"][0]
        before = posiciones_lotes(self.entries)
        main_before = before[(line["stock_entry_id"], self.main.pk)]
        store_before = before[(line["stock_entry_id"], store.pk)]
        request_lines = [{"line_id": line["id"], "quantity": 2}]
        request = {
            "idempotency_key": str(uuid4()),
            "receiver_name": "Encargado Almacen",
            "transport_reference": "",
            "documentation_status": "internal_control",
            "reason": "Devolución de sobrantes del punto de venta",
            "received_confirmed": True,
            "lines": request_lines,
        }
        previous_transfers = StockTransfer.objects.count()
        done = client.post(self.endpoint(op_id, "registrar-retorno-destino"),
                           request, format="json")
        self.assertEqual(done.status_code, 201, done.data)
        self.assertEqual(done.data["reconciliation"]["delivered"], 10)
        self.assertEqual(done.data["reconciliation"]["returned"], 2)
        receipt = done.data["destination_returns"][-1]
        self.assertTrue(receipt["receipt_number"].startswith("BE-RC-"))
        self.assertEqual(sum(item["quantity"] for item in receipt["details"]), 2)
        self.assertFalse(done.data["internal_return_plans"])

        self.assertEqual(done.data["reconciliation"]["not_returned"], 8)
        self.assertIsNone(done.data["reconciliation"]["sold"])
        self.assertFalse(done.data["reconciliation"]["can_close"])
        self.assertEqual(StockTransfer.objects.count(), previous_transfers + 1)
        after = posiciones_lotes(self.entries)
        self.assertEqual(after[(line["stock_entry_id"], self.main.pk)], main_before + 2)
        self.assertEqual(after[(line["stock_entry_id"], store.pk)], store_before - 2)
        repeated = client.post(self.endpoint(op_id, "registrar-retorno-destino"),
                               request, format="json")
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(StockTransfer.objects.count(), previous_transfers + 1)
        self.assertEqual(posiciones_lotes(self.entries), after)

    def test_b5_3_retorno_de_consignacion_idempotente(self):
        from warehouse.transfers import posiciones_lotes

        location = WarehouseLocation.objects.create(
            code=f"B5-CONS-{uuid4().hex[:8]}", name="Consignación de prueba",
            kind=WarehouseLocation.Kind.CONSIGNMENT,
        )
        client = self.api_client()
        products = list(self.adopcion.items.order_by("pk"))
        plan = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            {
                "idempotency_key": str(uuid4()), "adoption_id": self.adopcion.pk,
                "mode": "consignment", "source_id": self.main.pk,
                "destination_id": location.pk,
                "operation_name": "Consignación de ensayo",
                "responsible_name": "Responsable de ensayo",
                "items": [
                    {"product_id": item.product_id, "quantity": 5}
                    for item in products
                ],
            }, format="json",
        )
        self.assertEqual(plan.status_code, 201, plan.data)
        operation_id = plan.data["id"]
        reserve = client.post(
            self.endpoint(operation_id, "reservar"), {}, format="json",
        )
        self.assertEqual(reserve.status_code, 201, reserve.data)
        prepared = client.post(
            self.endpoint(operation_id, "confirmar-preparacion"),
            {"counts": [
                {"reservation_id": row["id"], "counted": row["quantity"]}
                for row in reserve.data["reservations"]
            ]}, format="json",
        )
        self.assertEqual(prepared.status_code, 200, prepared.data)
        created = client.post(
            self.endpoint(operation_id, "documento-interno"),
            {"idempotency_key": str(uuid4())}, format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        out = client.post(
            self.endpoint(operation_id, "confirmar-salida"),
            {"evidence_kind": "external_guide",
             "external_guide_reference": "EG01-00000124",
             "physical_dispatch_confirmed": True}, format="json",
        )
        self.assertEqual(out.status_code, 201, out.data)
        arrival = client.post(
            self.endpoint(operation_id, "confirmar-llegada"),
            {
                "receiver_name": "Responsable Feria",
                "arrival_confirmed": True,
                "counts": [
                    {"line_id": row["id"], "counted": row["quantity"]}
                    for row in out.data["lines"]
                ],
            }, format="json",
        )
        self.assertEqual(arrival.status_code, 200, arrival.data)
        line = arrival.data["lines"][0]
        entry_id = line["stock_entry_id"]
        before = posiciones_lotes(self.entries)
        main_before = before[(entry_id, self.main.pk)]
        fair_before = before[(entry_id, location.pk)]
        key = str(uuid4())
        request = {
            "idempotency_key": key,
            "receiver_name": "Responsable Almacen",
            "transport_reference": "EG01-00000125",
            "reason": "Retorno parcial de sobrantes de consignación",
            "received_confirmed": True,
            "lines": [{"line_id": line["id"], "quantity": 2}],
        }
        endpoint = self.endpoint(operation_id, "registrar-retorno-destino")
        # No permitir que consignación utilice modalidad interna de feria.
        invalid_internal = client.post(endpoint, {
            **request,
            "idempotency_key": str(uuid4()),
            "transport_reference": "",
            "documentation_status": "internal_control",
        }, format="json")
        self.assertEqual(invalid_internal.status_code, 400, invalid_internal.data)
        count_before = StockTransfer.objects.count()
        posted = client.post(endpoint, request, format="json")
        self.assertEqual(posted.status_code, 201, posted.data)
        self.assertEqual(len(posted.data["destination_returns"]), 1)
        self.assertEqual(posted.data["destination_returns"][0]["details"][0]["quantity"], 2)
        receipt = posted.data["destination_returns"][0]
        self.assertTrue(receipt["receipt_number"].startswith("BE-RC-"))
        self.assertEqual(receipt["received_by"], "Responsable Almacen")
        self.assertEqual(posted.data["reconciliation"]["delivered"], sum(row["quantity"] for row in arrival.data["lines"]))
        self.assertEqual(posted.data["reconciliation"]["returned"], 2)
        self.assertEqual(posted.data["reconciliation"]["not_returned"], sum(row["quantity"] for row in arrival.data["lines"]) - 2)
        self.assertIsNone(posted.data["reconciliation"]["sold"])
        self.assertFalse(posted.data["reconciliation"]["can_close"])

        self.assertEqual(StockTransfer.objects.count(), count_before + 1)
        after = posiciones_lotes(self.entries)
        self.assertEqual(after[(entry_id, self.main.pk)], main_before + 2)
        self.assertEqual(after[(entry_id, location.pk)], fair_before - 2)

        retry = client.post(endpoint, request, format="json")
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(StockTransfer.objects.count(), count_before + 1)
        changed = client.post(endpoint, {**request, "lines": [
            {"line_id": line["id"], "quantity": 1},
        ]}, format="json")
        self.assertEqual(changed.status_code, 400, changed.data)
        self.assertEqual(StockTransfer.objects.count(), count_before + 1)

        excess = client.post(endpoint, {**request,
            "idempotency_key": str(uuid4()),
            "lines": [{"line_id": line["id"], "quantity": line["quantity"]}],
        }, format="json")
        self.assertEqual(excess.status_code, 400, excess.data)
        self.assertEqual(StockTransfer.objects.count(), count_before + 1)
        self.assertEqual(posiciones_lotes(self.entries), after)

        restricted = self.api_client(self.employee).post(endpoint, {
            **request, "idempotency_key": str(uuid4()),
        }, format="json")
        self.assertEqual(restricted.status_code, 403)

    def test_b5_servicio_rechaza_conteos_negativos_sin_depender_del_serializer(self):
        """Protege futuras llamadas internas y el flujo de incidencias B5."""
        from types import SimpleNamespace
        from unittest.mock import Mock

        from django.core.exceptions import ValidationError
        from warehouse.distribution_dispatch import _validar_conteo_lineas

        dispatch = SimpleNamespace(lines=Mock())
        dispatch.lines.order_by.return_value = [
            SimpleNamespace(pk=11, quantity=3),
            SimpleNamespace(pk=12, quantity=2),
        ]
        with self.assertRaisesMessage(ValidationError, "enteros no negativos"):
            _validar_conteo_lineas(dispatch, [
                {"line_id": 11, "counted": -1},
                {"line_id": 12, "counted": 2},
            ])
        with self.assertRaisesMessage(ValidationError, "enteros no negativos"):
            _validar_conteo_lineas(dispatch, [
                {"line_id": 11, "counted": True},
                {"line_id": 12, "counted": 2},
            ])
        expected, given = _validar_conteo_lineas(dispatch, [
            {"line_id": 11, "counted": 2},
            {"line_id": 12, "counted": 2},
        ])
        self.assertEqual(expected, {11: 3, 12: 2})
        self.assertEqual(given, {11: 2, 12: 2})

    def test_b5_requiere_permiso_para_registrar_y_cerrar_incidencias(self):
        op_id = self.plan()
        employee = self.api_client(self.employee)
        self.assertEqual(employee.post(
            self.endpoint(op_id, "registrar-diferencia-llegada"), {
                "receiver_name": "Otro",
                "observations": "Falta un libro de esta entrega",
                "counts": [{"line_id": 1, "counted": 0}],
            }, format="json",
        ).status_code, 403)
        self.assertEqual(employee.post(
            self.endpoint(op_id, "resolver-diferencia-llegada"), {
                "incident_id": 1,
                "resolution_note": "Una validación no autorizada",
                "counts": [{"line_id": 1, "counted": 0}],
            }, format="json",
        ).status_code, 403)

    def test_supervisor_corrige_feria_generica_sin_mover_stock_ni_tocar_lotes(self):
        from warehouse.transfers import posiciones_lotes

        operation_id = self.plan()
        generic = WarehouseLocation.objects.create(
            code="B4-GENERIC-FAIR", name="ALMACEN FERIA HISTORICO",
            kind=WarehouseLocation.Kind.FAIR,
        )
        op = DistributionOperation.objects.get(pk=operation_id)
        op.destination = generic
        op.save(update_fields=["destination", "updated_at"])
        client = self.api_client()
        reserved = client.post(
            self.endpoint(operation_id, "reservar"), {}, format="json",
        )
        self.assertEqual(reserved.status_code, 201, reserved.data)
        counted = client.post(
            self.endpoint(operation_id, "confirmar-preparacion"),
            {"counts": [{
                "reservation_id": row["id"], "counted": row["quantity"],
            } for row in reserved.data["reservations"]]}, format="json",
        )
        self.assertEqual(counted.status_code, 200, counted.data)
        initial_stock = posiciones_lotes(self.entries)
        initial_lots = list(
            DistributionStockReservation.objects.filter(operation_id=operation_id)
            .values_list("pk", "stock_entry_id", "quantity", "counted_quantity", "status"),
        )
        endpoint = self.endpoint(operation_id, "corregir-destino-feria")
        payload = {
            "destination_id": self.fair.pk,
            "reason": "Se identificó el evento escolar real que recibirá los libros.",
            "fair_verified_for_delivery": True,
        }
        denied = self.api_client(self.employee).post(endpoint, payload, format="json")
        self.assertEqual(denied.status_code, 403, denied.data)
        bad_generic = client.post(endpoint, {
            "destination_id": generic.pk,
            "reason": "Intento de conservar un destino de feria genérico.",
            "fair_verified_for_delivery": True,
        }, format="json")
        self.assertEqual(bad_generic.status_code, 400, bad_generic.data)
        short = client.post(endpoint, {
            "destination_id": self.fair.pk, "reason": "cambio",
            "fair_verified_for_delivery": True,
        }, format="json")
        self.assertEqual(short.status_code, 400, short.data)
        unchecked = client.post(endpoint, {
            **payload, "fair_verified_for_delivery": False,
        }, format="json")
        self.assertEqual(unchecked.status_code, 400, unchecked.data)
        updated = client.post(endpoint, payload, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["destination_id"], self.fair.pk)
        self.assertIsNotNone(updated.data["destination_fair_event_id"])
        self.assertEqual(updated.data["status"], "prepared")
        self.assertEqual(DistributionOperation.objects.get(pk=operation_id).source_id, self.main.pk)
        self.assertEqual(posiciones_lotes(self.entries), initial_stock)
        self.assertEqual(list(
            DistributionStockReservation.objects.filter(operation_id=operation_id)
            .values_list("pk", "stock_entry_id", "quantity", "counted_quantity", "status"),
        ), initial_lots)
        event = DistributionOperation.objects.get(pk=operation_id).events.last()
        self.assertEqual(event.action, "fair_destination_fixed")
        self.assertEqual(event.previous["destination_id"], generic.pk)
        self.assertEqual(event.current["destination_id"], self.fair.pk)
        self.assertEqual(
            client.post(endpoint, payload, format="json").status_code, 400,
        )
        doc = client.post(
            self.endpoint(operation_id, "documento-interno"),
            {"idempotency_key": str(uuid4())}, format="json",
        )
        self.assertEqual(doc.status_code, 201, doc.data)
        self.assertEqual(doc.data["destination_id"], self.fair.pk)
        self.assertEqual(
            client.post(endpoint, payload, format="json").status_code, 400,
        )
        self.assertEqual(posiciones_lotes(self.entries), initial_stock)

    def test_no_corrige_destino_generico_de_entrega_sin_preparar(self):
        operation_id = self.plan()
        generic = WarehouseLocation.objects.create(
            code="B4-GEN-UNPREP", name="FERIA HISTORICA PREPARACION",
            kind=WarehouseLocation.Kind.FAIR,
        )
        record = DistributionOperation.objects.get(pk=operation_id)
        record.destination = generic
        record.save(update_fields=["destination", "updated_at"])
        response = self.api_client().post(
            self.endpoint(operation_id, "corregir-destino-feria"), {
                "destination_id": self.fair.pk,
                "reason": "No debe aplicar una corrección supervisada a planificación.",
                "fair_verified_for_delivery": True,
            }, format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            DistributionOperation.objects.get(pk=operation_id).destination_id,
            generic.pk,
        )

    def test_feria_especifica_no_mezcla_colegios_ajenos(self):
        """Un depósito de feria por colegio; evita la mezcla vista en la demo."""
        from crm.models import School

        operation_id = self.plan()
        alien_school = School.objects.create(
            name="OTRO COLEGIO DE CONTROL",
        )
        DistributionOperation.objects.create(
            idempotency_key=uuid4(), adoption=self.adopcion,
            school=alien_school, source=self.main, destination=self.fair,
            original_mode="", mode=DistributionOperation.Mode.FAIR,
            operation_name="Feria ajena de ensayo",
            responsible_name="Operador de ensayo", created_by=self.user,
        )
        client = self.api_client()
        blocked_new = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            {
                "idempotency_key": str(uuid4()),
                "adoption_id": self.adopcion.pk, "mode": "fair",
                "source_id": self.main.pk, "destination_id": self.fair.pk,
                "operation_name": "Otro envío a destino ajeno",
                "responsible_name": "Responsable de ensayo",
                "items": [{
                    "product_id": item.product_id, "quantity": 1,
                } for item in self.adopcion.items.order_by("pk")],
            }, format="json",
        )
        self.assertEqual(blocked_new.status_code, 400, blocked_new.data)
        self.assertIn("otro colegio", str(blocked_new.data).lower())

        reserved = client.post(
            self.endpoint(operation_id, "reservar"), {}, format="json",
        )
        self.assertEqual(reserved.status_code, 201, reserved.data)
        prepared = client.post(
            self.endpoint(operation_id, "confirmar-preparacion"),
            {"counts": [{
                "reservation_id": row["id"], "counted": row["quantity"],
            } for row in reserved.data["reservations"]]}, format="json",
        )
        self.assertEqual(prepared.status_code, 200, prepared.data)
        doc = client.post(
            self.endpoint(operation_id, "documento-interno"),
            {"idempotency_key": str(uuid4())}, format="json",
        )
        self.assertEqual(doc.status_code, 400, doc.data)
        self.assertIn("otro colegio", str(doc.data).lower())
        self.assertEqual(DistributionDispatch.objects.count(), 0)
        self.assertEqual(
            DistributionOperation.objects.get(pk=operation_id).status,
            DistributionOperation.Status.PREPARED,
        )

    def test_excepcion_legal_solo_jefatura_y_sustento_completo(self):
        from warehouse.distribution_dispatch import confirmar_salida

        operation_id = self.plan()
        client = self.api_client()
        reserved = client.post(
            self.endpoint(operation_id, "reservar"), {}, format="json",
        )
        self.assertEqual(reserved.status_code, 201, reserved.data)
        prepared = client.post(
            self.endpoint(operation_id, "confirmar-preparacion"), {
                "counts": [{
                    "reservation_id": row["id"], "counted": row["quantity"],
                } for row in reserved.data["reservations"]],
            }, format="json",
        )
        self.assertEqual(prepared.status_code, 200, prepared.data)
        doc = client.post(
            self.endpoint(operation_id, "documento-interno"),
            {"idempotency_key": str(uuid4())}, format="json",
        )
        self.assertEqual(doc.status_code, 201, doc.data)
        justification = (
            "Caso legal excepcional previamente evaluado por el responsable "
            "tributario y documentado con sustento de la operación de prueba."
        )
        with self.assertRaisesMessage(DjangoValidationError, "Solo Jefatura"):
            confirmar_salida(
                operation_id, self.employee,
                document_basis=DistributionDispatch.Evidence.EXCEPTION,
                exemption=justification,
            )
        with self.assertRaisesMessage(DjangoValidationError, "mínimo 60 caracteres"):
            confirmar_salida(
                operation_id, self.user,
                document_basis=DistributionDispatch.Evidence.EXCEPTION,
                exemption="asdasdas asdasdas asdasdas asdasdas",
            )
        self.assertEqual(
            DistributionDispatch.objects.get(operation_id=operation_id).status,
            DistributionDispatch.Status.DOCUMENTED,
        )
