"""P-08.0: ubicaciones internas sin asignación falsa de stock."""
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
        cls.main = WarehouseLocation.objects.create(
            code="PRINCIPAL", name="Almacén principal de pruebas",
            kind=WarehouseLocation.Kind.MAIN,
        )
        cls.fair = WarehouseLocation.objects.create(
            code="FERIA-PRUEBA", name="Feria de prueba",
            kind=WarehouseLocation.Kind.FAIR, is_active=False,
        )

    def test_consulta_incluye_ubicaciones_activas_e_inactivas_sin_stock_ficticio(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get("/api/admin/erp/almacen/ubicaciones/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 2)
        codigos = {row["code"] for row in response.data}
        self.assertEqual(codigos, {"PRINCIPAL", "FERIA-PRUEBA"})
        self.assertEqual(StockEntry.objects.count(), 0)

    def test_no_habilita_alta_o_edicion_por_esta_api(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        url = "/api/admin/erp/almacen/ubicaciones/"
        self.assertEqual(client.post(url, {
            "code": "TIENDA", "name": "Tienda", "kind": "store"
        }, format="json").status_code, 405)
        self.assertEqual(client.patch(
            f"{url}{self.main.pk}/", {"name": "Nuevo nombre"}, format="json"
        ).status_code, 405)
        self.assertEqual(WarehouseLocation.objects.count(), 2)

    def test_requiere_permiso_para_consultar(self):
        employee = get_user_model().objects.create_user(
            username="locations-no-access", password="dummy"
        )
        client = APIClient()
        client.force_authenticate(user=employee)
        response = client.get("/api/admin/erp/almacen/ubicaciones/")
        self.assertEqual(response.status_code, 403)
