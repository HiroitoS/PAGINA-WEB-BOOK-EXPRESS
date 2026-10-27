"""Pruebas P-07.3: cortesías sin duplicar recepciones ni permitir stock negativo."""
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
from warehouse.models import GoodsReceipt, StockEntry, StockMovement
from warehouse.receiving import crear_borrador_recepcion, validar_recepcion
from warehouse.stock_movements import registrar_cortesia, saldo_entrada


class StockCourtesyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(
            username="stock-courtesy-admin", email="stock-courtesy@example.test", password="dummy",
        )
        cls.school = School.objects.create(name="Colegio de pruebas")
        cls.other_school = School.objects.create(name="Colegio ajeno")
        cls.provider = Provider.objects.create(name="Editorial de pruebas cortesía")
        cls.product = Product.objects.create(
            name="Libro de cortesía", code="CORT-001", provider=cls.provider,
        )
        cls.campaign = Campaign.objects.create(
            code="CORT-2027", name="Campaña cortesías", year=2027,
            created_by=cls.actor,
        )
        cls.order = PurchaseOrder.objects.create(
            origin=PurchaseOrder.Origin.MANUAL,
            provider=cls.provider,
            school=cls.school,
            campaign=cls.campaign,
            provider_name_snapshot=cls.provider.name,
            school_name_snapshot=cls.school.name,
            campaign_name_snapshot=cls.campaign.name,
            created_by=cls.actor, status=PurchaseOrder.Status.SENT,
            sent_at=timezone.now(),
        )
        cls.order_item = PurchaseOrderItem.objects.create(
            order=cls.order, product=cls.product,
            product_name_snapshot=cls.product.name,
            quantity_ordered=10, unit_supplier_cost=Decimal("30.00"),
        )
        receipt = crear_borrador_recepcion(
            actor=cls.actor, provider_id=cls.provider.pk,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number="COR-001", received_on=timezone.localdate(),
            lines=[{
                "order_item_id": cls.order_item.pk,
                "quantity_documented": 10,
                "quantity_arrived": 12,
                "quantity_accepted": 10,
                "quantity_observed": 0,
                "quantity_extra": 2,
            }],
        )
        validar_recepcion(actor=cls.actor, receipt_id=receipt.pk)
        cls.entry = StockEntry.objects.get(receipt_line__receipt=receipt)

    def data(self, **override):
        data = {
            "actor": self.actor,
            "stock_entry_id": self.entry.pk,
            "school_id": self.school.pk,
            "quantity": 3,
            "recipient_name": "Dirección del colegio",
            "recipient_role": "Directora",
            "notes": "Cortesía de directivo",
            "idempotency_key": uuid4(),
        }
        data.update(override)
        return data

    def test_salida_descontada_y_valorizada_sin_tocar_la_recepcion(self):
        move, created = registrar_cortesia(**self.data())
        self.assertTrue(created)
        self.assertEqual(move.quantity_delta, -3)
        self.assertEqual(move.unit_cost_snapshot, Decimal("30.00"))
        self.assertEqual(saldo_entrada(self.entry), 9)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.quantity_available, 12)
        self.assertEqual(StockEntry.objects.count(), 1)

        client = APIClient()
        client.force_authenticate(self.actor)
        stock = client.get("/api/admin/erp/almacen/inventario/existencias/")
        self.assertEqual(stock.status_code, 200)
        self.assertEqual(stock.data[0]["available"], 9)
        self.assertEqual(stock.data[0]["physical"], 9)
        self.assertEqual(stock.data[0]["gross_conforming_received"], 12)
        summary = client.get("/api/admin/erp/almacen/inventario/resumen/")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data["outflows"], 3)
        self.assertEqual(summary.data["conforming"], 9)
        self.assertEqual(Decimal(summary.data["value_reference"]), Decimal("270.00"))

    def test_idempotencia_y_colision_de_clave(self):
        payload = self.data()
        first, created = registrar_cortesia(**payload)
        same, created_again = registrar_cortesia(**payload)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, same.pk)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(saldo_entrada(self.entry), 9)
        with self.assertRaises(ValidationError):
            registrar_cortesia(**{**payload, "quantity": 2})

    def test_impide_salida_de_colegio_ajeno_y_saldo_insuficiente(self):
        with self.assertRaises(ValidationError):
            registrar_cortesia(**self.data(school_id=self.other_school.pk))
        with self.assertRaises(ValidationError):
            registrar_cortesia(**self.data(quantity=13))
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_api_alta_y_reintento(self):
        client = APIClient()
        client.force_authenticate(self.actor)
        payload = {
            "stock_entry_id": self.entry.pk,
            "school_id": self.school.pk,
            "quantity": 2,
            "recipient_name": "Dirección",
            "recipient_role": "Directora",
            "notes": "Cortesía",
            "idempotency_key": str(uuid4()),
        }
        url = "/api/admin/erp/almacen/inventario/cortesias/"
        first = client.post(url, payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        again = client.post(url, payload, format="json")
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(again.data["entry_balance"], 10)
        self.assertEqual(StockMovement.objects.count(), 1)
        history = client.get("/api/admin/erp/almacen/inventario/salidas/")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data[0]["quantity"], 2)
        self.assertEqual(history.data[0]["cost_reference"], "60.00")

    def test_solo_entradas_del_colegio_con_saldo_y_busqueda_paginada(self):
        client = APIClient()
        client.force_authenticate(self.actor)
        url = "/api/admin/erp/almacen/inventario/entradas-disponibles/"
        response = client.get(url, {"q": self.school.name})
        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["net_available"], 12)
        self.assertEqual(rows[0]["school_id"], self.school.pk)

        registrar_cortesia(**self.data(quantity=12))
        empty = client.get(url, {"q": self.school.name})
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.data["count"], 0)


    def test_valorizacion_por_editorial_incluye_adicionales_y_descuenta_cortesias(self):
        client = APIClient()
        client.force_authenticate(self.actor)
        endpoint = "/api/admin/erp/almacen/inventario/resumen-por-editorial/"
        initial = client.get(endpoint)
        self.assertEqual(initial.status_code, 200, initial.data)
        self.assertEqual(len(initial.data), 1)
        row = initial.data[0]
        self.assertEqual(row["editorial_id"], self.provider.pk)
        self.assertEqual(row["physical"], 12)
        self.assertEqual(row["available"], 12)
        self.assertEqual(row["observed"], 0)
        self.assertEqual(row["extra_received"], 2)
        self.assertEqual(Decimal(row["available_value_reference"]), Decimal("360.00"))
        self.assertEqual(Decimal(row["physical_value_reference"]), Decimal("360.00"))
        self.assertTrue(row["valuation_complete"])

        registrar_cortesia(**self.data(quantity=3))
        after = client.get(endpoint)
        self.assertEqual(after.status_code, 200, after.data)
        row = after.data[0]
        self.assertEqual(row["available"], 9)
        self.assertEqual(row["physical"], 9)
        self.assertEqual(row["extra_received"], 2)  # Histórico, no se duplica.
        self.assertEqual(Decimal(row["available_value_reference"]), Decimal("270.00"))
        self.assertEqual(Decimal(row["physical_value_reference"]), Decimal("270.00"))
        summary = client.get("/api/admin/erp/almacen/inventario/resumen/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(Decimal(summary.data["physical_value_reference"]), Decimal("270.00"))
        self.assertEqual(Decimal(summary.data["value_reference"]), Decimal("270.00"))


    def test_valorizacion_no_mezcla_editoriales(self):
        segunda = Provider.objects.create(name="Otra editorial para valuación")
        libro = Product.objects.create(
            name="Segundo libro", code="CORT-002", provider=segunda,
        )
        pedido = PurchaseOrder.objects.create(
            origin=PurchaseOrder.Origin.MANUAL,
            provider=segunda, school=self.school, campaign=self.campaign,
            provider_name_snapshot=segunda.name,
            school_name_snapshot=self.school.name,
            campaign_name_snapshot=self.campaign.name,
            created_by=self.actor, status=PurchaseOrder.Status.SENT,
            sent_at=timezone.now(),
        )
        item = PurchaseOrderItem.objects.create(
            order=pedido, product=libro, product_name_snapshot=libro.name,
            quantity_ordered=5, unit_supplier_cost=Decimal("15.00"),
        )
        recepcion = crear_borrador_recepcion(
            actor=self.actor, provider_id=segunda.pk,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number="COR-002", received_on=timezone.localdate(),
            lines=[{
                "order_item_id": item.pk, "quantity_documented": 5,
                "quantity_arrived": 5, "quantity_accepted": 5,
                "quantity_observed": 0, "quantity_extra": 0,
            }],
        )
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        client = APIClient()
        client.force_authenticate(self.actor)
        editorial = client.get("/api/admin/erp/almacen/inventario/resumen-por-editorial/")
        self.assertEqual(editorial.status_code, 200, editorial.data)
        self.assertEqual(len(editorial.data), 2)
        por_id = {row["editorial_id"]: row for row in editorial.data}
        self.assertEqual(Decimal(por_id[self.provider.pk]["physical_value_reference"]), Decimal("360.00"))
        self.assertEqual(Decimal(por_id[segunda.pk]["physical_value_reference"]), Decimal("75.00"))
        summary = client.get("/api/admin/erp/almacen/inventario/resumen/")
        self.assertEqual(Decimal(summary.data["physical_value_reference"]), Decimal("435.00"))

    def test_valor_fisico_separa_observados_del_stock_disponible(self):
        # Simula una entrada de 12 libros, 10 conformes y 2 observados.
        StockEntry.objects.filter(pk=self.entry.pk).update(
            quantity_available=10, quantity_quarantined=2,
        )
        client = APIClient()
        client.force_authenticate(self.actor)
        registrar_cortesia(**self.data(quantity=2))
        editorial = client.get("/api/admin/erp/almacen/inventario/resumen-por-editorial/")
        self.assertEqual(editorial.status_code, 200, editorial.data)
        row = editorial.data[0]
        self.assertEqual(row["available"], 8)
        self.assertEqual(row["observed"], 2)
        self.assertEqual(row["physical"], 10)
        self.assertEqual(Decimal(row["available_value_reference"]), Decimal("240.00"))
        self.assertEqual(Decimal(row["observed_value_reference"]), Decimal("60.00"))
        self.assertEqual(Decimal(row["physical_value_reference"]), Decimal("300.00"))
        summary = client.get("/api/admin/erp/almacen/inventario/resumen/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(Decimal(summary.data["observed_value_reference"]), Decimal("60.00"))
        self.assertEqual(Decimal(summary.data["physical_value_reference"]), Decimal("300.00"))
        self.assertTrue(summary.data["physical_valuation_complete"])

    def test_editorial_identifica_unidades_sin_costo_y_no_finge_valor_total(self):
        StockEntry.objects.filter(pk=self.entry.pk).update(unit_cost_snapshot=None)
        client = APIClient()
        client.force_authenticate(self.actor)
        editorial = client.get("/api/admin/erp/almacen/inventario/resumen-por-editorial/")
        self.assertEqual(editorial.status_code, 200, editorial.data)
        row = editorial.data[0]
        self.assertEqual(row["unvalued_available_units"], 12)
        self.assertFalse(row["valuation_complete"])
        summary = client.get("/api/admin/erp/almacen/inventario/resumen/")
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertFalse(summary.data["physical_valuation_complete"])

    def test_usuario_sin_permiso_no_puede_registrar_cortesia(self):
        employee = get_user_model().objects.create_user(
            username="sin-permiso-cortesia", password="dummy",
        )
        client = APIClient()
        client.force_authenticate(employee)
        response = client.post("/api/admin/erp/almacen/inventario/cortesias/", {
            "stock_entry_id": self.entry.pk,
            "school_id": self.school.pk,
            "quantity": 1,
            "recipient_name": "Directora",
            "recipient_role": "Dirección",
            "idempotency_key": str(uuid4()),
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(StockMovement.objects.count(), 0)
