"""Pruebas de permisos y rutas privadas del módulo de compras."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from purchasing.models import PurchaseOrder
from purchasing.test_integration import GeneracionPedidosAdopcionTests


class APIComprasTests(GeneracionPedidosAdopcionTests):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("pedido-editorial-list")
        self.generar_url = reverse("pedido-editorial-generate-from-adoption")

    def test_consulta_requiere_autenticacion(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (401, 403))

    def test_generacion_requiere_autenticacion(self):
        response = self.client.post(self.generar_url, {"adoption_id": self.adopcion.pk})
        self.assertIn(response.status_code, (401, 403))

    def test_administrador_genera_y_lista_pedidos(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.generar_url, {"adoption_id": self.adopcion.pk}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(PurchaseOrder.objects.count(), 2)
        listing = self.client.get(self.url)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 2)

    def test_repeticion_de_api_no_duplica_pedidos(self):
        self.client.force_authenticate(self.user)
        for _ in range(2):
            response = self.client.post(self.generar_url, {"adoption_id": self.adopcion.pk}, format="json")
            self.assertEqual(response.status_code, 200)
        self.assertEqual(PurchaseOrder.objects.count(), 2)

    def test_rechaza_filtros_invalidos(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.url, {"provider": "abc"}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"status": "inventado"}).status_code, 400)

    def test_usuario_sin_permiso_no_consulta_ni_genera(self):
        usuario = get_user_model().objects.create_user(username="sin-permiso-compras")
        self.client.force_authenticate(usuario)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(
            self.client.post(self.generar_url, {"adoption_id": self.adopcion.pk}, format="json").status_code,
            403,
        )
