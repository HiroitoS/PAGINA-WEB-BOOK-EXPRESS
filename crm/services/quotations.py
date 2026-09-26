from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from catalog.models import ProductPrice
from crm.models import (
    CommercialProjection,
    CommercialQuotation,
    CommercialQuotationItem,
    Opportunity,
    PipelineStage,
)

from .opportunities import transition_opportunity_stage


class CommercialQuotationError(ValidationError):
    pass


def _decimal_value(value, *, field_label):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommercialQuotationError(
            f"{field_label} debe ser un importe válido."
        ) from exc


def _product_snapshot(product):
    return {
        "product_name_snapshot": product.name,
        "provider_name_snapshot": product.provider.name,
        "level_name_snapshot": (
            product.level.name if product.level_id else ""
        ),
        "grade_name_snapshot": (
            product.grade.name if product.grade_id else ""
        ),
        "area_name_snapshot": (
            product.area.name if product.area_id else ""
        ),
    }


STANDARD_SCHOOL_DISCOUNT = Decimal("20.00")
MONEY_QUANTUM = Decimal("0.01")


def _money(value):
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _discount_value(value):
    discount = _decimal_value(
        value,
        field_label="Descuento colegio",
    )
    if discount < Decimal("0.00") or discount > Decimal("100.00"):
        raise CommercialQuotationError(
            "El descuento colegio debe estar entre 0% y 100%."
        )
    return discount


def _cost_price_for_projection_item(*, projection_item):
    prices = ProductPrice.objects.filter(
        product=projection_item.product,
        year=projection_item.price_year_snapshot,
        is_active=True,
    )

    exact = prices.filter(
        campaign__iexact=projection_item.price_campaign_snapshot,
    )
    exact_count = exact.count()

    if exact_count > 1:
        raise CommercialQuotationError(
            (
                f"{projection_item.product.name} tiene más de un precio "
                f"activo para {projection_item.price_year_snapshot} y "
                f"{projection_item.price_campaign_snapshot}."
            )
        )

    price = exact.first() if exact_count == 1 else None

    if price is None:
        price_count = prices.count()
        if price_count == 1:
            price = prices.first()
        elif price_count > 1:
            raise CommercialQuotationError(
                (
                    f"{projection_item.product.name} tiene precios activos "
                    f"ambiguos para {projection_item.price_year_snapshot}."
                )
            )

    if price is None or price.cost_price is None:
        raise CommercialQuotationError(
            (
                f"{projection_item.product.name} no tiene precio costo "
                f"registrado para {projection_item.price_year_snapshot}. "
                "Completa el precio del catálogo antes de cotizar."
            )
        )

    return price.cost_price


