"""Regresión del requerimiento de jefatura (17/11/2026)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from purchasing.order_creation import create_orders_from_adoption
from purchasing.test_integration import GeneracionPedidosAdopcionTests
from notifications.models import Notification
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

    def test_atribucion_bandeja_y_enlaces_de_notificaciones(self):
        base = "/api/admin/erp/almacen/recepciones/pendientes-aprobacion/"
        before = self.api(self.boss).get(base)
        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.data["total"], 0)
        self.assertEqual(self.api(self.clerk).get(base).status_code, 403)

        submit = self.api(self.clerk).post(self.url("solicitar-aprobacion"), {}, format="json")
        self.assertEqual(submit.status_code, 200, submit.data)

        pending = self.api(self.boss).get(base)
        self.assertEqual(pending.status_code, 200, pending.data)
        self.assertEqual(pending.data["total"], 1)
        self.assertEqual(pending.data["recepciones"][0]["id"], self.receipt.pk)

        notice = Notification.objects.get(
            recipient=self.boss,
            event_type="warehouse.receipt_approval_requested",
            source_id=str(self.receipt.pk),
        )
        destination = f"/admin/erp/almacen/recepciones?recepcion={self.receipt.pk}"
        self.assertEqual(notice.link, destination)

        approved = self.api(self.boss).post(self.url("validar"), {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(self.api(self.boss).get(base).data["total"], 0)

        notice.refresh_from_db()
        self.assertTrue(notice.is_resolved)
        self.assertTrue(notice.is_read)

        clerk_notice = Notification.objects.get(
            recipient=self.clerk,
            event_type="warehouse.receipt_validated",
            source_id=str(self.receipt.pk),
        )
        self.assertEqual(clerk_notice.link, destination)

    def test_devolucion_notifica_al_registrador_y_reenvio_no_duplica(self):
        destination = f"/admin/erp/almacen/recepciones?recepcion={self.receipt.pk}"
        self.assertEqual(
            self.api(self.clerk).post(self.url("solicitar-aprobacion"), {}, format="json").status_code,
            200,
        )
        back = self.api(self.boss).post(self.url("devolver"), {
            "reason": "Rectificar los cinco ejemplares observados.",
        }, format="json")
        self.assertEqual(back.status_code, 200, back.data)
        returned = Notification.objects.get(
            recipient=self.clerk,
            event_type="warehouse.receipt_returned",
            source_id=str(self.receipt.pk),
        )
        self.assertEqual(returned.link, destination)
        self.assertIn("Rectificar", returned.message)
        self.assertTrue(Notification.objects.get(
            recipient=self.boss, event_type="warehouse.receipt_approval_requested",
            source_id=str(self.receipt.pk),
        ).is_resolved)

        # Una nueva revisión debe generar un aviso nuevo, no reutilizar el anterior.
        second = self.api(self.clerk).post(
            self.url("solicitar-aprobacion"), {}, format="json",
        )
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(Notification.objects.filter(
            recipient=self.boss,
            event_type="warehouse.receipt_approval_requested",
            source_id=str(self.receipt.pk),
        ).count(), 2)
        self.assertEqual(self.api(self.boss).get(
            "/api/admin/erp/almacen/recepciones/pendientes-aprobacion/"
        ).data["total"], 1)

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
        self.assertEqual(list_result.data[0]["created_by"], self.clerk.get_username())
        downloaded = self.api(self.boss).get(
            self.url(f"evidencias/{e.pk}/archivo"),
        )
        self.assertEqual(downloaded.status_code, 200)
        downloaded.close()
        self.assertEqual(
            self.api(get_user_model().objects.create_user(
                username="sin-acceso-descarga",
            )).get(self.url(f"evidencias/{e.pk}/archivo")).status_code,
            403,
        )
        self.assertEqual(
            self.api(get_user_model().objects.create_user(username="unauthorized")).get(
                self.url("evidencias")
            ).status_code, 403,
        )
        report = self.api(self.boss).get(self.url("reporte-editorial"))
        self.assertEqual(report.status_code, 200, report.data)
        self.assertTrue(report.data["requires_attention"])
        self.assertFalse(report.data["sending_enabled"])
        self.assertIn("Faltante frente a la guía: 2 unidad(es)", report.data["body"])
        self.assertIn("2 unidad(es) observada(s)", report.data["body"])
        self.assertNotIn("Faltante frente a la guía: 0", report.data["body"])
        self.assertIn("Cubierta deteriorada", report.data["body"])
        sent = self.api(self.boss).post(self.url("reporte-editorial"), {
            "recipient": "editorial@example.test",
            "dispatch_key": "8bf3bb1c-7627-4d51-b98c-33b5c79d9f62",
        }, format="json")
        self.assertEqual(sent.status_code, 400, sent.data)
        self.assertFalse(self.receipt.events.filter(action="supplier_report_sent").exists())

    def test_evidencia_despues_de_aprobacion_no_reingresa_inventario(self):
        """Fotografías complementan recepción validada sin duplicar entradas."""
        submit = self.api(self.clerk).post(
            self.url("solicitar-aprobacion"), {}, format="json",
        )
        self.assertEqual(submit.status_code, 200, submit.data)
        approved = self.api(self.boss).post(
            self.url("validar"), {}, format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(StockEntry.objects.count(), 1)
        stock_before = list(StockEntry.objects.values_list("pk", flat=True))

        image = SimpleUploadedFile(
            "observacion.png",
            b"\x89PNG\r\n\x1a\n" + b"evidencia-test-despues-de-aprobacion",
            content_type="image/png",
        )
        result = self.api(self.clerk).post(self.url("evidencias"), {
            "receipt_line_id": self.receipt.lines.get().pk,
            "kind": "damaged",
            "description": "Dos ejemplares con cubierta deteriorada",
            "file": image,
        }, format="multipart")
        self.assertEqual(result.status_code, 201, result.data)
        evidence = ReceivingEvidence.objects.get(pk=result.data["id"])
        self.addCleanup(evidence.file.delete, False)
        self.assertEqual(
            list(StockEntry.objects.values_list("pk", flat=True)),
            stock_before,
        )
        report = self.api(self.boss).get(self.url("reporte-editorial"))
        self.assertEqual(report.status_code, 200, report.data)
        self.assertTrue(report.data["requires_attention"])
        self.assertTrue(report.data["validated"])
        self.assertIn("Dos ejemplares con cubierta deteriorada", report.data["body"])
        self.assertFalse(self.receipt.events.filter(action="supplier_report_sent").exists())

    def test_correo_solo_incluye_incidencias_y_no_pendientes_del_pedido(self):
        """Guía completa con observados: no anunciar faltantes ficticios."""
        line = self.receipt.lines.get()
        line.quantity_documented = line.quantity_arrived
        line.save(update_fields=["quantity_documented", "updated_at"])
        response = self.api(self.boss).get(self.url("reporte-editorial"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("Incidencias de recepción", response.data["subject"])
        self.assertIn("2 unidad(es) observada(s)", response.data["body"])
        self.assertNotIn("Faltante frente a la guía:", response.data["body"])
        self.assertNotIn("observados 2, faltantes", response.data["body"])
        self.assertNotIn("No se adjuntaron evidencias.", response.data["body"])
        self.assertTrue(response.data["requires_attention"])

    def test_sin_incidencias_no_inventa_reclamacion(self):
        """Sin observados ni faltantes de guía no hay correo que enviar."""
        line = self.receipt.lines.get()
        line.quantity_documented = line.quantity_arrived
        line.quantity_observed = 0
        line.quantity_accepted = line.quantity_arrived
        line.save(update_fields=[
            "quantity_documented", "quantity_observed",
            "quantity_accepted", "updated_at",
        ])
        response = self.api(self.boss).get(self.url("reporte-editorial"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["requires_attention"])
        self.assertIn("No se registraron incidencias", response.data["body"])
        self.assertNotIn("Faltante frente a la guía:", response.data["body"])

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
