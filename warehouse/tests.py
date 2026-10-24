"""Pruebas del flujo de recepción parcial sin registrar stock ni pagos."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from catalog.models import Product, Provider
from crm.models import Campaign
from purchasing.models import PurchaseOrder, PurchaseOrderItem
from warehouse.models import GoodsReceipt, GoodsReceiptEvent
from warehouse.receiving import (
    actualizar_borrador_recepcion, crear_borrador_recepcion,
    saldos_pedido, validar_recepcion,
)


class RecepcionMercaderiaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(
            username="almacen-pruebas", email="almacen@example.test", password="prueba"
        )
        cls.editorial = Provider.objects.create(name="Editorial de pruebas")
        cls.campania = Campaign.objects.create(
            code="ALMACEN-2027-TEST", name="Campaña almacén",
            year=2027, created_by=cls.actor,
        )
        cls.producto = Product.objects.create(
            name="Libro de prueba", code="ALM-01", provider=cls.editorial,
        )
        cls.pedido = PurchaseOrder.objects.create(
            origin=PurchaseOrder.Origin.MANUAL, provider=cls.editorial,
            campaign=cls.campania, provider_name_snapshot=cls.editorial.name,
            campaign_name_snapshot=cls.campania.name,
            created_by=cls.actor, status=PurchaseOrder.Status.SENT,
            sent_at=timezone.now(),
        )
        cls.item = PurchaseOrderItem.objects.create(
            order=cls.pedido, product=cls.producto,
            product_name_snapshot=cls.producto.name,
            quantity_ordered=100, unit_supplier_cost="25.80",
        )

    def borrador(self, aceptadas, observadas=0, documento="G-001"):
        return crear_borrador_recepcion(
            actor=self.actor,
            provider_id=self.editorial.pk,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number=documento,
            received_on=timezone.localdate(),
            lines=[{
                "order_item_id": self.item.pk,
                "quantity_arrived": aceptadas + observadas,
                "quantity_accepted": aceptadas,
                "quantity_observed": observadas,
            }],
        )

    def test_80_recibidas_20_pendientes_y_segunda_entrega(self):
        primera = self.borrador(80)
        self.assertEqual(self.pedido.status, PurchaseOrder.Status.SENT)
        validar_recepcion(actor=self.actor, receipt_id=primera.pk)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.status, PurchaseOrder.Status.PARTIALLY_RECEIVED)
        datos = saldos_pedido(actor=self.actor, order_id=self.pedido.pk)
        self.assertEqual(datos["productos"][0]["cantidad_aceptada"], 80)
        self.assertEqual(datos["productos"][0]["cantidad_pendiente"], 20)

        segunda = self.borrador(20, documento="G-002")
        validar_recepcion(actor=self.actor, receipt_id=segunda.pk)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.status, PurchaseOrder.Status.RECEIVED)
        datos = saldos_pedido(actor=self.actor, order_id=self.pedido.pk)
        self.assertEqual(datos["productos"][0]["cantidad_pendiente"], 0)
        self.assertEqual(GoodsReceiptEvent.objects.filter(action="validated").count(), 2)

    def test_no_permite_aceptar_mas_de_lo_solicitado(self):
        primero = self.borrador(80)
        validar_recepcion(actor=self.actor, receipt_id=primero.pk)
        segundo = self.borrador(21, documento="G-002")
        with self.assertRaises(ValidationError):
            validar_recepcion(actor=self.actor, receipt_id=segundo.pk)
        segundo.refresh_from_db()
        self.assertEqual(segundo.status, GoodsReceipt.Status.DRAFT)
        self.assertEqual(saldos_pedido(actor=self.actor, order_id=self.pedido.pk)["productos"][0]["cantidad_pendiente"], 20)

    def test_observado_no_se_cuenta_como_aceptado(self):
        recepcion = self.borrador(60, observadas=20)
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        datos = saldos_pedido(actor=self.actor, order_id=self.pedido.pk)
        self.assertEqual(datos["productos"][0]["cantidad_aceptada"], 60)
        self.assertEqual(datos["productos"][0]["cantidad_pendiente"], 40)

    def test_doble_validacion_no_duplica_recepcion(self):
        recepcion = self.borrador(80)
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        with self.assertRaises(ValidationError):
            validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        self.assertEqual(GoodsReceiptEvent.objects.filter(action="validated").count(), 1)

    def test_valida_pertenencia_a_editorial(self):
        otro = Provider.objects.create(name="Editorial diferente")
        with self.assertRaises(ValidationError):
            crear_borrador_recepcion(
                actor=self.actor, provider_id=otro.pk,
                document_type=GoodsReceipt.DocumentType.GUIDE,
                document_number="G-999", received_on=timezone.localdate(),
                lines=[{"order_item_id": self.item.pk, "quantity_arrived": 1,
                        "quantity_accepted": 1, "quantity_observed": 0}],
            )
        self.assertEqual(GoodsReceipt.objects.count(), 0)

    def test_cantidades_no_cuadran_se_rechazan(self):
        with self.assertRaises(ValidationError):
            crear_borrador_recepcion(
                actor=self.actor, provider_id=self.editorial.pk,
                document_type=GoodsReceipt.DocumentType.GUIDE,
                document_number="G-003", received_on=timezone.localdate(),
                lines=[{"order_item_id": self.item.pk, "quantity_arrived": 10,
                        "quantity_accepted": 11, "quantity_observed": 0}],
            )
        self.assertEqual(GoodsReceipt.objects.count(), 0)

    def test_rechaza_actor_sin_permiso(self):
        usuario = get_user_model().objects.create_user(username="sin-permiso-almacen")
        with self.assertRaises(PermissionDenied):
            saldos_pedido(actor=usuario, order_id=self.pedido.pk)

    def test_api_crear_validar_y_consultar_saldos(self):
        client = APIClient()
        client.force_authenticate(self.actor)
        url = "/api/admin/erp/almacen/recepciones/"
        response = client.post(url + "crear/", {
            "provider_id": self.editorial.pk,
            "document_type": "guide",
            "document_number": "G-001",
            "received_on": str(timezone.localdate()),
            "lines": [{
                "order_item_id": self.item.pk, "quantity_arrived": 80,
                "quantity_accepted": 80, "quantity_observed": 0,
            }],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        receipt_id = response.data["id"]
        response = client.post(url + str(receipt_id) + "/validar/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        response = client.get(url + "saldos/?pedido=" + str(self.pedido.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["productos"][0]["cantidad_pendiente"], 20)

    def test_guia_repetida_no_genera_doble_recepcion(self):
        primera = self.borrador(80)
        validar_recepcion(actor=self.actor, receipt_id=primera.pk)
        with self.assertRaises(ValidationError):
            self.borrador(20, documento="g-001")
        self.assertEqual(GoodsReceipt.objects.count(), 1)

    def test_una_guia_puede_incluir_dos_pedidos_de_la_misma_editorial(self):
        segundo = PurchaseOrder.objects.create(
            origin=PurchaseOrder.Origin.MANUAL, provider=self.editorial,
            campaign=self.campania, provider_name_snapshot=self.editorial.name,
            campaign_name_snapshot=self.campania.name, created_by=self.actor,
            status=PurchaseOrder.Status.SENT, sent_at=timezone.now(),
        )
        item_segundo = PurchaseOrderItem.objects.create(
            order=segundo, product=self.producto,
            product_name_snapshot=self.producto.name,
            quantity_ordered=50, unit_supplier_cost="25.80",
        )
        recepcion = crear_borrador_recepcion(
            actor=self.actor, provider_id=self.editorial.pk,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number="G-COMUN", received_on=timezone.localdate(),
            lines=[
                {"order_item_id": self.item.pk, "quantity_arrived": 80,
                 "quantity_accepted": 80, "quantity_observed": 0},
                {"order_item_id": item_segundo.pk, "quantity_arrived": 50,
                 "quantity_accepted": 50, "quantity_observed": 0},
            ],
        )
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        self.pedido.refresh_from_db()
        segundo.refresh_from_db()
        self.assertEqual(self.pedido.status, PurchaseOrder.Status.PARTIALLY_RECEIVED)
        self.assertEqual(segundo.status, PurchaseOrder.Status.RECEIVED)

    def test_editar_borrador_conserva_documento_y_eventos(self):
        recepcion = self.borrador(30)
        actualizada = actualizar_borrador_recepcion(
            actor=self.actor, receipt_id=recepcion.pk,
            provider_id=self.editorial.pk, document_type="guide",
            document_number="G-001", received_on=timezone.localdate(),
            lines=[{
                "order_item_id": self.item.pk, "quantity_arrived": 85,
                "quantity_accepted": 80, "quantity_observed": 5,
            }],
        )
        self.assertEqual(actualizada.lines.count(), 1)
        self.assertEqual(actualizada.lines.first().quantity_accepted, 80)
        self.assertEqual(actualizada.events.filter(action="updated").count(), 1)
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        self.assertEqual(saldos_pedido(actor=self.actor, order_id=self.pedido.pk)["productos"][0]["cantidad_pendiente"], 20)
        with self.assertRaises(ValidationError):
            actualizar_borrador_recepcion(
                actor=self.actor, receipt_id=recepcion.pk, provider_id=self.editorial.pk,
                document_type="guide", document_number="G-001",
                received_on=timezone.localdate(),
                lines=[{"order_item_id": self.item.pk, "quantity_arrived": 20,
                        "quantity_accepted": 20, "quantity_observed": 0}],
            )

    def test_pedidos_pendientes_no_exponen_costos(self):
        client = APIClient()
        client.force_authenticate(self.actor)
        url = "/api/admin/erp/almacen/recepciones/pedidos-pendientes/"
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.data["results"] if "results" in response.data else response.data
        self.assertTrue(any(pedido["id"] == self.pedido.pk for pedido in data))
        detalle = next(pedido for pedido in data if pedido["id"] == self.pedido.pk)
        self.assertEqual(detalle["productos"][0]["pendientes"], 100)
        self.assertNotIn("unit_supplier_cost", str(detalle))