@transaction.atomic
def create_commercial_quotation_from_projection(
    *,
    opportunity,
    actor,
    item_adjustments=None,
    notes="",
):
    locked_opportunity = (
        Opportunity.objects
        .select_for_update()
        .select_related("school", "campaign", "stage")
        .get(pk=opportunity.pk)
    )

    if locked_opportunity.is_closed:
        raise CommercialQuotationError(
            "No se puede cotizar una oportunidad cerrada."
        )

    if locked_opportunity.quotations.filter(
        status=CommercialQuotation.Status.ACCEPTED,
    ).exists():
        raise CommercialQuotationError(
            "La oportunidad ya tiene una cotización aceptada."
        )

    projection = (
        CommercialProjection.objects
        .select_for_update()
        .filter(
            opportunity=locked_opportunity,
            is_current=True,
        )
        .first()
    )

    if projection is None:
        raise CommercialQuotationError(
            "Primero registra una proyección comercial vigente."
        )

    projection_items = list(
        projection.items
        .select_related(
            "product__provider",
            "product__level",
            "product__grade",
            "product__area",
        )
        .order_by("id")
    )

    if not projection_items:
        raise CommercialQuotationError(
            "La proyección vigente no tiene productos para cotizar."
        )

    adjustments = {}
    for payload in item_adjustments or []:
        projection_item = payload.get("projection_item")
        if projection_item is None:
            raise CommercialQuotationError(
                "Cada ajuste debe indicar el producto proyectado."
            )
        if projection_item.projection_id != projection.id:
            raise CommercialQuotationError(
                "El producto proyectado no pertenece a la proyección vigente."
            )
        if projection_item.pk in adjustments:
            raise CommercialQuotationError(
                "No se puede repetir un producto proyectado en la cotización."
            )
        adjustments[projection_item.pk] = payload

    prepared_items = []
    requires_approval = False

    for projection_item in projection_items:
        payload = adjustments.get(projection_item.pk, {})

        try:
            quantity = int(
                payload.get("quantity", projection_item.quantity)
            )
        except (TypeError, ValueError) as exc:
            raise CommercialQuotationError(
                "La cantidad debe ser un número entero."
            ) from exc

        if quantity < 1:
            raise CommercialQuotationError(
                "La cantidad debe ser mayor que cero."
            )

        discount = _discount_value(
            payload.get(
                "school_discount_percent",
                STANDARD_SCHOOL_DISCOUNT,
            )
        )
        pvp = _money(projection_item.unit_price)
        supplier_cost = _money(
            _cost_price_for_projection_item(
                projection_item=projection_item,
            )
        )
        school_price = _money(
            pvp * (Decimal("100.00") - discount) / Decimal("100.00")
        )
        parent_price = _money(
            _decimal_value(
                payload.get("parent_price", pvp),
                field_label="Precio PPFF",
            )
        )
        school_commission = _money(
            _decimal_value(
                payload.get("school_commission", "0.00"),
                field_label="Comisión colegio",
            )
        )

        if discount > STANDARD_SCHOOL_DISCOUNT:
            requires_approval = True

        prepared_items.append(
            {
                "projection_item": projection_item,
                "product": projection_item.product,
                "quantity": quantity,
                "pvp": pvp,
                "supplier_cost": supplier_cost,
                "school_price": school_price,
                "school_discount_percent": discount,
                "parent_price": parent_price,
                "school_commission": school_commission,
                "price_year_snapshot": (
                    projection_item.price_year_snapshot
                ),
                "price_campaign_snapshot": (
                    projection_item.price_campaign_snapshot
                ),
                "uses_reference_price": (
                    projection_item.price_year_snapshot
                    < locked_opportunity.campaign.year
                ),
            }
        )

    current_version = (
        locked_opportunity.quotations
        .aggregate(max_version=Max("version"))
        .get("max_version")
        or 0
    )

    quotation = CommercialQuotation(
        opportunity=locked_opportunity,
        source_projection=projection,
        version=current_version + 1,
        status=CommercialQuotation.Status.DRAFT,
        school_name_snapshot=locked_opportunity.school.name,
        campaign_name_snapshot=locked_opportunity.campaign.name,
        notes=(notes or "").strip(),
        requires_discount_approval=requires_approval,
        discount_approval_status=(
            CommercialQuotation.DiscountApprovalStatus.PENDING
            if requires_approval
            else CommercialQuotation.DiscountApprovalStatus.NOT_REQUIRED
        ),
        created_by=actor,
    )
    quotation.full_clean()
    quotation.save()

    for prepared in prepared_items:
        product = prepared["product"]
        item = CommercialQuotationItem(
            quotation=quotation,
            product=product,
            quantity=prepared["quantity"],
            pvp=prepared["pvp"],
            supplier_cost=prepared["supplier_cost"],
            school_price=prepared["school_price"],
            school_discount_percent=prepared[
                "school_discount_percent"
            ],
            parent_price=prepared["parent_price"],
            school_commission=prepared["school_commission"],
            price_year_snapshot=prepared["price_year_snapshot"],
            price_campaign_snapshot=prepared[
                "price_campaign_snapshot"
            ],
            uses_reference_price=prepared["uses_reference_price"],
            **_product_snapshot(product),
        )
        item.full_clean()
        item.save()

    return quotation


