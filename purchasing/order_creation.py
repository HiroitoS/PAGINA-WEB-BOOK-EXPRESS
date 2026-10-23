"""Create draft editorial orders from one confirmed adoption.

A database uniqueness constraint on (adoption, provider) makes repeat requests
idempotent. Lock the adoption row to serialize concurrent generators.
"""
from collections import defaultdict

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from accounts.permissions import usuario_tiene_permiso
from crm.models import Adoption

from purchasing.models import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem


def group_adoption_items_by_provider(lines):
    """Keep each adoption line under its catalog editorial; never merge schools."""
    grouped = defaultdict(list)
    for line in lines:
        if line.quantity < 1:
            raise ValidationError(f"Cantidad inválida en el ítem {line.pk}.")
        if not line.product.provider_id:
            raise ValidationError(f"El producto del ítem {line.pk} no tiene editorial.")
        grouped[line.product.provider_id].append(line)
    return grouped


@transaction.atomic
def create_orders_from_adoption(*, adoption_id, actor):
    """Return existing or newly generated draft orders, one per editorial.

    Does not approve or send them. Does not calculate inventory requirements.
    If the adoption has already generated orders, existing orders are returned
    unchanged: regenerating must never silently rewrite approved documents.
    """
    if not actor or not actor.is_authenticated or not usuario_tiene_permiso(
        actor, "purchasing.manage_purchasing"
    ):
        raise PermissionDenied("No tienes permiso para preparar pedidos.")

    adoption = (
        Adoption.objects.select_for_update()
        .select_related("school", "campaign")
        .get(pk=adoption_id)
    )
    if not adoption.is_current or not adoption.confirmed_at:
        raise ValidationError("Solo se pueden generar pedidos desde una adopción vigente y confirmada.")

    lines = list(
        adoption.items.select_related("product__provider")
        .order_by("pk")
    )
    if not lines:
        raise ValidationError("La adopción confirmada no contiene productos.")

    grouped = group_adoption_items_by_provider(lines)

    result = []
    for provider_id, items in sorted(grouped.items()):
        provider = items[0].product.provider
        existing = PurchaseOrder.objects.filter(
            adoption=adoption, provider_id=provider_id
        ).first()
        if existing:
            result.append(existing)
            continue

        order = PurchaseOrder(
            origin=PurchaseOrder.Origin.ADOPTION,
            provider=provider,
            school=adoption.school,
            campaign=adoption.campaign,
            adoption=adoption,
            provider_name_snapshot=provider.name,
            school_name_snapshot=adoption.school_name_snapshot,
            campaign_name_snapshot=adoption.campaign_name_snapshot,
            created_by=actor,
        )
        order.full_clean()
        order.save()

        order_lines = []
        for item in items:
            line = PurchaseOrderItem(
                order=order,
                product=item.product,
                adoption_item=item,
                product_name_snapshot=item.product_name_snapshot,
                product_code_snapshot=item.product.code or "",
                quantity_ordered=item.quantity,
                unit_supplier_cost=item.supplier_cost,
                currency="PEN",
            )
            line.full_clean()
            order_lines.append(line)
        PurchaseOrderItem.objects.bulk_create(order_lines)
        PurchaseOrderEvent.objects.create(
            order=order,
            actor=actor,
            event_type="created_from_adoption",
            to_status=PurchaseOrder.Status.DRAFT,
            details={"adoption_id": adoption.pk, "item_count": len(order_lines)},
        )
        result.append(order)

    return result
