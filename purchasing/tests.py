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

from types import SimpleNamespace
from django.core.exceptions import ValidationError

from purchasing.order_creation import group_adoption_items_by_provider


class PurchaseOrderEditorialGroupingTests(SimpleTestCase):
    @staticmethod
    def _line(line_id, provider_id, quantity):
        return SimpleNamespace(
            pk=line_id,
            quantity=quantity,
            product=SimpleNamespace(provider_id=provider_id),
        )

    def test_adoption_lines_split_by_provider_without_changing_quantities(self):
        lines = [self._line(1, 10, 100), self._line(2, 20, 40), self._line(3, 10, 80)]
        grouped = group_adoption_items_by_provider(lines)
        self.assertEqual(set(grouped), {10, 20})
        self.assertEqual([line.pk for line in grouped[10]], [1, 3])
        self.assertEqual([line.quantity for line in grouped[10]], [100, 80])
        self.assertEqual([line.pk for line in grouped[20]], [2])

    def test_empty_lines_do_not_generate_groups(self):
        self.assertEqual(group_adoption_items_by_provider([]), {})

    def test_zero_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            group_adoption_items_by_provider([self._line(1, 10, 0)])

    def test_missing_provider_is_rejected(self):
        with self.assertRaises(ValidationError):
            group_adoption_items_by_provider([self._line(1, None, 1)])