@transaction.atomic
def update_commercial_quotation_from_projection(
    *,
    quotation,
    item_adjustments=None,
    notes="",
):
    locked_quotation = (
        CommercialQuotation.objects
        .select_for_update()
        .select_related(
            "opportunity__campaign",
            "source_projection",
        )
        .get(pk=quotation.pk)
    )

    if locked_quotation.status != CommercialQuotation.Status.DRAFT:
        raise CommercialQuotationError(
            "Solo una cotización en borrador puede editarse."
        )

    if locked_quotation.source_projection_id is None:
        raise CommercialQuotationError(
            (
                "Esta cotización no tiene una proyección de origen y "
                "no puede editarse desde este flujo."
            )
        )

    projection = (
        CommercialProjection.objects
        .select_for_update()
        .get(pk=locked_quotation.source_projection_id)
    )

    projection_items = list(
        projection.items
        .select_related(
            "product__provider",
            "product__level",
            "product__grade",
            "product__area",
        )
        .order_by("id")
    )

    if not projection_items:
        raise CommercialQuotationError(
            "La proyección de origen no tiene productos para cotizar."
        )

    adjustments = {}
    for payload in item_adjustments or []:
        projection_item = payload.get("projection_item")

        if projection_item is None:
            raise CommercialQuotationError(
                "Cada ajuste debe indicar el producto proyectado."
            )

        if projection_item.projection_id != projection.id:
            raise CommercialQuotationError(
                (
                    "El producto proyectado no pertenece a la "
                    "proyección de origen de la cotización."
                )
            )

        if projection_item.pk in adjustments:
            raise CommercialQuotationError(
                "No se puede repetir un producto proyectado en la cotización."
            )

        adjustments[projection_item.pk] = payload

    prepared_items = []
    requires_approval = False

    for projection_item in projection_items:
        payload = adjustments.get(projection_item.pk, {})

        try:
            quantity = int(
                payload.get("quantity", projection_item.quantity)
            )
        except (TypeError, ValueError) as exc:
            raise CommercialQuotationError(
                "La cantidad debe ser un número entero."
            ) from exc

        if quantity < 1:
            raise CommercialQuotationError(
                "La cantidad debe ser mayor que cero."
            )

        discount = _discount_value(
            payload.get(
                "school_discount_percent",
                STANDARD_SCHOOL_DISCOUNT,
            )
        )
        pvp = _money(projection_item.unit_price)
        supplier_cost = _money(
            _cost_price_for_projection_item(
                projection_item=projection_item,
            )
        )
        school_price = _money(
            pvp
            * (Decimal("100.00") - discount)
            / Decimal("100.00")
        )
        parent_price = _money(
            _decimal_value(
                payload.get("parent_price", pvp),
                field_label="Precio PPFF",
            )
        )
        school_commission = _money(
            _decimal_value(
                payload.get("school_commission", "0.00"),
                field_label="Comisión colegio",
            )
        )

        if discount > STANDARD_SCHOOL_DISCOUNT:
            requires_approval = True

        prepared_items.append(
            {
                "product": projection_item.product,
                "quantity": quantity,
                "pvp": pvp,
                "supplier_cost": supplier_cost,
                "school_price": school_price,
                "school_discount_percent": discount,
                "parent_price": parent_price,
                "school_commission": school_commission,
                "price_year_snapshot": (
                    projection_item.price_year_snapshot
                ),
                "price_campaign_snapshot": (
                    projection_item.price_campaign_snapshot
                ),
                "uses_reference_price": (
                    projection_item.price_year_snapshot
                    < locked_quotation.opportunity.campaign.year
                ),
            }
        )

    locked_quotation.items.all().delete()

    for prepared in prepared_items:
        product = prepared["product"]
        item = CommercialQuotationItem(
            quotation=locked_quotation,
            product=product,
            quantity=prepared["quantity"],
            pvp=prepared["pvp"],
            supplier_cost=prepared["supplier_cost"],
            school_price=prepared["school_price"],
            school_discount_percent=prepared[
                "school_discount_percent"
            ],
            parent_price=prepared["parent_price"],
            school_commission=prepared["school_commission"],
            price_year_snapshot=prepared["price_year_snapshot"],
            price_campaign_snapshot=prepared[
                "price_campaign_snapshot"
            ],
            uses_reference_price=prepared["uses_reference_price"],
            **_product_snapshot(product),
        )
        item.full_clean()
        item.save()

    locked_quotation.notes = (notes or "").strip()
    locked_quotation.requires_discount_approval = requires_approval
    locked_quotation.discount_approval_status = (
        CommercialQuotation.DiscountApprovalStatus.PENDING
        if requires_approval
        else CommercialQuotation.DiscountApprovalStatus.NOT_REQUIRED
    )
    locked_quotation.discount_approved_at = None
    locked_quotation.discount_approved_by = None
    locked_quotation.discount_approval_note = ""
    locked_quotation.full_clean()
    locked_quotation.save(
        update_fields=[
            "notes",
            "requires_discount_approval",
            "discount_approval_status",
            "discount_approved_at",
            "discount_approved_by",
            "discount_approval_note",
            "updated_at",
        ]
    )

    return locked_quotation


