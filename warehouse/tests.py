"""Pruebas del flujo de recepción parcial sin registrar stock ni pagos."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from catalog.models import Product, Provider
from crm.models import Campaign
from purchasing.models import PurchaseOrder, PurchaseOrderItem
from warehouse.api_serializers import GoodsReceiptSerializer
from warehouse.models import GoodsReceipt, GoodsReceiptEvent, ReceivingIncident, StockEntry
from warehouse.inventory import registrar_entrada_recepcion
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

    def test_conteo_fisico_102_documento_100_con_excedente_conservado(self):
        recepcion = crear_borrador_recepcion(
            actor=self.actor,
            provider_id=self.editorial.pk,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number="G-102",
            received_on=timezone.localdate(),
            notes="Diferencia de dos unidades conservadas en almacén.",
            lines=[{
                "order_item_id": self.item.pk,
                "quantity_documented": 100,
                "quantity_arrived": 102,
                "quantity_accepted": 100,
                "quantity_extra": 2,
                "quantity_observed": 0,
            }],
        )
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        linea = recepcion.lines.get()
        self.assertEqual(linea.quantity_arrived, 102)
        self.assertEqual(linea.quantity_documented, 100)
        self.assertEqual(linea.quantity_extra, 2)
        self.assertEqual(saldos_pedido(actor=self.actor, order_id=self.pedido.pk)["productos"][0]["cantidad_pendiente"], 0)

    def test_incidencias_se_crean_por_faltante_de_guia_y_no_conformes(self):
        recepcion = crear_borrador_recepcion(
            actor=self.actor, provider_id=self.editorial.pk,
            document_type="guide", document_number="G-INC-01",
            received_on=timezone.localdate(),
            lines=[{
                "order_item_id": self.item.pk,
                "quantity_documented": 100,
                "quantity_arrived": 98,
                "quantity_accepted": 95,
                "quantity_observed": 3,
                "quantity_extra": 0,
            }],
        )
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        incidencias = {
            x.kind: x.quantity
            for x in ReceivingIncident.objects.filter(receipt_line__receipt=recepcion)
        }
        self.assertEqual(incidencias, {"shortage": 2, "nonconforming": 3})
        with self.assertRaises(ValidationError):
            validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        self.assertEqual(ReceivingIncident.objects.filter(receipt_line__receipt=recepcion).count(), 2)
        client = APIClient()
        client.force_authenticate(self.actor)
        response = client.get("/api/admin/erp/almacen/incidencias/")
        self.assertEqual(response.status_code, 200)
        registros = response.data.get("results", response.data)
        self.assertEqual(len(registros), 2)

    def test_alerta_liquidacion_identifica_faltantes_y_danados(self):
        recepcion = crear_borrador_recepcion(
            actor=self.actor, provider_id=self.editorial.pk,
            document_type="guide", document_number="G-ALERTA",
            received_on=timezone.localdate(),
            lines=[{
                "order_item_id": self.item.pk, "quantity_documented": 100,
                "quantity_arrived": 98, "quantity_accepted": 95,
                "quantity_observed": 3,
            }],
        )
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        client = APIClient()
        client.force_authenticate(self.actor)
        response = client.get(
            f"/api/admin/erp/almacen/incidencias/alertas-liquidacion/?provider={self.editorial.pk}"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["requires_review"])
        self.assertEqual(response.data["quantities"], {"shortage": 2, "nonconforming": 3})
        self.assertEqual(response.data["open_incidents"], 2)

    def test_incidencias_no_expuestas_a_usuario_sin_permiso(self):
        usuario = get_user_model().objects.create_user(username="sin-incidencias")
        client = APIClient()
        client.force_authenticate(usuario)
        response = client.get("/api/admin/erp/almacen/incidencias/")
        self.assertEqual(response.status_code, 403)

    def test_inventario_ingreso_con_adicionales_no_se_duplica(self):
        recepcion = crear_borrador_recepcion(
            actor=self.actor, provider_id=self.editorial.pk,
            document_type="guide", document_number="G-STOCK",
            received_on=timezone.localdate(),
            lines=[{
                "order_item_id": self.item.pk, "quantity_documented": 100,
                "quantity_arrived": 102, "quantity_accepted": 100,
                "quantity_extra": 2, "quantity_observed": 0,
            }],
        )
        with self.assertRaises(ValidationError):
            registrar_entrada_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        self.assertEqual(StockEntry.objects.filter(receipt_line__receipt=recepcion).count(), 1)
        self.assertEqual(registrar_entrada_recepcion(actor=self.actor, receipt_id=recepcion.pk)["new_entries"], 0)
        entrada = StockEntry.objects.get(receipt_line__receipt=recepcion)
        self.assertEqual((entrada.quantity_available, entrada.quantity_extra, entrada.quantity_quarantined), (102, 2, 0))
        self.assertEqual(StockEntry.objects.count(), 1)
        client = APIClient()
        client.force_authenticate(self.actor)
        detail = client.get("/api/admin/erp/almacen/inventario/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["results"][0]["unit_cost"], "25.80")
        self.assertEqual(detail.data["results"][0]["entry_value"], "2631.60")
        totals = client.get("/api/admin/erp/almacen/inventario/existencias/")
        self.assertEqual(totals.status_code, 200)
        self.assertEqual(totals.data[0]["available"], 102)
        self.assertEqual(totals.data[0]["extra_included"], 2)
        self.assertEqual(totals.data[0]["physical"], 102)


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
                "quantity_documented": 80,
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

    def test_la_misma_guia_de_editoriales_diferentes_es_valida(self):
        primera = self.borrador(20, documento="T001-25200")
        otra_editorial = Provider.objects.create(name="Otra editorial")
        segunda = GoodsReceipt.objects.create(
            provider=otra_editorial,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number="t001-25200",
            received_on=timezone.localdate(),
            created_by=self.actor,
        )
        self.assertNotEqual(primera.provider_id, segunda.provider_id)
        self.assertEqual(GoodsReceipt.objects.count(), 2)

    def test_guia_misma_editorial_se_rechaza_aun_con_otras_mayusculas(self):
        self.borrador(20, documento="T001-25200")
        with self.assertRaises(ValidationError):
            self.borrador(15, documento=" t001-25200 ")
        self.assertEqual(GoodsReceipt.objects.count(), 1)

    def test_indice_de_base_de_datos_bloquea_guia_minuscula_por_orm(self):
        self.borrador(20, documento="T001-25200")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GoodsReceipt.objects.create(
                    provider=self.editorial,
                    document_type=GoodsReceipt.DocumentType.GUIDE,
                    document_number="t001-25200",
                    received_on=timezone.localdate(),
                    created_by=self.actor,
                )
        self.assertEqual(GoodsReceipt.objects.count(), 1)

    def test_correccion_de_borrador_no_puede_duplicar_guia(self):
        primera = self.borrador(30, documento="T001-25200")
        segunda = self.borrador(5, documento="G-099")
        with self.assertRaises(ValidationError):
            actualizar_borrador_recepcion(
                actor=self.actor, receipt_id=segunda.pk,
                provider_id=self.editorial.pk, document_type="guide",
                document_number=" t001-25200 ", received_on=timezone.localdate(),
                lines=[{"order_item_id": self.item.pk, "quantity_arrived": 5,
                        "quantity_accepted": 5, "quantity_observed": 0}],
            )
        segunda.refresh_from_db()
        self.assertEqual(segunda.document_number, "G-099")
        self.assertNotEqual(primera.pk, segunda.pk)

    def test_guia_vacia_no_se_puede_registrar(self):
        with self.assertRaises(ValidationError):
            self.borrador(10, documento="  ")

    def test_semaforo_diferencia_validacion_y_pedido_completo(self):
        primera = self.borrador(80, documento="G-080")
        self.assertEqual(GoodsReceiptSerializer(primera).data["fulfillment_status"], "draft")
        validar_recepcion(actor=self.actor, receipt_id=primera.pk)
        primera.refresh_from_db()
        self.assertEqual(GoodsReceiptSerializer(primera).data["fulfillment_status"], "pending")
        segunda = self.borrador(20, documento="G-020")
        validar_recepcion(actor=self.actor, receipt_id=segunda.pk)
        primera.refresh_from_db()
        segunda.refresh_from_db()
        self.assertEqual(GoodsReceiptSerializer(primera).data["fulfillment_status"], "complete")
        self.assertEqual(GoodsReceiptSerializer(segunda).data["fulfillment_status"], "complete")

    def test_api_exige_cantidad_segun_guia_en_nuevas_recepciones(self):
        client = APIClient()
        client.force_authenticate(self.actor)
        response = client.post(
            "/api/admin/erp/almacen/recepciones/crear/",
            {
                "provider_id": self.editorial.pk,
                "document_type": "guide",
                "document_number": "G-SIN-CANTIDAD",
                "received_on": str(timezone.localdate()),
                "lines": [{
                    "order_item_id": self.item.pk,
                    "quantity_arrived": 5,
                    "quantity_accepted": 5,
                    "quantity_observed": 0,
                }],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(GoodsReceipt.objects.count(), 0)

    def test_api_rechaza_guia_repetida_con_error_de_negocio(self):
        self.borrador(10, documento="T001-25200")
        client = APIClient()
        client.force_authenticate(self.actor)
        response = client.post(
            "/api/admin/erp/almacen/recepciones/crear/",
            {
                "provider_id": self.editorial.pk,
                "document_type": "guide",
                "document_number": "t001-25200",
                "received_on": str(timezone.localdate()),
                "lines": [{
                    "order_item_id": self.item.pk,
                    "quantity_arrived": 5,
                    "quantity_accepted": 5,
                    "quantity_observed": 0,
                }],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(GoodsReceipt.objects.count(), 1)

    def test_api_historial_con_responsables_y_orden_cronologico(self):
        recepcion = self.borrador(30, documento="G-AUDITORIA")
        actualizar_borrador_recepcion(
            actor=self.actor, receipt_id=recepcion.pk,
            provider_id=self.editorial.pk, document_type="guide",
            document_number="G-AUDITORIA", received_on=timezone.localdate(),
            lines=[{
                "order_item_id": self.item.pk, "quantity_arrived": 35,
                "quantity_accepted": 30, "quantity_observed": 5,
            }],
        )
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        client = APIClient()
        client.force_authenticate(self.actor)
        response = client.get(f"/api/admin/erp/almacen/recepciones/{recepcion.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created_by_name"], self.actor.get_username())
        self.assertEqual(response.data["validated_by_name"], self.actor.get_username())
        self.assertIsNotNone(response.data["validated_at"])
        eventos = response.data["events"]
        self.assertEqual([evento["action"] for evento in eventos], [
            "created", "updated", "validated",
        ])
        self.assertTrue(all(
            evento["actor_name"] == self.actor.get_username() and evento["created_at"]
            for evento in eventos
        ))

    def test_api_resumen_acumulado_tras_recepcion_parcial(self):
        primera = self.borrador(80, documento="G-RESUMEN")
        validar_recepcion(actor=self.actor, receipt_id=primera.pk)
        client = APIClient()
        client.force_authenticate(self.actor)
        response = client.get("/api/admin/erp/almacen/recepciones/pedidos-pendientes/")
        self.assertEqual(response.status_code, 200, response.data)
        resultados = response.data["results"] if "results" in response.data else response.data
        pedido = next(item for item in resultados if item["id"] == self.pedido.pk)
        self.assertEqual(pedido["resumen"], {
            "solicitadas": 100,
            "aceptadas": 80,
            "pendientes": 20,
        })
        self.assertEqual(pedido["productos"][0]["aceptadas"], 80)
        self.assertEqual(pedido["productos"][0]["pendientes"], 20)

    def test_seguimiento_muestra_primera_y_segunda_guia_y_saldo_actual(self):
        primera = self.borrador(80, documento="G-PRIMERA")
        validar_recepcion(actor=self.actor, receipt_id=primera.pk)
        segunda = self.borrador(20, documento="G-SEGUNDA")
        validar_recepcion(actor=self.actor, receipt_id=segunda.pk)
        client = APIClient()
        client.force_authenticate(self.actor)
        response = client.get(
            f"/api/admin/erp/almacen/recepciones/{primera.pk}/seguimiento/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["pedidos"]), 1)
        pedido = response.data["pedidos"][0]
        self.assertEqual(
            (pedido["solicitadas"], pedido["aceptadas"], pedido["pendientes"]),
            (100, 100, 0),
        )
        self.assertEqual(pedido["productos"][0]["aceptadas_en_guia"], 80)
        self.assertEqual(
            [entrega["aceptadas"] for entrega in pedido["entregas"]], [80, 20]
        )
        self.assertEqual(
            [entrega["document_number"] for entrega in pedido["entregas"]],
            ["G-PRIMERA", "G-SEGUNDA"],
        )
        self.assertTrue(pedido["entregas"][0]["es_recepcion_actual"])
        self.assertFalse(pedido["entregas"][1]["es_recepcion_actual"])

    def test_excedente_se_observa_con_motivo_y_no_aumenta_pedido(self):
        recepcion = crear_borrador_recepcion(
            actor=self.actor, provider_id=self.editorial.pk,
            document_type="guide", document_number="G-EXCESO",
            received_on=timezone.localdate(),
            notes="Se recibieron 10 unidades de más; permanecen observadas.",
            lines=[{
                "order_item_id": self.item.pk,
                "quantity_arrived": 110, "quantity_accepted": 100,
                "quantity_observed": 10,
            }],
        )
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.status, PurchaseOrder.Status.RECEIVED)
        datos = saldos_pedido(actor=self.actor, order_id=self.pedido.pk)
        self.assertEqual(datos["productos"][0]["cantidad_aceptada"], 100)
        self.assertEqual(datos["productos"][0]["cantidad_pendiente"], 0)
        self.assertEqual(
            recepcion.lines.get().quantity_observed, 10,
        )

    def test_excedente_conforme_sin_motivo_se_audita_automaticamente(self):
        recepcion = crear_borrador_recepcion(
            actor=self.actor, provider_id=self.editorial.pk,
            document_type="guide", document_number="G-EXCESO",
            received_on=timezone.localdate(),
            lines=[{
                "order_item_id": self.item.pk,
                "quantity_documented": 100,
                "quantity_arrived": 110, "quantity_accepted": 100,
                "quantity_extra": 10, "quantity_observed": 0,
            }],
        )
        validar_recepcion(actor=self.actor, receipt_id=recepcion.pk)
        recepcion.refresh_from_db()
        self.pedido.refresh_from_db()
        self.assertEqual(recepcion.status, GoodsReceipt.Status.VALIDATED)
        self.assertEqual(self.pedido.status, PurchaseOrder.Status.RECEIVED)
        evento = GoodsReceiptEvent.objects.get(receipt=recepcion, action="validated")
        self.assertEqual(evento.details["extra"], 10)
        self.assertEqual(evento.details["differences"][0]["physical"], 110)
        self.assertEqual(evento.details["differences"][0]["documented"], 100)

    def test_seguimiento_una_guia_con_dos_pedidos_mantiene_colegios_separados(self):
        segundo = PurchaseOrder.objects.create(
            origin=PurchaseOrder.Origin.MANUAL,
            provider=self.editorial,
            campaign=self.campania,
            provider_name_snapshot=self.editorial.name,
            campaign_name_snapshot=self.campania.name,
            school_name_snapshot="Colegio segundo",
            created_by=self.actor,
            status=PurchaseOrder.Status.SENT,
            sent_at=timezone.now(),
        )
        item_segundo = PurchaseOrderItem.objects.create(
            order=segundo, product=self.producto,
            product_name_snapshot=self.producto.name,
            quantity_ordered=50, unit_supplier_cost="25.80",
        )
        recibo = crear_borrador_recepcion(
            actor=self.actor, provider_id=self.editorial.pk,
            document_type="guide", document_number="G-DOS-COLEGIOS",
            received_on=timezone.localdate(),
            lines=[
                {"order_item_id": self.item.pk, "quantity_arrived": 80,
                 "quantity_accepted": 80, "quantity_observed": 0},
                {"order_item_id": item_segundo.pk, "quantity_arrived": 50,
                 "quantity_accepted": 50, "quantity_observed": 0},
            ],
        )
        validar_recepcion(actor=self.actor, receipt_id=recibo.pk)
        client = APIClient()
        client.force_authenticate(self.actor)
        response = client.get(
            f"/api/admin/erp/almacen/recepciones/{recibo.pk}/seguimiento/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        por_id = {pedido["pedido_id"]: pedido for pedido in response.data["pedidos"]}
        self.assertEqual(por_id[self.pedido.pk]["pendientes"], 20)
        self.assertEqual(por_id[segundo.pk]["pendientes"], 0)
        self.assertEqual(por_id[self.pedido.pk]["entregas"][0]["aceptadas"], 80)
        self.assertEqual(por_id[segundo.pk]["entregas"][0]["aceptadas"], 50)

    def test_seguimiento_restringido_a_usuarios_autorizados(self):
        recibo = self.borrador(10)
        usuario = get_user_model().objects.create_user(username="sin-seguimiento")
        client = APIClient()
        client.force_authenticate(usuario)
        response = client.get(
            f"/api/admin/erp/almacen/recepciones/{recibo.pk}/seguimiento/"
        )
        self.assertEqual(response.status_code, 403)
