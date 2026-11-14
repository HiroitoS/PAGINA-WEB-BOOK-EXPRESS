"""Modalidades logísticas intercambiables, con trazabilidad sin cambiar la adopción."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from purchasing.test_integration import GeneracionPedidosAdopcionTests
from warehouse.models import (
    DistributionOperation, DistributionOperationEvent,
    DistributionOperationLine, StockEntry, StockTransfer, WarehouseLocation,
)


class DistributionAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        GeneracionPedidosAdopcionTests.setUpTestData.__func__(cls)
        cls.main = WarehouseLocation.objects.create(
            code="D-PRINC", name="Principal", kind=WarehouseLocation.Kind.MAIN,
        )
        cls.store = WarehouseLocation.objects.create(
            code="D-TIENDA", name="Tienda", kind=WarehouseLocation.Kind.STORE,
        )
        cls.fair = WarehouseLocation.objects.create(
            code="D-FERIA", name="Feria", kind=WarehouseLocation.Kind.FAIR,
        )
        cls.cons = WarehouseLocation.objects.create(
            code="D-CONSIG", name="Consignación", kind=WarehouseLocation.Kind.CONSIGNMENT,
        )
        cls.outsider = get_user_model().objects.create_user(username="sin-distribucion")

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def payload(self, **overrides):
        data = {
            "idempotency_key": str(uuid4()),
            "adoption_id": self.adopcion.pk,
            "mode": "fair",
            "source_id": self.main.pk,
            "destination_id": self.fair.pk,
            "operation_name": "Feria de campaña del colegio",
            "responsible_name": "Responsable de almacén",
            "scheduled_on": "2027-02-01",
            "scheduled_until": "2027-02-03",
            "notes": "Sólo planificación",
        }
        data.update(overrides)
        return data

    def test_crear_desde_adopcion_no_mueve_ni_reserva_inventario(self):
        before = StockEntry.objects.count(), StockTransfer.objects.count()
        response = self.client_as(self.user).post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            self.payload(), format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        record = DistributionOperation.objects.get()
        self.assertEqual(record.school_id, self.colegio.pk)
        self.assertEqual(record.mode, "fair")
        self.assertEqual(record.original_mode, "")
        self.assertEqual(record.events.count(), 1)
        self.assertEqual(
            sorted(record.items.values_list("quantity_planned", flat=True)),
            [40, 100],
        )
        self.assertEqual(
            (StockEntry.objects.count(), StockTransfer.objects.count()), before,
        )
        self.assertIn("todavía no reserva", response.data["notice"])
        self.assertEqual(
            self.client_as(self.user).get(
                "/api/admin/erp/almacen/operaciones-distribucion/opciones/"
            ).status_code, 200,
        )

    def test_transiciones_todas_las_modalidades_y_repetidos_con_historial(self):
        client = self.client_as(self.user)
        for original, destino in [
            ("point_of_sale", "fair"),
            ("point_of_sale", "consignment"),
            ("fair", "point_of_sale"),
            ("fair", "consignment"),
            ("consignment", "point_of_sale"),
            ("consignment", "fair"),
        ]:
            with self.subTest(original=original, destino=destino):
                self.adopcion.sale_mode = original
                self.adopcion.save(update_fields=["sale_mode"])
                created = client.post(
                    "/api/admin/erp/almacen/operaciones-distribucion/",
                    self.payload(
                        idempotency_key=str(uuid4()),
                        mode=original,
                    ), format="json",
                )
                self.assertEqual(created.status_code, 201, created.data)
                pk = created.data["id"]
                response = client.patch(
                    f"/api/admin/erp/almacen/operaciones-distribucion/{pk}/",
                    {
                        "mode": destino,
                        "reason": "El colegio cambió de modalidad de entrega.",
                    }, format="json",
                )
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["mode"], destino)
                self.assertEqual(response.data["original_mode"], original)
                self.assertEqual(len(response.data["events"]), 2)
                self.assertEqual(response.data["events"][1]["previous"]["mode"], original)
                self.assertEqual(response.data["events"][1]["current"]["mode"], destino)
                self.adopcion.refresh_from_db()
                self.assertEqual(self.adopcion.sale_mode, original)
        self.assertEqual(StockEntry.objects.count(), 0)
        self.assertEqual(StockTransfer.objects.count(), 0)

    def test_reintento_idempotente_y_no_permite_reutilizar_clave_con_otros_datos(self):
        client = self.client_as(self.user)
        data = self.payload()
        first = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            data, format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        repeat = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            data, format="json",
        )
        self.assertEqual(repeat.status_code, 200, repeat.data)
        other = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            {**data, "mode": "point_of_sale"}, format="json",
        )
        self.assertEqual(other.status_code, 400, other.data)
        self.assertEqual(DistributionOperation.objects.count(), 1)
        self.assertEqual(DistributionOperationEvent.objects.count(), 1)

    def test_anulacion_no_modifica_registros_anteriores(self):
        client = self.client_as(self.user)
        new = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            self.payload(), format="json",
        )
        pk = new.data["id"]
        base = f"/api/admin/erp/almacen/operaciones-distribucion/{pk}/"
        self.assertEqual(
            client.patch(base, {"mode": "consignment"}, format="json").status_code,
            400,
        )
        self.assertEqual(
            client.post(base + "anular/", {"reason": "No"}, format="json").status_code,
            400,
        )
        cancelled = client.post(
            base + "anular/", {"reason": "El colegio suspendió su feria."},
            format="json",
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["status"], "cancelled")
        self.assertEqual(
            client.patch(
                base, {"mode": "point_of_sale", "reason": "Cambiar a librería."},
                format="json",
            ).status_code, 400,
        )
        self.assertEqual(DistributionOperationLine.objects.count(), 2)
        self.assertEqual(DistributionOperationEvent.objects.count(), 2)

    def test_restricciones_de_destino_fechas_permisos(self):
        client = self.client_as(self.user)
        cases = [
            self.payload(destination_id=self.main.pk),
            self.payload(scheduled_on="2027-05-05", scheduled_until="2027-01-01"),
            self.payload(mode="otra"),
            self.payload(responsible_name=""),
            self.payload(adoption_id=999999),
        ]
        for data in cases:
            with self.subTest(data=data):
                response = client.post(
                    "/api/admin/erp/almacen/operaciones-distribucion/",
                    data, format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(DistributionOperation.objects.exists())
        self.assertEqual(
            self.client_as(self.outsider).get(
                "/api/admin/erp/almacen/operaciones-distribucion/",
            ).status_code, 403,
        )
        self.assertEqual(
            self.client_as(self.outsider).post(
                "/api/admin/erp/almacen/operaciones-distribucion/",
                self.payload(), format="json",
            ).status_code, 403,
        )