@transaction.atomic
def approve_commercial_quotation_discount(
    *,
    quotation,
    actor,
    note="",
):
    locked_quotation = (
        CommercialQuotation.objects
        .select_for_update()
        .get(pk=quotation.pk)
    )

    if locked_quotation.status != CommercialQuotation.Status.DRAFT:
        raise CommercialQuotationError(
            "Solo se puede aprobar el descuento de una cotización en borrador."
        )

    if not locked_quotation.requires_discount_approval:
        raise CommercialQuotationError(
            "Esta cotización no requiere aprobación adicional de descuento."
        )

    locked_quotation.discount_approval_status = (
        CommercialQuotation.DiscountApprovalStatus.APPROVED
    )
    locked_quotation.discount_approved_at = timezone.now()
    locked_quotation.discount_approved_by = actor
    locked_quotation.discount_approval_note = (note or "").strip()
    locked_quotation.save(
        update_fields=[
            "discount_approval_status",
            "discount_approved_at",
            "discount_approved_by",
            "discount_approval_note",
            "updated_at",
        ]
    )

    return locked_quotation


@transaction.atomic
def create_commercial_quotation(
    *,
    opportunity,
    actor,
    items,
    notes="",
):
    locked_opportunity = (
        Opportunity.objects
        .select_for_update()
        .select_related("school", "campaign", "stage")
        .get(pk=opportunity.pk)
    )

    if locked_opportunity.is_closed:
        raise CommercialQuotationError(
            "No se puede cotizar una oportunidad cerrada."
        )

    if not items:
        raise CommercialQuotationError(
            "La cotización debe incluir al menos un producto."
        )

    if locked_opportunity.quotations.filter(
        status=CommercialQuotation.Status.ACCEPTED,
    ).exists():
        raise CommercialQuotationError(
            "La oportunidad ya tiene una cotización aceptada."
        )

    current_version = (
        locked_opportunity.quotations
        .aggregate(max_version=Max("version"))
        .get("max_version")
        or 0
    )

    quotation = CommercialQuotation(
        opportunity=locked_opportunity,
        version=current_version + 1,
        status=CommercialQuotation.Status.DRAFT,
        school_name_snapshot=locked_opportunity.school.name,
        campaign_name_snapshot=locked_opportunity.campaign.name,
        notes=(notes or "").strip(),
        created_by=actor,
    )
    quotation.full_clean()
    quotation.save()

    for payload in items:
        product = payload.get("product")

        if product is None:
            raise CommercialQuotationError(
                "Cada ítem debe indicar un producto."
            )

        if not product.is_active:
            raise CommercialQuotationError(
                f"El producto {product.name} está inactivo."
            )

        try:
            quantity = int(payload.get("quantity"))
        except (TypeError, ValueError) as exc:
            raise CommercialQuotationError(
                "La cantidad debe ser un número entero."
            ) from exc

        item = CommercialQuotationItem(
            quotation=quotation,
            product=product,
            quantity=quantity,
            pvp=_decimal_value(
                payload.get("pvp"),
                field_label="PVP",
            ),
            supplier_cost=_decimal_value(
                payload.get("supplier_cost"),
                field_label="Costo editorial",
            ),
            school_price=_decimal_value(
                payload.get("school_price"),
                field_label="Precio colegio",
            ),
            parent_price=_decimal_value(
                payload.get("parent_price"),
                field_label="Precio PPFF",
            ),
            school_commission=_decimal_value(
                payload.get("school_commission", "0.00"),
                field_label="Comisión colegio",
            ),
            **_product_snapshot(product),
        )
        item.full_clean()
        item.save()

    return quotation


