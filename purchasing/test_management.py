"""Pruebas operativas de pedidos: borrador, aprobación y envío."""
from django.core.exceptions import ValidationError

from purchasing.models import PurchaseOrder, PurchaseOrderEvent
from purchasing.order_creation import create_orders_from_adoption
from purchasing.order_management import (
    actualizar_cantidad_borrador, aprobar_pedido, registrar_envio_pedido,
)
from purchasing.test_integration import GeneracionPedidosAdopcionTests


class GestionPedidoTests(GeneracionPedidosAdopcionTests):
    # Las pruebas heredadas deben ejecutarse sin pedidos preexistentes.
    # La preparación de cada prueba operativa se realiza solo para esos casos.
    def setUp(self):
        if self._testMethodName.startswith("test_") and self._testMethodName in {
            "test_actualizar_cantidad_solo_en_borrador",
            "test_aprobar_y_registrar_envio",
            "test_prohibir_envio_sin_aprobacion",
            "test_exigir_evidencia",
        }:
            self.pedido = create_orders_from_adoption(
                adoption_id=self.adopcion.pk, actor=self.user,
            )[0]

    def test_actualizar_cantidad_solo_en_borrador(self):
        item = self.pedido.items.first()
        actualizar_cantidad_borrador(
            pedido_id=self.pedido.pk, detalle_id=item.pk,
            cantidad=87, actor=self.user,
        )
        item.refresh_from_db()
        self.assertEqual(item.quantity_ordered, 87)
        self.assertTrue(PurchaseOrderEvent.objects.filter(
            order=self.pedido, event_type="quantity_changed"
        ).exists())
        aprobar_pedido(pedido_id=self.pedido.pk, actor=self.user)
        with self.assertRaises(ValidationError):
            actualizar_cantidad_borrador(
                pedido_id=self.pedido.pk, detalle_id=item.pk,
                cantidad=90, actor=self.user,
            )

    def test_aprobar_y_registrar_envio(self):
        aprobar_pedido(pedido_id=self.pedido.pk, actor=self.user)
        registrar_envio_pedido(
            pedido_id=self.pedido.pk, actor=self.user,
            evidencia="Enviado desde Outlook, referencia de prueba.",
        )
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.status, PurchaseOrder.Status.SENT)
        self.assertIsNotNone(self.pedido.sent_at)
        self.assertEqual(self.pedido.events.filter(event_type="sent").count(), 1)

    def test_prohibir_envio_sin_aprobacion(self):
        with self.assertRaises(ValidationError):
            registrar_envio_pedido(
                pedido_id=self.pedido.pk, actor=self.user, evidencia="Correo",
            )

    def test_exigir_evidencia(self):
        aprobar_pedido(pedido_id=self.pedido.pk, actor=self.user)
        with self.assertRaises(ValidationError):
            registrar_envio_pedido(
                pedido_id=self.pedido.pk, actor=self.user, evidencia=" ",
            )
