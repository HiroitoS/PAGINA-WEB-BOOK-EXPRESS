"""Regresión del requerimiento de jefatura (17/11/2026)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from purchasing.order_creation import create_orders_from_adoption
from purchasing.test_integration import GeneracionPedidosAdopcionTests
from warehouse.models import GoodsReceipt, ReceivingEvidence, StockEntry, WarehouseLocation
from warehouse.receiving import crear_borrador_recepcion


class WarehouseSupervisorFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        GeneracionPedidosAdopcionTests.setUpTestData.__func__(cls)
        cls.clerk = get_user_model().objects.create_user(
            username="b3-almacenero", password="test",
        )
        cls.boss = get_user_model().objects.create_user(
            username="b3-jefe-almacen", password="test",
        )
        cls.ambos = get_user_model().objects.create_user(
            username="b3-dual", password="test",
        )
        for actor, perms in (
            (cls.clerk, ["view_receiving", "manage_receiving"]),
            (cls.boss, ["view_receiving", "validate_receiving"]),
            (cls.ambos, ["view_receiving", "manage_receiving", "validate_receiving"]),
        ):
            actor.user_permissions.add(*Permission.objects.filter(
                content_type__app_label="warehouse",
                codename__in=perms,
            ))
        WarehouseLocation.objects.create(
            code="P17-MAIN", name="Principal supervisor",
            kind=WarehouseLocation.Kind.MAIN,
        )

    def setUp(self):
        order = create_orders_from_adoption(
            adoption_id=self.adopcion.pk, actor=self.user,
        )[0]
        order.status = order.Status.SENT
        order.save(update_fields=["status", "updated_at"])
        self.order = order
        self.line = order.items.first()
        self.receipt = crear_borrador_recepcion(
            actor=self.clerk, provider_id=order.provider_id,
            document_type=GoodsReceipt.DocumentType.GUIDE,
            document_number="B3-REPORT-001",
            received_on="2026-11-17",
            lines=[{
                "order_item_id": self.line.pk,
                "quantity_arrived": 10,
                "quantity_documented": 12,
                "quantity_observed": 2,
                "quantity_accepted": 8,
                "quantity_extra": 0,
            }],
        )

    def api(self, actor):
        client = APIClient()
        client.force_authenticate(user=actor)
        return client

    def url(self, action):
        return f"/api/admin/erp/almacen/recepciones/{self.receipt.pk}/{action}/"

    def test_almacenero_envia_jefe_aprueba_stock_solo_al_final(self):
        self.assertEqual(StockEntry.objects.count(), 0)
        self.assertEqual(
            self.api(self.boss).post(self.url("validar"), {}, format="json").status_code, 400,
        )
        submitted = self.api(self.clerk).post(self.url("solicitar-aprobacion"), {}, format="json")
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["status"], "submitted")
        self.assertEqual(StockEntry.objects.count(), 0)
        self.assertEqual(
            self.api(self.clerk).post(self.url("validar"), {}, format="json").status_code, 403,
        )
        validated = self.api(self.boss).post(self.url("validar"), {}, format="json")
        self.assertEqual(validated.status_code, 200, validated.data)
        self.assertEqual(validated.data["status"], "validated")
        self.assertEqual(StockEntry.objects.count(), 1)
        self.assertEqual(
            self.api(self.boss).post(self.url("validar"), {}, format="json").status_code, 400,
        )
        self.assertEqual(
            self.receipt.events.filter(action__in=["submitted", "validated"]).count(), 2,
        )

    def test_jefatura_devuelve_y_no_acepta_autoaprobacion(self):
        submitted = self.api(self.clerk).post(self.url("solicitar-aprobacion"), {}, format="json")
        self.assertEqual(submitted.status_code, 200, submitted.data)
        back = self.api(self.boss).post(self.url("devolver"), {
            "reason": "Revisar físicamente las tapas de la guía.",
        }, format="json")
        self.assertEqual(back.status_code, 200, back.data)
        self.assertEqual(back.data["status"], "draft")
        self.assertFalse(StockEntry.objects.exists())

        # Un usuario con ambos permisos tampoco debe aprobar su propio registro.
        from warehouse.receiving import crear_borrador_recepcion as draft
        from django.core.exceptions import ValidationError
        another = draft(
            actor=self.ambos, provider_id=self.order.provider_id,
            document_type=GoodsReceipt.DocumentType.OTHER,
            document_number="B3-SELF-APPROVAL",
            received_on="2026-11-17",
            lines=[{
                "order_item_id": self.line.pk, "quantity_arrived": 1,
                "quantity_accepted": 1, "quantity_observed": 0,
            }],
        )
        client = self.api(self.ambos)
        self.assertEqual(client.post(
            f"/api/admin/erp/almacen/recepciones/{another.pk}/solicitar-aprobacion/",
            {}, format="json",
        ).status_code, 200)
        rejected = client.post(
            f"/api/admin/erp/almacen/recepciones/{another.pk}/validar/",
            {}, format="json",
        )
        self.assertEqual(rejected.status_code, 400, rejected.data)

    def test_evidencia_privada_y_reporte_sin_envio_automatico(self):
        client = self.api(self.clerk)
        line = self.receipt.lines.get()
        image = SimpleUploadedFile(
            "tapa.png",
            b"\x89PNG\r\n\x1a\n" + b"bookexpress-test",
            content_type="image/png",
        )
        created = client.post(self.url("evidencias"), {
            "receipt_line_id": line.pk,
            "kind": "damaged",
            "description": "Cubierta deteriorada en dos ejemplares",
            "file": image,
        }, format="multipart")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(ReceivingEvidence.objects.count(), 1)
        e = ReceivingEvidence.objects.get()
        self.addCleanup(e.file.delete, False)
        list_result = self.api(self.boss).get(self.url("evidencias"))
        self.assertEqual(list_result.status_code, 200, list_result.data)
        self.assertEqual(len(list_result.data), 1)
        self.assertNotIn("file", list_result.data[0])
        self.assertEqual(
            self.api(get_user_model().objects.create_user(username="unauthorized")).get(
                self.url("evidencias")
            ).status_code, 403,
        )
        report = self.api(self.boss).get(self.url("reporte-editorial"))
        self.assertEqual(report.status_code, 200, report.data)
        self.assertTrue(report.data["requires_attention"])
        self.assertFalse(report.data["sending_enabled"])
        self.assertIn("faltantes frente a guía 2", report.data["body"])
        self.assertIn("Cubierta deteriorada", report.data["body"])
        sent = self.api(self.boss).post(self.url("reporte-editorial"), {
            "recipient": "editorial@example.test",
            "dispatch_key": "8bf3bb1c-7627-4d51-b98c-33b5c79d9f62",
        }, format="json")
        self.assertEqual(sent.status_code, 400, sent.data)
        self.assertFalse(self.receipt.events.filter(action="supplier_report_sent").exists())

    def test_filtros_inventario_por_editorial_y_colegio(self):
        submit = self.api(self.clerk).post(self.url("solicitar-aprobacion"), {}, format="json")
        self.assertEqual(submit.status_code, 200, submit.data)
        self.assertEqual(self.api(self.boss).post(self.url("validar"), {}, format="json").status_code, 200)
        client = self.api(self.boss)
        base = "/api/admin/erp/almacen/inventario/"
        filters = client.get(base + "consolidado-filtros/")
        self.assertEqual(filters.status_code, 200, filters.data)
        self.assertIn(self.order.provider_id, [i["id"] for i in filters.data["editoriales"]])
        self.assertIn(self.colegio.pk, [i["id"] for i in filters.data["colegios"]])
        good = client.get(base + "consolidado/", {
            "grupo": "colegio",
            "editorial_id": self.order.provider_id,
            "colegio_id": self.colegio.pk,
        })
        self.assertEqual(good.status_code, 200, good.data)
        self.assertTrue(good.data["resultados"])
        empty = client.get(base + "consolidado/", {
            "grupo": "colegio", "editorial_id": self.order.provider_id,
            "colegio_id": self.colegio.pk + 9000,
        })
        self.assertEqual(empty.status_code, 200, empty.data)
        self.assertEqual(empty.data["conteo"], 0)
