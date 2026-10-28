"""P-08.1a: ubicaciones administradas sin creación ficticia de existencias."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from warehouse.models import WarehouseLocation, StockEntry


class WarehouseLocationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username="locations-admin", email="locations@example.test", password="dummy"
        )
        cls.employee = get_user_model().objects.create_user(
            username="locations-no-access", password="dummy"
        )
        cls.main = WarehouseLocation.objects.create(
            code="PRINCIPAL", name="Almacén principal de pruebas",
            kind=WarehouseLocation.Kind.MAIN,
        )
        cls.fair = WarehouseLocation.objects.create(
            code="FERIA-PRUEBA", name="Feria de prueba",
            kind=WarehouseLocation.Kind.FAIR, is_active=False,
        )

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_consulta_incluye_ubicaciones_activas_e_inactivas_sin_stock_ficticio(self):
        response = self.client_as(self.admin).get(
            "/api/admin/erp/almacen/ubicaciones/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(
            {row["code"] for row in response.data},
            {"PRINCIPAL", "FERIA-PRUEBA"},
        )
        self.assertEqual(StockEntry.objects.count(), 0)

    def test_administrador_puede_crear_y_editar_sin_afectar_stock(self):
        client = self.client_as(self.admin)
        url = "/api/admin/erp/almacen/ubicaciones/"
        response = client.post(url, {
            "name": "Tienda principal",
            "kind": "store", "address": "Referencia de prueba",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertRegex(response.data["code"], r"^UBI-[A-F0-9]{24}$")
        codigo_inicial = response.data["code"]
        location_id = response.data["id"]
        response = client.patch(f"{url}{location_id}/", {
            "name": "Tienda comercial", "is_active": False,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        location = WarehouseLocation.objects.get(pk=location_id)
        self.assertEqual(location.name, "Tienda comercial")
        self.assertFalse(location.is_active)
        self.assertEqual(location.code, codigo_inicial)
        self.assertEqual(StockEntry.objects.count(), 0)

    def test_codigo_interno_automatico_no_depende_del_nombre_ni_de_la_entrada(self):
        client = self.client_as(self.admin)
        url = "/api/admin/erp/almacen/ubicaciones/"
        primero = client.post(url, {
            "name": "Tienda", "kind": "store",
        }, format="json")
        segundo = client.post(url, {
            "code": "PRINCIPAL", "name": "Tienda", "kind": "store",
        }, format="json")
        self.assertEqual(primero.status_code, 201, primero.data)
        self.assertEqual(segundo.status_code, 201, segundo.data)
        self.assertRegex(primero.data["code"], r"^UBI-[A-F0-9]{24}$")
        self.assertRegex(segundo.data["code"], r"^UBI-[A-F0-9]{24}$")
        self.assertNotEqual(primero.data["code"], segundo.data["code"])
        self.assertNotEqual(segundo.data["code"], "PRINCIPAL")
        self.assertEqual(StockEntry.objects.count(), 0)

    def test_codigo_existente_no_se_puede_modificar(self):
        client = self.client_as(self.admin)
        url = "/api/admin/erp/almacen/ubicaciones/"
        response = client.patch(f"{url}{self.main.pk}/", {
            "code": "CAMBIAR-CODIGO",
        }, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.main.refresh_from_db()
        self.assertEqual(self.main.code, "PRINCIPAL")

    @patch("warehouse.api_locations.generar_codigo_ubicacion")
    def test_colision_de_codigo_reintenta_sin_sobrescribir_ubicacion(self, generar):
        generar.side_effect = ["PRINCIPAL", "UBI-ABCDEF012345678901234567"]
        response = self.client_as(self.admin).post(
            "/api/admin/erp/almacen/ubicaciones/",
            {"name": "Feria escolar", "kind": "fair"}, format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["code"], "UBI-ABCDEF012345678901234567")
        self.assertEqual(generar.call_count, 2)
        self.main.refresh_from_db()
        self.assertEqual(self.main.code, "PRINCIPAL")
        self.assertEqual(StockEntry.objects.count(), 0)

    def test_tipo_no_valido_es_rechazado(self):
        response = self.client_as(self.admin).post(
            "/api/admin/erp/almacen/ubicaciones/",
            {"name": "Inventado", "kind": "cualquier-tipo"}, format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_no_se_pueden_borrar_ubicaciones(self):
        response = self.client_as(self.admin).delete(
            f"/api/admin/erp/almacen/ubicaciones/{self.main.pk}/"
        )
        self.assertEqual(response.status_code, 405)
        self.assertTrue(WarehouseLocation.objects.filter(pk=self.main.pk).exists())

    def test_usuarios_sin_permisos_no_pueden_consultar_ni_modificar(self):
        client = self.client_as(self.employee)
        url = "/api/admin/erp/almacen/ubicaciones/"
        self.assertEqual(client.get(url).status_code, 403)
        self.assertEqual(client.post(url, {
            "code": "TIENDA", "name": "Tienda", "kind": "store",
        }, format="json").status_code, 403)
        self.assertEqual(client.patch(
            f"{url}{self.main.pk}/", {"name": "Manipulado"},
            format="json",
        ).status_code, 403)
        self.assertEqual(WarehouseLocation.objects.count(), 2)
