"""Pruebas P-09: requerimientos, permisos e historial sin mover inventario."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from catalog.models import Product, Provider
from warehouse.models import (
    InternalStockRequest, InternalStockRequestEvent, InternalStockRequestItem,
    StockEntry, StockTransfer, WarehouseLocation,
)


class InternalRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser(
            username="req-admin", password="dummy", email="req-admin@example.test",
        )
        cls.worker = User.objects.create_user(username="req-worker", password="dummy")
        cls.reviewer = User.objects.create_user(username="req-reviewer", password="dummy")
        cls.outsider = User.objects.create_user(username="req-outsider", password="dummy")
        cls.worker.user_permissions.add(*Permission.objects.filter(
            codename__in=("view_internal_stock_requests", "manage_internal_stock_requests"),
        ))
        cls.reviewer.user_permissions.add(*Permission.objects.filter(
            codename__in=("view_internal_stock_requests", "approve_internal_stock_requests"),
        ))
        cls.provider = Provider.objects.create(name="Editorial prueba solicitud")
        cls.product = Product.objects.create(
            name="Libro solicitado", provider=cls.provider, code="REQ-001",
        )
        cls.other = Product.objects.create(
            name="Otra lectura", provider=cls.provider, code="REQ-002",
        )
        cls.main = WarehouseLocation.objects.create(
            code="REQ-MAIN", name="Almacén inicial",
            kind=WarehouseLocation.Kind.MAIN,
        )
        cls.store = WarehouseLocation.objects.create(
            code="REQ-STORE", name="Tienda centro",
            kind=WarehouseLocation.Kind.STORE,
        )
        cls.fair = WarehouseLocation.objects.create(
            code="REQ-FAIR", name="Feria general",
            kind=WarehouseLocation.Kind.FAIR,
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def payload(self, **updates):
        data = {
            "source_id": self.main.pk, "destination_id": self.store.pk,
            "responsible_name": "Encargado de tienda",
            "needed_on": (timezone.localdate() + timedelta(days=2)).isoformat(),
            "notes": "Campaña escolar",
            "items": [
                {"product_id": self.product.pk, "quantity": 12},
                {"product_id": self.other.pk, "quantity": 3},
            ],
        }
        data.update(updates)
        return data

    def test_crear_solicitud_no_reserva_ni_ingresa_stock_y_conserva_historial(self):
        url = "/api/admin/erp/almacen/solicitudes-internas/"
        before = StockEntry.objects.count(), StockTransfer.objects.count()
        response = self.client_as(self.worker).post(url, self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        record = InternalStockRequest.objects.get(pk=response.data["id"])
        self.assertEqual(record.status, InternalStockRequest.Status.SUBMITTED)
        self.assertEqual(record.created_by_id, self.worker.pk)
        self.assertEqual(record.items.count(), 2)
        self.assertEqual([i.quantity_requested for i in record.items.all()], [12, 3])
        self.assertEqual(record.events.count(), 1)
        self.assertEqual(response.data["events"][0]["actor_name"], self.worker.username)
        self.assertEqual((StockEntry.objects.count(), StockTransfer.objects.count()), before)

        forbidden = self.client_as(self.worker).post(
            f"{url}{record.pk}/aprobar/", {}, format="json",
        )
        self.assertEqual(forbidden.status_code, 403)
        review = self.client_as(self.reviewer).post(
            f"{url}{record.pk}/aprobar/", {}, format="json",
        )
        self.assertEqual(review.status_code, 200, review.data)
        record.refresh_from_db()
        self.assertEqual(record.status, InternalStockRequest.Status.APPROVED)
        self.assertEqual(record.approved_by_id, self.reviewer.pk)
        self.assertEqual(record.events.count(), 2)
        self.assertIsNotNone(record.approved_at)
        self.assertEqual((StockEntry.objects.count(), StockTransfer.objects.count()), before)
        duplicate = self.client_as(self.reviewer).post(f"{url}{record.pk}/aprobar/", {}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(record.events.count(), 2)

    def test_bloquea_duplicados_destino_igual_y_solicitudes_feria_sin_referencia(self):
        url = "/api/admin/erp/almacen/solicitudes-internas/"
        client = self.client_as(self.admin)
        invalid = [
            self.payload(destination_id=self.main.pk),
            self.payload(destination_id=self.fair.pk),
            self.payload(items=[]),
            self.payload(items=[
                {"product_id": self.product.pk, "quantity": 2},
                {"product_id": self.product.pk, "quantity": 3},
            ]),
            self.payload(items=[{"product_id": self.product.pk, "quantity": 0}]),
            self.payload(responsible_name=""),
        ]
        for data in invalid:
            with self.subTest(data=data):
                result = client.post(url, data, format="json")
                self.assertEqual(result.status_code, 400, result.data)
        self.assertFalse(InternalStockRequest.objects.exists())
        okay = client.post(url, self.payload(
            destination_id=self.fair.pk,
            operation_name="Feria Colegio Zárate, 2027",
        ), format="json")
        self.assertEqual(okay.status_code, 201, okay.data)

    def test_rechazo_exige_motivo_cancelacion_restringida_y_eventos_conservados(self):
        base = "/api/admin/erp/almacen/solicitudes-internas/"
        created = self.client_as(self.worker).post(base, self.payload(), format="json")
        pk = created.data["id"]
        self.assertEqual(
            self.client_as(self.reviewer).post(f"{base}{pk}/rechazar/", {"note": ""}).status_code,
            400,
        )
        self.assertEqual(
            self.client_as(self.outsider).post(f"{base}{pk}/anular/", {}).status_code,
            403,
        )
        self.assertEqual(
            self.client_as(self.worker).post(f"{base}{pk}/anular/", {}).status_code,
            200,
        )
        record = InternalStockRequest.objects.get(pk=pk)
        self.assertEqual(record.status, InternalStockRequest.Status.CANCELLED)
        self.assertEqual(record.events.count(), 2)

        created = self.client_as(self.worker).post(base, self.payload(), format="json")
        pk = created.data["id"]
        self.assertEqual(
            self.client_as(self.reviewer).post(f"{base}{pk}/rechazar/",
                                                 {"note": "Falta confirmar destino"}, format="json").status_code,
            200,
        )
        self.assertEqual(InternalStockRequest.objects.get(pk=pk).events.count(), 2)

    def test_lectura_paginada_y_busqueda_productos_respetan_permisos(self):
        base = "/api/admin/erp/almacen/solicitudes-internas/"
        self.client_as(self.worker).post(base, self.payload(), format="json")
        self.assertEqual(self.client_as(self.outsider).get(base).status_code, 403)
        self.assertEqual(self.client_as(self.outsider).get(f"{base}productos/?q=REQ").status_code, 403)
        self.assertEqual(self.client_as(self.reviewer).post(base, self.payload(), format="json").status_code, 403)
        found = self.client_as(self.worker).get(f"{base}productos/?q=REQ")
        self.assertEqual(found.status_code, 200, found.data)
        self.assertEqual(len(found.data), 2)
        rows = self.client_as(self.worker).get(base, {"status": "submitted"})
        self.assertEqual(rows.status_code, 200, rows.data)
        self.assertEqual(rows.data["count"], 1)
        self.assertEqual(rows.data["results"][0]["items"][0]["product_code_snapshot"], "REQ-001")
        self.assertEqual(self.client_as(self.worker).get(base, {"status": "desconocido"}).status_code, 400)
        self.assertEqual(self.client_as(self.worker).get(base, {"page": "0"}).status_code, 400)

    def test_no_expone_metodos_para_modificar_solicitud_confirmada(self):
        url = "/api/admin/erp/almacen/solicitudes-internas/"
        created = self.client_as(self.admin).post(url, self.payload(), format="json")
        pk = created.data["id"]
        self.assertEqual(self.client_as(self.admin).patch(
            f"{url}{pk}/", {"notes": "alterar"}, format="json",
        ).status_code, 405)
        self.assertEqual(self.client_as(self.admin).delete(f"{url}{pk}/").status_code, 405)
        self.assertEqual(InternalStockRequestItem.objects.filter(request_id=pk).count(), 2)
        self.assertEqual(InternalStockRequestEvent.objects.filter(request_id=pk).count(), 1)