@transaction.atomic
def send_commercial_quotation(*, quotation, actor):
    locked_quotation = (
        CommercialQuotation.objects
        .select_for_update()
        .select_related(
            "opportunity__pipeline",
            "opportunity__stage",
        )
        .get(pk=quotation.pk)
    )

    if locked_quotation.status != CommercialQuotation.Status.DRAFT:
        raise CommercialQuotationError(
            "Solo una cotización en borrador puede enviarse."
        )

    if not locked_quotation.items.exists():
        raise CommercialQuotationError(
            "No se puede enviar una cotización sin productos."
        )

    if locked_quotation.items.filter(
        uses_reference_price=True,
    ).exists():
        raise CommercialQuotationError(
            (
                "La cotización usa precios referenciales de una campaña "
                "anterior. Actualiza los precios de la campaña antes de "
                "enviarla al colegio."
            )
        )

    if (
        locked_quotation.requires_discount_approval
        and locked_quotation.discount_approval_status
        != CommercialQuotation.DiscountApprovalStatus.APPROVED
    ):
        raise CommercialQuotationError(
            (
                "La cotización supera el descuento comercial estándar "
                "del 20% y necesita aprobación del supervisor comercial."
            )
        )

    if locked_quotation.opportunity.quotations.exclude(
        pk=locked_quotation.pk,
    ).filter(
        status=CommercialQuotation.Status.ACCEPTED,
    ).exists():
        raise CommercialQuotationError(
            "Existe otra cotización aceptada para esta oportunidad."
        )

    quotation_stage = (
        PipelineStage.objects
        .filter(
            pipeline=locked_quotation.opportunity.pipeline,
            code="cotizacion_enviada",
            category=PipelineStage.Category.OPEN,
            is_active=True,
        )
        .first()
    )

    if quotation_stage is None:
        raise CommercialQuotationError(
            "El pipeline no tiene configurada la etapa de cotización enviada."
        )

    locked_quotation.opportunity.quotations.exclude(
        pk=locked_quotation.pk,
    ).filter(
        status__in=[
            CommercialQuotation.Status.DRAFT,
            CommercialQuotation.Status.SENT,
        ],
    ).update(
        status=CommercialQuotation.Status.SUPERSEDED,
        updated_at=timezone.now(),
    )

    locked_quotation.status = CommercialQuotation.Status.SENT
    locked_quotation.sent_at = timezone.now()
    locked_quotation.sent_by = actor
    locked_quotation.save(
        update_fields=[
            "status",
            "sent_at",
            "sent_by",
            "updated_at",
        ]
    )

    if locked_quotation.opportunity.stage_id != quotation_stage.id:
        transition_opportunity_stage(
            opportunity=locked_quotation.opportunity,
            to_stage=quotation_stage,
            changed_by=actor,
            note=(
                f"Cotización v{locked_quotation.version} enviada."
            ),
        )

    return locked_quotation


@transaction.atomic
def accept_commercial_quotation(*, quotation, actor):
    locked_quotation = (
        CommercialQuotation.objects
        .select_for_update()
        .select_related("opportunity")
        .get(pk=quotation.pk)
    )

    if locked_quotation.status != CommercialQuotation.Status.SENT:
        raise CommercialQuotationError(
            "Solo una cotización enviada puede marcarse como aceptada."
        )

    if locked_quotation.opportunity.quotations.exclude(
        pk=locked_quotation.pk,
    ).filter(
        status=CommercialQuotation.Status.ACCEPTED,
    ).exists():
        raise CommercialQuotationError(
            "La oportunidad ya tiene otra cotización aceptada."
        )

    locked_quotation.opportunity.quotations.exclude(
        pk=locked_quotation.pk,
    ).filter(
        status__in=[
            CommercialQuotation.Status.DRAFT,
            CommercialQuotation.Status.SENT,
        ],
    ).update(
        status=CommercialQuotation.Status.SUPERSEDED,
        updated_at=timezone.now(),
    )

    locked_quotation.status = CommercialQuotation.Status.ACCEPTED
    locked_quotation.accepted_at = timezone.now()
    locked_quotation.accepted_by = actor
    locked_quotation.save(
        update_fields=[
            "status",
            "accepted_at",
            "accepted_by",
            "updated_at",
        ]
    )

    return locked_quotation
