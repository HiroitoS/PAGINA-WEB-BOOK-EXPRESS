"""Pruebas P-08.2: saldo por ubicación, cortesías, idempotencia y permisos."""
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from catalog.models import Product, Provider
from crm.models import School, Campaign
from purchasing.models import PurchaseOrder, PurchaseOrderItem
from warehouse.models import GoodsReceipt, StockEntry, StockTransfer, StockTransferBatch, WarehouseLocation
from warehouse.receiving import crear_borrador_recepcion, validar_recepcion
from warehouse.stock_movements import registrar_cortesia, saldo_entrada
from warehouse.transfers import registrar_traslado, saldo_en_ubicacion


class StockTransferTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(
            username="transfer-admin", email="transfer@example.test", password="dummy",
        )
        cls.employee = get_user_model().objects.create_user(
            username="transfer-employee", password="dummy",
        )
        cls.school = School.objects.create(name="Colegio de traslado")
        cls.provider = Provider.objects.create(name="Editorial traslado")
        cls.product = Product.objects.create(name="Libro para traslado", code="TRA-001", provider=cls.provider)
        cls.campaign = Campaign.objects.create(
            code="TRF-2027", name="Campaña traslado 2027", year=2027, created_by=cls.actor,
        )
        cls.order = PurchaseOrder.objects.create(
            origin=PurchaseOrder.Origin.MANUAL,
            provider=cls.provider, school=cls.school, campaign=cls.campaign,
            provider_name_snapshot=cls.provider.name, school_name_snapshot=cls.school.name,
            campaign_name_snapshot=cls.campaign.name,
            created_by=cls.actor, status=PurchaseOrder.Status.SENT, sent_at=timezone.now(),
        )
        cls.order_item = PurchaseOrderItem.objects.create(
            order=cls.order, product=cls.product,
            product_name_snapshot=cls.product.name,
            quantity_ordered=10, unit_supplier_cost=Decimal("25.00"),
        )
        cls.main = WarehouseLocation.objects.create(
            code="TRF-MAIN", name="Principal de pruebas", kind=WarehouseLocation.Kind.MAIN,
        )
        cls.store = WarehouseLocation.objects.create(
            code="TRF-STORE", name="Tienda de pruebas", kind=WarehouseLocation.Kind.STORE,
        )

    def setUp(self):
        receipt = crear_borrador_recepcion(
            actor=self.actor, provider_id=self.provider.pk,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number="T-TRF-001", received_on=timezone.localdate(),
            lines=[{
                "order_item_id": self.order_item.pk, "quantity_documented": 10,
                "quantity_arrived": 12, "quantity_accepted": 10,
                "quantity_extra": 2, "quantity_observed": 0,
            }],
        )
        validar_recepcion(actor=self.actor, receipt_id=receipt.pk)
        self.entry = StockEntry.objects.get(receipt_line__receipt=receipt)

    def client_as(self, actor):
        client = APIClient()
        client.force_authenticate(user=actor)
        return client

    def test_traslado_no_modifica_global_ni_reingresa_lote(self):
        url = "/api/admin/erp/almacen/traslados/"
        payload = {
            "stock_entry_id": self.entry.pk,
            "source_id": self.main.pk, "destination_id": self.store.pk,
            "quantity": 5, "idempotency_key": str(uuid4()), "notes": "Feria escolar",
            "entrega_confirmada": True,
        }
        client = self.client_as(self.actor)
        response = client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(saldo_en_ubicacion(self.entry, self.main.pk), 7)
        self.assertEqual(saldo_en_ubicacion(self.entry, self.store.pk), 5)
        self.assertEqual(saldo_entrada(self.entry), 12)
        self.assertEqual(StockEntry.objects.count(), 1)
        second = client.post(url, payload, format="json")
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(StockTransfer.objects.count(), 1)
        summary = client.get("/api/admin/erp/almacen/ubicaciones/resumen-ubicaciones/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data["global"]["available"], 12)

    def test_sobregiro_y_salida_duplicada_son_rechazados(self):
        key = uuid4()
        registrar_traslado(
            actor=self.actor, stock_entry_id=self.entry.pk, source_id=self.main.pk,
            destination_id=self.store.pk, quantity=10, idempotency_key=key, entrega_confirmada=True,
        )
        response = self.client_as(self.actor).post(
            "/api/admin/erp/almacen/traslados/", {
                "stock_entry_id": self.entry.pk, "source_id": self.main.pk,
                "destination_id": self.store.pk, "quantity": 3,
                "idempotency_key": str(uuid4()), "entrega_confirmada": True,
            }, format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(StockTransfer.objects.count(), 1)

    def test_cortesia_no_puede_consumir_stock_trasladado(self):
        registrar_traslado(
            actor=self.actor, stock_entry_id=self.entry.pk, source_id=self.main.pk,
            destination_id=self.store.pk, quantity=11, idempotency_key=uuid4(), entrega_confirmada=True,
        )
        result = self.client_as(self.actor).post(
            "/api/admin/erp/almacen/inventario/cortesias/", {
                "stock_entry_id": self.entry.pk, "school_id": self.school.pk,
                "quantity": 2, "recipient_name": "Directora",
                "recipient_role": "Directora", "idempotency_key": str(uuid4()),
            }, format="json",
        )
        self.assertEqual(result.status_code, 400, result.data)

    def test_permiso_traslados_protegido(self):
        result = self.client_as(self.employee).post(
            "/api/admin/erp/almacen/traslados/", {
                "stock_entry_id": self.entry.pk, "source_id": self.main.pk,
                "destination_id": self.store.pk, "quantity": 1,
                "idempotency_key": str(uuid4()), "entrega_confirmada": True,
            }, format="json",
        )
        self.assertEqual(result.status_code, 403)

    def test_retorno_parcial_desde_tienda_conserva_totales(self):
        registrar_traslado(
            actor=self.actor, stock_entry_id=self.entry.pk,
            source_id=self.main.pk, destination_id=self.store.pk,
            quantity=6, idempotency_key=uuid4(), entrega_confirmada=True,
        )
        registrar_traslado(
            actor=self.actor, stock_entry_id=self.entry.pk,
            source_id=self.store.pk, destination_id=self.main.pk,
            quantity=2, idempotency_key=uuid4(), entrega_confirmada=True,
        )
        self.assertEqual(saldo_en_ubicacion(self.entry, self.main.pk), 8)
        self.assertEqual(saldo_en_ubicacion(self.entry, self.store.pk), 4)
        self.assertEqual(saldo_entrada(self.entry), 12)

    def test_no_permite_anotar_mercaderia_que_sigue_en_camino(self):
        result = self.client_as(self.actor).post(
            "/api/admin/erp/almacen/traslados/", {
                "stock_entry_id": self.entry.pk,
                "source_id": self.main.pk, "destination_id": self.store.pk,
                "quantity": 2, "idempotency_key": str(uuid4()),
                "entrega_confirmada": False,
            }, format="json",
        )
        self.assertEqual(result.status_code, 400, result.data)
        self.assertEqual(StockTransfer.objects.count(), 0)

    def _crear_guia_dos_productos(self):
        extra_product = Product.objects.create(
            name="Segundo libro para traslado", code=f"TRA-B-{uuid4().hex[:10]}",
            provider=self.provider,
        )
        extra_order = PurchaseOrder.objects.create(
            origin=PurchaseOrder.Origin.MANUAL, provider=self.provider,
            school=self.school, campaign=self.campaign,
            provider_name_snapshot=self.provider.name,
            school_name_snapshot=self.school.name,
            campaign_name_snapshot=self.campaign.name,
            created_by=self.actor, status=PurchaseOrder.Status.SENT,
            sent_at=timezone.now(),
        )
        lines = []
        for product, qty in [(self.product, 4), (extra_product, 6)]:
            order_item = PurchaseOrderItem.objects.create(
                order=extra_order, product=product,
                product_name_snapshot=product.name,
                quantity_ordered=qty, unit_supplier_cost=Decimal("25.00"),
            )
            lines.append({
                "order_item_id": order_item.pk,
                "quantity_documented": qty,
                "quantity_arrived": qty,
                "quantity_accepted": qty,
                "quantity_extra": 0,
                "quantity_observed": 0,
            })
        receipt = crear_borrador_recepcion(
            actor=self.actor, provider_id=self.provider.pk,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number=f"TRF-BATCH-{uuid4().hex[:12]}",
            received_on=timezone.localdate(), lines=lines,
        )
        validar_recepcion(actor=self.actor, receipt_id=receipt.pk)
        entries = list(StockEntry.objects.filter(
            receipt_line__receipt=receipt,
        ).order_by("pk"))
        return receipt, entries

    def test_traslado_guia_completa_es_atomico_y_reintentable(self):
        receipt, entries = self._crear_guia_dos_productos()
        payload = {
            "receipt_id": receipt.pk, "source_id": self.main.pk,
            "destination_id": self.store.pk,
            "entrega_confirmada": True,
            "idempotency_key": str(uuid4()),
            "notes": "Feria, guía completa",
            "items": [
                {"stock_entry_id": entry.pk, "quantity": available}
                for entry, available in zip(entries, [4, 6])
            ],
        }
        client = self.client_as(self.actor)
        result = client.get(
            "/api/admin/erp/almacen/traslados/guia/",
            {"receipt_id": receipt.pk, "source_id": self.main.pk},
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(len(result.data["results"]), 2)
        first = client.post(
            "/api/admin/erp/almacen/traslados/por-guia/",
            payload, format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["count"], 2)
        for entry in entries:
            self.assertEqual(saldo_en_ubicacion(entry, self.main.pk), 0)
        self.assertEqual(sum(
            saldo_en_ubicacion(entry, self.store.pk) for entry in entries
        ), 10)
        self.assertEqual(StockTransferBatch.objects.count(), 1)
        before = StockTransfer.objects.count()
        again = client.post(
            "/api/admin/erp/almacen/traslados/por-guia/",
            payload, format="json",
        )
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(StockTransfer.objects.count(), before)

    def test_traslado_guia_falla_completo_si_un_lote_no_tiene_saldo(self):
        receipt, entries = self._crear_guia_dos_productos()
        result = self.client_as(self.actor).post(
            "/api/admin/erp/almacen/traslados/por-guia/",
            {
                "receipt_id": receipt.pk, "source_id": self.main.pk,
                "destination_id": self.store.pk,
                "entrega_confirmada": True,
                "idempotency_key": str(uuid4()),
                "items": [
                    {"stock_entry_id": entries[0].pk, "quantity": 2},
                    {"stock_entry_id": entries[1].pk, "quantity": 99},
                ],
            }, format="json",
        )
        self.assertEqual(result.status_code, 400, result.data)
        self.assertEqual(StockTransferBatch.objects.count(), 0)
        self.assertEqual(StockTransfer.objects.count(), 0)
        self.assertEqual(saldo_en_ubicacion(entries[0], self.main.pk), 4)
        self.assertEqual(saldo_en_ubicacion(entries[1], self.main.pk), 6)

    def test_traslado_guia_no_acepta_lote_de_otra_guia(self):
        receipt, entries = self._crear_guia_dos_productos()
        result = self.client_as(self.actor).post(
            "/api/admin/erp/almacen/traslados/por-guia/",
            {
                "receipt_id": receipt.pk, "source_id": self.main.pk,
                "destination_id": self.store.pk,
                "entrega_confirmada": True,
                "idempotency_key": str(uuid4()),
                "items": [
                    {"stock_entry_id": entries[0].pk, "quantity": 1},
                    {"stock_entry_id": self.entry.pk, "quantity": 1},
                ],
            }, format="json",
        )
        self.assertEqual(result.status_code, 400, result.data)
        self.assertEqual(StockTransfer.objects.count(), 0)
        self.assertEqual(StockTransferBatch.objects.count(), 0)
