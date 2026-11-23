"""B3.2: un subalmacén por feria real, sin inventar mercadería."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from warehouse.models import (
    DistributionOperation, StockEntry, StockTransfer,
    WarehouseFairEvent, WarehouseLocation,
)


class WarehouseFairEventTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username="fair-supervisor", email="fair@example.test", password="dummy",
        )
        cls.employee = get_user_model().objects.create_user(
            username="fair-without-permissions", password="dummy",
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    @staticmethod
    def payload(key=None):
        return {
            "idempotency_key": str(key or uuid4()),
            "name": "Feria de demostración escolar",
            "venue_name": "Recinto de prueba",
            "venue_address": "Dirección de prueba (no real)",
            "starts_on": "2027-02-10",
            "ends_on": "2027-02-12",
            "responsible_name": "Responsable de prueba",
            "notes": "",
        }

    def test_creacion_genera_subalmacen_exclusivo_sin_stock(self):
        client = self.client_as(self.admin)
        response = client.post(
            "/api/admin/erp/almacen/ferias/", self.payload(), format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["name"], "Feria de demostración escolar")
        loc = WarehouseLocation.objects.get(pk=response.data["location_id"])
        self.assertEqual(loc.kind, WarehouseLocation.Kind.FAIR)
        self.assertEqual(loc.address, "Dirección de prueba (no real)")
        self.assertTrue(loc.is_active)
        self.assertEqual(WarehouseFairEvent.objects.count(), 1)
        self.assertEqual(WarehouseLocation.objects.count(), 1)
        self.assertEqual(StockEntry.objects.count(), 0)
        self.assertEqual(StockTransfer.objects.count(), 0)
        self.assertEqual(DistributionOperation.objects.count(), 0)
        get_response = client.get("/api/admin/erp/almacen/ferias/")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(len(get_response.data), 1)
        self.assertEqual(get_response.data[0]["location_id"], loc.pk)
        self.assertEqual(get_response.data[0]["schools"], [])
        self.assertFalse(get_response.data[0]["school_conflict"])

    def test_reintento_no_crea_segunda_ubicacion(self):
        client = self.client_as(self.admin)
        payload = self.payload()
        url = "/api/admin/erp/almacen/ferias/"
        first = client.post(url, payload, format="json")
        second = client.post(url, payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(WarehouseLocation.objects.count(), 1)
        self.assertEqual(WarehouseFairEvent.objects.count(), 1)
        changed = {**payload, "venue_name": "Recinto diferente"}
        third = client.post(url, changed, format="json")
        self.assertEqual(third.status_code, 400, third.data)
        self.assertEqual(WarehouseLocation.objects.count(), 1)

    def test_fecha_invertida_o_ubicacion_faltante_no_deja_ubicaciones(self):
        client = self.client_as(self.admin)
        url = "/api/admin/erp/almacen/ferias/"
        bad_dates = self.payload()
        bad_dates["ends_on"] = "2027-02-09"
        self.assertEqual(client.post(url, bad_dates, format="json").status_code, 400)
        missing_venue = self.payload()
        missing_venue["venue_address"] = ""
        self.assertEqual(client.post(url, missing_venue, format="json").status_code, 400)
        self.assertEqual(WarehouseLocation.objects.count(), 0)
        self.assertEqual(WarehouseFairEvent.objects.count(), 0)

    def test_ubicacion_de_evento_no_se_modifica_desde_formulario_generico(self):
        client = self.client_as(self.admin)
        response = client.post(
            "/api/admin/erp/almacen/ferias/", self.payload(), format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        location_id = response.data["location_id"]
        url = f"/api/admin/erp/almacen/ubicaciones/{location_id}/"
        got = client.get(url)
        self.assertEqual(got.status_code, 200, got.data)
        self.assertEqual(got.data["fair_event_id"], response.data["id"])
        changed = client.patch(url, {
            "kind": "store", "name": "Intento de tienda",
        }, format="json")
        self.assertEqual(changed.status_code, 400, changed.data)
        location = WarehouseLocation.objects.get(pk=location_id)
        self.assertEqual(location.kind, WarehouseLocation.Kind.FAIR)
        self.assertEqual(location.name, response.data["name"])

    def test_ferias_separadas_no_comparten_ubicacion(self):
        client = self.client_as(self.admin)
        first = client.post(
            "/api/admin/erp/almacen/ferias/", self.payload(), format="json",
        )
        second_data = {
            **self.payload(), "name": "Feria de otro colegio",
            "venue_address": "Otro recinto de prueba",
        }
        second = client.post(
            "/api/admin/erp/almacen/ferias/", second_data, format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertNotEqual(first.data["location_id"], second.data["location_id"])
        self.assertEqual(StockEntry.objects.count(), 0)

    def test_feria_esta_disponible_como_destino_identificable(self):
        client = self.client_as(self.admin)
        created = client.post(
            "/api/admin/erp/almacen/ferias/", self.payload(), format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        choices = client.get(
            "/api/admin/erp/almacen/operaciones-distribucion/opciones/"
        )
        self.assertEqual(choices.status_code, 200, choices.data)
        match = [
            location for location in choices.data["locations"]
            if location["id"] == created.data["location_id"]
        ]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["kind"], "fair")
        self.assertEqual(match[0]["fair_event_id"], created.data["id"])

    def test_permisos_y_sin_eliminar_ferias(self):
        unauth = self.client_as(self.employee)
        admin = self.client_as(self.admin)
        url = "/api/admin/erp/almacen/ferias/"
        self.assertEqual(unauth.get(url).status_code, 403)
        self.assertEqual(
            unauth.post(url, self.payload(), format="json").status_code, 403,
        )
        created = admin.post(url, self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        detail = f"{url}{created.data['id']}/"
        self.assertEqual(admin.get(detail).status_code, 200)
        self.assertEqual(admin.delete(detail).status_code, 405)
        self.assertEqual(WarehouseFairEvent.objects.count(), 1)
