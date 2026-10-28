"""P-08.1b: ubicación física inicial, sin agregar stock ni duplicar cortesías."""
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from catalog.models import Product, Provider
from crm.models import Campaign, School
from purchasing.models import PurchaseOrder, PurchaseOrderItem
from warehouse.models import (
    GoodsReceipt, StockEntry, StockEntryLocation, WarehouseLocation,
)
from warehouse.receiving import crear_borrador_recepcion, validar_recepcion
from warehouse.stock_movements import registrar_cortesia, saldo_entrada


class StockEntryLocationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(
            username="stock-location-admin", email="stock-location@example.test",
            password="dummy",
        )
        cls.employee = get_user_model().objects.create_user(
            username="stock-location-employee", password="dummy",
        )
        cls.school = School.objects.create(name="Colegio de ubicación")
        cls.provider = Provider.objects.create(name="Editorial de ubicación")
        cls.product = Product.objects.create(
            name="Texto de ubicación", code="LOC-001", provider=cls.provider,
        )
        cls.campaign = Campaign.objects.create(
            code="LOC-2027", name="Campaña para ubicaciones",
            year=2027, created_by=cls.actor,
        )
        cls.order = PurchaseOrder.objects.create(
            origin=PurchaseOrder.Origin.MANUAL,
            provider=cls.provider, school=cls.school, campaign=cls.campaign,
            provider_name_snapshot=cls.provider.name,
            school_name_snapshot=cls.school.name,
            campaign_name_snapshot=cls.campaign.name,
            created_by=cls.actor, status=PurchaseOrder.Status.SENT,
            sent_at=timezone.now(),
        )
        cls.order_item = PurchaseOrderItem.objects.create(
            order=cls.order, product=cls.product,
            product_name_snapshot=cls.product.name,
            quantity_ordered=10, unit_supplier_cost=Decimal("25.00"),
        )

    def recepcionar(self):
        receipt = crear_borrador_recepcion(
            actor=self.actor, provider_id=self.provider.pk,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number="L-LOC-001", received_on=timezone.localdate(),
            lines=[{
                "order_item_id": self.order_item.pk,
                "quantity_documented": 10,
                "quantity_arrived": 12,
                "quantity_accepted": 10,
                "quantity_extra": 2,
                "quantity_observed": 0,
            }],
        )
        validar_recepcion(actor=self.actor, receipt_id=receipt.pk)
        return receipt, StockEntry.objects.get(receipt_line__receipt=receipt)

    def principal(self):
        return WarehouseLocation.objects.create(
            name="Almacén central", code="MAIN-LOC-TEST",
            kind=WarehouseLocation.Kind.MAIN,
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_nueva_recepcion_se_asigna_solo_al_principal_activo(self):
        main = self.principal()
        receipt, entry = self.recepcionar()
        assigned = StockEntryLocation.objects.get(stock_entry=entry)
        self.assertEqual(assigned.location_id, main.pk)
        self.assertEqual(assigned.origin, StockEntryLocation.Origin.RECEIPT)
        self.assertEqual(assigned.available_at_assignment, 12)
        self.assertEqual(assigned.observed_at_assignment, 0)
        self.assertEqual(StockEntry.objects.count(), 1)
        response = self.client_as(self.actor).get(
            "/api/admin/erp/almacen/ubicaciones/resumen-ubicaciones/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["global"]["available"], 12)
        self.assertEqual(response.data["unassigned"]["available"], 0)
        self.assertEqual(response.data["locations"][0]["available"], 12)
        validar_again = self.client_as(self.actor).post(
            "/api/admin/erp/almacen/inventario/registrar-entrada/",
            {"receipt_id": receipt.pk}, format="json",
        )
        self.assertEqual(validar_again.status_code, 200, validar_again.data)
        self.assertEqual(StockEntry.objects.count(), 1)
        self.assertEqual(StockEntryLocation.objects.count(), 1)

    def test_stock_historico_requiere_confirmacion_y_no_duplica(self):
        _, entry = self.recepcionar()  # Sin almacén configurado previamente.
        self.assertFalse(StockEntryLocation.objects.filter(stock_entry=entry).exists())
        registrar_cortesia(
            actor=self.actor, stock_entry_id=entry.pk, school_id=self.school.pk,
            quantity=2, recipient_name="Directora", recipient_role="Dirección",
            idempotency_key=uuid4(),
        )
        self.assertEqual(saldo_entrada(entry), 10)
        main = self.principal()
        client = self.client_as(self.actor)
        pending = client.get("/api/admin/erp/almacen/ubicaciones/pendientes-asignacion/")
        self.assertEqual(pending.status_code, 200, pending.data)
        self.assertEqual(pending.data["count"], 1)
        self.assertEqual(pending.data["results"][0]["available"], 10)

        url = f"/api/admin/erp/almacen/ubicaciones/{main.pk}/conciliar/"
        invalid = client.post(url, {
            "entry_ids": [entry.pk], "confirmado_fisicamente": False,
        }, format="json")
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertEqual(StockEntryLocation.objects.count(), 0)

        payload = {"entry_ids": [entry.pk], "confirmado_fisicamente": True}
        first = client.post(url, payload, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["assigned"], 1)
        assigned = StockEntryLocation.objects.get(stock_entry=entry)
        self.assertEqual(assigned.available_at_assignment, 10)
        self.assertEqual(assigned.origin, StockEntryLocation.Origin.RECONCILIATION)
        repeat = client.post(url, payload, format="json")
        self.assertEqual(repeat.status_code, 200, repeat.data)
        self.assertEqual(repeat.data["assigned"], 0)
        self.assertEqual(StockEntry.objects.count(), 1)
        self.assertEqual(StockEntryLocation.objects.count(), 1)
        summary = client.get("/api/admin/erp/almacen/ubicaciones/resumen-ubicaciones/")
        self.assertEqual(summary.data["global"]["available"], 10)
        self.assertEqual(summary.data["locations"][0]["available"], 10)
        self.assertEqual(summary.data["unassigned"]["available"], 0)

    def test_lote_ya_conciliado_no_puede_asignarse_a_otro_lugar(self):
        _, entry = self.recepcionar()
        main = self.principal()
        store = WarehouseLocation.objects.create(
            code="STORE-LOC-TEST", name="Tienda", kind=WarehouseLocation.Kind.STORE,
        )
        client = self.client_as(self.actor)
        payload = {"entry_ids": [entry.pk], "confirmado_fisicamente": True}
        ok = client.post(
            f"/api/admin/erp/almacen/ubicaciones/{main.pk}/conciliar/",
            payload, format="json",
        )
        self.assertEqual(ok.status_code, 200, ok.data)
        rejected = client.post(
            f"/api/admin/erp/almacen/ubicaciones/{store.pk}/conciliar/",
            payload, format="json",
        )
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertEqual(StockEntryLocation.objects.get(stock_entry=entry).location_id, main.pk)

    def test_varios_principales_bloquean_la_validacion_sin_duplicar_stock(self):
        self.principal()
        WarehouseLocation.objects.create(
            code="MAIN-DUPLICATE", name="Principal duplicado",
            kind=WarehouseLocation.Kind.MAIN,
        )
        with self.assertRaises(ValidationError):
            self.recepcionar()
        self.assertEqual(StockEntry.objects.count(), 0)
        self.assertEqual(StockEntryLocation.objects.count(), 0)

    def test_sin_permisos_no_se_puede_confirmar_ubicacion(self):
        _, entry = self.recepcionar()
        main = self.principal()
        response = self.client_as(self.employee).post(
            f"/api/admin/erp/almacen/ubicaciones/{main.pk}/conciliar/",
            {"entry_ids": [entry.pk], "confirmado_fisicamente": True},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(StockEntryLocation.objects.count(), 0)
