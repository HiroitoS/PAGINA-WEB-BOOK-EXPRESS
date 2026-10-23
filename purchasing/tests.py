"""Model contract tests for the first ERP purchase-order milestone."""
from django.test import SimpleTestCase, TestCase

from purchasing.models import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem


class PurchaseOrderModelContractTests(SimpleTestCase):
    def test_order_origin_and_status_are_distinct(self):
        self.assertEqual(PurchaseOrder.Origin.ADOPTION, "adoption")
        self.assertEqual(PurchaseOrder.Origin.MANUAL, "manual")
        self.assertNotEqual(PurchaseOrder.Status.SENT, PurchaseOrder.Status.RECEIVED)

    def test_order_preserves_optional_adoption_link(self):
        adoption_field = PurchaseOrder._meta.get_field("adoption")
        self.assertTrue(adoption_field.null)
        self.assertEqual(adoption_field.remote_field.model._meta.label, "crm.Adoption")

    def test_order_item_has_requested_quantity_not_received_stock(self):
        self.assertIsNotNone(PurchaseOrderItem._meta.get_field("quantity_ordered"))
        self.assertIsNotNone(PurchaseOrderItem._meta.get_field("unit_supplier_cost"))
        self.assertNotIn("quantity_received", [field.name for field in PurchaseOrderItem._meta.fields])

    def test_purchase_events_reference_original_order(self):
        self.assertEqual(PurchaseOrderEvent._meta.get_field("order").remote_field.model, PurchaseOrder)

    def test_order_has_database_duplicate_guard(self):
        names = {constraint.name for constraint in PurchaseOrder._meta.constraints}
        self.assertIn("purch_order_once_per_adoption_provider", names)

    def test_purchase_item_has_database_quantity_guard(self):
        names = {constraint.name for constraint in PurchaseOrderItem._meta.constraints}
        self.assertIn("purch_item_quantity_positive", names)

from unittest.mock import patch

from django.core.exceptions import PermissionDenied

from purchasing.order_creation import create_orders_from_adoption


class PurchaseOrderCreationPermissionTests(TestCase):
    def test_anonymous_actor_is_rejected_before_database_access(self):
        with self.assertRaises(PermissionDenied):
            create_orders_from_adoption(adoption_id=1, actor=None)

    def test_authenticated_user_without_purchasing_permission_is_rejected(self):
        class User:
            is_authenticated = True

        with patch("purchasing.order_creation.usuario_tiene_permiso", return_value=False):
            with self.assertRaises(PermissionDenied):
                create_orders_from_adoption(adoption_id=1, actor=User())
