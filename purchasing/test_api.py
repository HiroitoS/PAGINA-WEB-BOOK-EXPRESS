"""Pruebas de permisos y rutas privadas del módulo de compras."""
import re
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
        pagina = re.search(
            rb"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)\s*\]",
            respuesta.content,
        )
        self.assertIsNotNone(pagina, "La orden debe declarar el tamaño de página.")
        self.assertGreater(float(pagina.group(1)), float(pagina.group(2)), "Debe ser A4 horizontal.")
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

    def test_generacion_individual_solo_editorial_solicitada(self):
        self.client.force_authenticate(self.user)
        editorial_id = self.adopcion.items.first().product.provider_id
        respuesta = self.client.post(
            self.generar_url,
            {"adoption_id": self.adopcion.pk, "provider_id": editorial_id},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(len(respuesta.data), 1)
        self.assertEqual(respuesta.data[0]["provider"], editorial_id)
        self.assertEqual(PurchaseOrder.objects.count(), 1)
        self.assertEqual(PurchaseOrder.objects.get().provider_id, editorial_id)

    def test_generacion_individual_rechaza_editorial_ajena(self):
        self.client.force_authenticate(self.user)
        respuesta = self.client.post(
            self.generar_url,
            {"adoption_id": self.adopcion.pk, "provider_id": 99999999},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.data)
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_guardado_conjunto_cantidades(self):
        pedido = create_orders_from_adoption(
            adoption_id=self.adopcion.pk, actor=self.user,
        )[0]
        detalle = pedido.items.first()
        self.client.force_authenticate(self.user)
        respuesta = self.client.post(
            reverse("pedido-editorial-change-quantities", args=[pedido.pk]),
            {"items": [{"item_id": detalle.pk, "quantity": 55}]},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        detalle.refresh_from_db()
        self.assertEqual(detalle.quantity_ordered, 55)
        self.assertEqual(
            PurchaseOrderEvent.objects.filter(order=pedido, event_type="quantity_changed").count(),
            1,
        )

    def test_guardado_conjunto_invalido_no_modifica_ninguna_linea(self):
        pedidos = create_orders_from_adoption(adoption_id=self.adopcion.pk, actor=self.user)
        pedido, otro = pedidos
        detalle = pedido.items.first()
        detalle_ajeno = otro.items.first()
        anterior = detalle.quantity_ordered
        self.client.force_authenticate(self.user)
        respuesta = self.client.post(
            reverse("pedido-editorial-change-quantities", args=[pedido.pk]),
            {"items": [
                {"item_id": detalle.pk, "quantity": 72},
                {"item_id": detalle_ajeno.pk, "quantity": 55},
            ]},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.data)
        detalle.refresh_from_db()
        self.assertEqual(detalle.quantity_ordered, anterior)
        self.assertFalse(
            PurchaseOrderEvent.objects.filter(order=pedido, event_type="quantity_changed").exists()
        )

    def test_no_modifica_cantidades_con_pedido_aprobado(self):
        pedido = create_orders_from_adoption(
            adoption_id=self.adopcion.pk, actor=self.user,
        )[0]
        detalle = pedido.items.first()
        aprobar_pedido(pedido_id=pedido.pk, actor=self.user)
        self.client.force_authenticate(self.user)
        respuesta = self.client.post(
            reverse("pedido-editorial-change-quantities", args=[pedido.pk]),
            {"items": [{"item_id": detalle.pk, "quantity": 99}]},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.data)

    def test_pdf_solicitud_sin_precios_pedido_aprobado(self):
        pedido = create_orders_from_adoption(
            adoption_id=self.adopcion.pk, actor=self.user,
        )[0]
        aprobar_pedido(pedido_id=pedido.pk, actor=self.user)
        self.client.force_authenticate(self.user)
        respuesta = self.client.get(
            reverse("pedido-editorial-export-purchase-order", args=[pedido.pk]),
            {"formato": "solicitud"},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("BE-SL-", respuesta["Content-Disposition"])
        self.assertTrue(respuesta.content.startswith(b"%PDF"))
        self.assertTrue(
            PurchaseOrderEvent.objects.filter(
                order=pedido, event_type="document_exported",
                notes__icontains="sin precios",
            ).exists()
        )
