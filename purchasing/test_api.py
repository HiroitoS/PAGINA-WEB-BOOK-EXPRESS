"""Pruebas de permisos y rutas privadas del módulo de compras."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from purchasing.models import PurchaseOrder, PurchaseOrderEvent
from purchasing.order_creation import create_orders_from_adoption
from purchasing.order_management import aprobar_pedido
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

    def test_pdf_pedido_aprobado_se_descarga_y_audita(self):
        pedido = create_orders_from_adoption(
            adoption_id=self.adopcion.pk, actor=self.user,
        )[0]
        aprobar_pedido(pedido_id=pedido.pk, actor=self.user)
        self.client.force_authenticate(self.user)
        respuesta = self.client.get(
            reverse("pedido-editorial-export-purchase-order", args=[pedido.pk])
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Content-Type"], "application/pdf")
        self.assertIn("attachment;", respuesta["Content-Disposition"])
        self.assertTrue(respuesta.content.startswith(b"%PDF"))
        self.assertGreater(len(respuesta.content), 1000)
        self.assertEqual(
            PurchaseOrderEvent.objects.filter(
                order=pedido, event_type="document_exported"
            ).count(), 1,
        )
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, PurchaseOrder.Status.APPROVED)

    def test_pdf_no_disponible_en_borrador(self):
        pedido = create_orders_from_adoption(
            adoption_id=self.adopcion.pk, actor=self.user,
        )[0]
        self.client.force_authenticate(self.user)
        respuesta = self.client.get(
            reverse("pedido-editorial-export-purchase-order", args=[pedido.pk])
        )
        self.assertEqual(respuesta.status_code, 409)
        self.assertFalse(
            PurchaseOrderEvent.objects.filter(
                order=pedido, event_type="document_exported"
            ).exists()
        )

    def test_pdf_requiere_autenticacion(self):
        pedido = create_orders_from_adoption(
            adoption_id=self.adopcion.pk, actor=self.user,
        )[0]
        aprobar_pedido(pedido_id=pedido.pk, actor=self.user)
        self.client.force_authenticate(user=None)
        respuesta = self.client.get(
            reverse("pedido-editorial-export-purchase-order", args=[pedido.pk])
        )
        self.assertIn(respuesta.status_code, (401, 403))
