from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.permissions import usuario_es_administrador
from catalog.models import ProductPrice
from crm.models import (
    CommercialProjection,
    CommercialQuotation,
    CommercialQuotationItem,
    Opportunity,
    PipelineStage,
)
from crm.permissions import usuario_puede_supervisar_crm

from .commercial_lines import (
    OTHER,
    READING_PLAN,
    SCHOOL_TEXT,
    green_margin_threshold,
    resolve_product_commercial_line,
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
    product_type = getattr(product, "product_type", None)

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
        "product_code_snapshot": product.code or product.sku or "",
        "product_type_name_snapshot": (
            product_type.name if product_type else ""
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


def _actor_can_manage_financials(actor):
    if actor is None:
        return False

    return (
        usuario_es_administrador(actor)
        or usuario_puede_supervisar_crm(actor)
    )


def _reading_month_value(value):
    if value in (None, ""):
        return None

    try:
        month = int(value)
    except (TypeError, ValueError) as exc:
        raise CommercialQuotationError(
            "El mes de lectura debe ser un número entre 1 y 12."
        ) from exc

    if month < 1 or month > 12:
        raise CommercialQuotationError(
            "El mes de lectura debe estar entre 1 y 12."
        )

    return month


def _commission_values(
    *,
    payload,
    quantity,
    actor,
    existing_item=None,
):
    can_manage = _actor_can_manage_financials(actor)

    provided_amount = None
    if "commission_amount" in payload:
        provided_amount = payload.get("commission_amount")
    elif "school_commission" in payload:
        provided_amount = payload.get("school_commission")

    if not can_manage:
        if provided_amount not in (None, ""):
            amount = _decimal_value(
                provided_amount,
                field_label="Comisión",
            )
            if amount != Decimal("0.00"):
                raise CommercialQuotationError(
                    (
                        "Solo supervisión comercial puede registrar "
                        "comisiones o incentivos."
                    )
                )

        if existing_item is not None:
            return (
                existing_item.commission_mode,
                existing_item.commission_input_amount,
                existing_item.school_commission,
            )

        return (
            CommercialQuotationItem.CommissionMode.PER_UNIT,
            Decimal("0.00"),
            Decimal("0.00"),
        )

    if "commission_amount" in payload:
        mode = payload.get(
            "commission_mode",
            CommercialQuotationItem.CommissionMode.PER_UNIT,
        )
        amount_value = payload.get("commission_amount")
    elif "school_commission" in payload:
        mode = CommercialQuotationItem.CommissionMode.PER_UNIT
        amount_value = payload.get("school_commission")
    elif existing_item is not None:
        mode = existing_item.commission_mode
        amount_value = existing_item.commission_input_amount
    else:
        mode = CommercialQuotationItem.CommissionMode.PER_UNIT
        amount_value = "0.00"

    valid_modes = {
        CommercialQuotationItem.CommissionMode.PER_UNIT,
        CommercialQuotationItem.CommissionMode.TOTAL,
    }
    if mode not in valid_modes:
        raise CommercialQuotationError(
            "La modalidad de comisión no es válida."
        )

    amount = _money(
        _decimal_value(
            amount_value,
            field_label="Comisión",
        )
    )
    if amount < Decimal("0.00"):
        raise CommercialQuotationError(
            "La comisión no puede ser negativa."
        )

    if mode == CommercialQuotationItem.CommissionMode.TOTAL:
        unit_amount = _money(amount / Decimal(quantity))
    else:
        unit_amount = amount

    return mode, amount, unit_amount


def _profitability_snapshot(
    *,
    commercial_line,
    pvp,
    school_price,
    supplier_cost,
    school_commission,
    quantity,
    discount,
):
    margin_unit = _money(
        school_price - supplier_cost - school_commission
    )
    margin_total = _money(margin_unit * Decimal(quantity))
    margin_percent = Decimal("0.00")

    if school_price > Decimal("0.00"):
        margin_percent = _money(
            margin_unit / school_price * Decimal("100.00")
        )

    green_threshold = None
    band = CommercialQuotationItem.ProfitabilityBand.UNCLASSIFIED

    if (
        commercial_line
        == CommercialQuotationItem.CommercialLine.SCHOOL_TEXT
    ):
        green_threshold = green_margin_threshold(commercial_line)
        if margin_unit > Decimal("20.00"):
            band = CommercialQuotationItem.ProfitabilityBand.GREEN
        elif margin_unit >= Decimal("15.00"):
            band = CommercialQuotationItem.ProfitabilityBand.AMBER
        elif margin_unit >= Decimal("0.00"):
            band = CommercialQuotationItem.ProfitabilityBand.RED
        else:
            band = CommercialQuotationItem.ProfitabilityBand.LOSS
    elif (
        commercial_line
        == CommercialQuotationItem.CommercialLine.READING_PLAN
    ):
        green_threshold = green_margin_threshold(commercial_line)
        if margin_unit > Decimal("5.00"):
            band = CommercialQuotationItem.ProfitabilityBand.GREEN
        elif margin_unit > Decimal("2.00"):
            band = CommercialQuotationItem.ProfitabilityBand.AMBER
        elif margin_unit >= Decimal("0.00"):
            band = CommercialQuotationItem.ProfitabilityBand.RED
        else:
            band = CommercialQuotationItem.ProfitabilityBand.LOSS

    max_green_discount = None
    green_headroom = None

    if (
        green_threshold is not None
        and pvp > Decimal("0.00")
    ):
        minimum_green_price = (
            supplier_cost + school_commission + green_threshold
        )
        max_green_discount = _money(
            (
                Decimal("1.00")
                - (minimum_green_price / pvp)
            )
            * Decimal("100.00")
        )
        green_headroom = _money(
            max_green_discount - discount
        )

    return {
        "commercial_margin_unit": margin_unit,
        "commercial_margin_total": margin_total,
        "commercial_margin_percent": margin_percent,
        "profitability_band": band,
        "max_green_discount_percent": max_green_discount,
        "green_discount_headroom_points": green_headroom,
    }


def _quantity_from_projection(*, projection_item, payload):
    projected_quantity = int(projection_item.quantity)

    if "quantity" not in payload:
        return projected_quantity

    try:
        requested_quantity = int(payload.get("quantity"))
    except (TypeError, ValueError) as exc:
        raise CommercialQuotationError(
            "La cantidad debe ser un número entero."
        ) from exc

    if requested_quantity != projected_quantity:
        raise CommercialQuotationError(
            (
                "La cantidad de la cotización proviene de la proyección. "
                "Modifica la proyección y genera una nueva cotización."
            )
        )

    return projected_quantity


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


def _supplier_cost_value(
    *,
    payload,
    actor,
    projection_item,
    existing_item=None,
):
    provided_cost = payload.get("supplier_cost")

    if provided_cost not in (None, ""):
        if not _actor_can_manage_financials(actor):
            raise CommercialQuotationError(
                (
                    "Solo supervisión comercial puede modificar "
                    "el costo editorial."
                )
            )

        supplier_cost = _money(
            _decimal_value(
                provided_cost,
                field_label="Costo editorial",
            )
        )
        if supplier_cost < Decimal("0.00"):
            raise CommercialQuotationError(
                "El costo editorial no puede ser negativo."
            )
        return supplier_cost

    if existing_item is not None:
        return _money(existing_item.supplier_cost)

    return _money(
        _cost_price_for_projection_item(
            projection_item=projection_item,
        )
    )


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
            "product__product_type",
        )
        .order_by("id")
    )

    if not projection_items:
        raise CommercialQuotationError(
            "La proyección vigente no tiene productos para cotizar."
        )

    if projection.commercial_line == OTHER:
        raise CommercialQuotationError(
            (
                "La proyección vigente no tiene una línea comercial "
                "definida. Genera una nueva versión como Texto escolar "
                "o Plan lector antes de cotizar."
            )
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

        quantity = _quantity_from_projection(
            projection_item=projection_item,
            payload=payload,
        )

        discount = _discount_value(
            payload.get(
                "school_discount_percent",
                STANDARD_SCHOOL_DISCOUNT,
            )
        )
        pvp = _money(projection_item.unit_price)
        supplier_cost = _supplier_cost_value(
            payload=payload,
            actor=actor,
            projection_item=projection_item,
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
        commercial_line = projection.commercial_line
        reading_month = _reading_month_value(
            payload.get("reading_month")
        )
        if commercial_line == READING_PLAN and reading_month is None:
            raise CommercialQuotationError(
                (
                    f"Selecciona el mes de lectura para "
                    f"{projection_item.product.name}."
                )
            )
        if commercial_line == SCHOOL_TEXT:
            reading_month = None

        (
            commission_mode,
            commission_input_amount,
            school_commission,
        ) = _commission_values(
            payload=payload,
            quantity=quantity,
            actor=actor,
        )
        profitability = _profitability_snapshot(
            commercial_line=commercial_line,
            pvp=pvp,
            school_price=school_price,
            supplier_cost=supplier_cost,
            school_commission=school_commission,
            quantity=quantity,
            discount=discount,
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
                "reading_month": reading_month,
                "commission_mode": commission_mode,
                "commission_input_amount": commission_input_amount,
                "school_commission": school_commission,
                "commercial_line": commercial_line,
                **profitability,
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
        commercial_line=projection.commercial_line,
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
            commercial_line=prepared["commercial_line"],
            reading_month=prepared["reading_month"],
            commission_mode=prepared["commission_mode"],
            commission_input_amount=prepared[
                "commission_input_amount"
            ],
            school_commission=prepared["school_commission"],
            commercial_margin_unit=prepared[
                "commercial_margin_unit"
            ],
            commercial_margin_total=prepared[
                "commercial_margin_total"
            ],
            commercial_margin_percent=prepared[
                "commercial_margin_percent"
            ],
            profitability_band=prepared["profitability_band"],
            max_green_discount_percent=prepared[
                "max_green_discount_percent"
            ],
            green_discount_headroom_points=prepared[
                "green_discount_headroom_points"
            ],
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
    actor,
    item_adjustments=None,
    notes="",
):
    locked_quotation = (
        CommercialQuotation.objects
        .select_for_update()
        .select_related("opportunity__campaign")
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
            "product__product_type",
        )
        .order_by("id")
    )

    if not projection_items:
        raise CommercialQuotationError(
            "La proyección de origen no tiene productos para cotizar."
        )

    if projection.commercial_line == OTHER:
        raise CommercialQuotationError(
            (
                "La proyección de origen no tiene una línea comercial "
                "definida. Genera una nueva versión de la proyección."
            )
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

    existing_items_by_product = {
        item.product_id: item
        for item in locked_quotation.items.all()
    }

    prepared_items = []
    requires_approval = False

    for projection_item in projection_items:
        payload = adjustments.get(projection_item.pk, {})

        quantity = _quantity_from_projection(
            projection_item=projection_item,
            payload=payload,
        )

        discount = _discount_value(
            payload.get(
                "school_discount_percent",
                STANDARD_SCHOOL_DISCOUNT,
            )
        )
        pvp = _money(projection_item.unit_price)
        existing_item = existing_items_by_product.get(
            projection_item.product_id
        )
        supplier_cost = _supplier_cost_value(
            payload=payload,
            actor=actor,
            projection_item=projection_item,
            existing_item=existing_item,
        )
        school_price = _money(
            pvp
            * (Decimal("100.00") - discount)
            / Decimal("100.00")
        )
        parent_price = _money(
            _decimal_value(
                payload.get(
                    "parent_price",
                    (
                        existing_item.parent_price
                        if existing_item is not None
                        else pvp
                    ),
                ),
                field_label="Precio PPFF",
            )
        )
        commercial_line = projection.commercial_line
        reading_month = _reading_month_value(
            payload.get(
                "reading_month",
                (
                    existing_item.reading_month
                    if existing_item is not None
                    else None
                ),
            )
        )
        if commercial_line == READING_PLAN and reading_month is None:
            raise CommercialQuotationError(
                (
                    f"Selecciona el mes de lectura para "
                    f"{projection_item.product.name}."
                )
            )
        if commercial_line == SCHOOL_TEXT:
            reading_month = None

        (
            commission_mode,
            commission_input_amount,
            school_commission,
        ) = _commission_values(
            payload=payload,
            quantity=quantity,
            actor=actor,
            existing_item=existing_item,
        )
        profitability = _profitability_snapshot(
            commercial_line=commercial_line,
            pvp=pvp,
            school_price=school_price,
            supplier_cost=supplier_cost,
            school_commission=school_commission,
            quantity=quantity,
            discount=discount,
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
                "reading_month": reading_month,
                "commission_mode": commission_mode,
                "commission_input_amount": commission_input_amount,
                "school_commission": school_commission,
                "commercial_line": commercial_line,
                **profitability,
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
            commercial_line=prepared["commercial_line"],
            reading_month=prepared["reading_month"],
            commission_mode=prepared["commission_mode"],
            commission_input_amount=prepared[
                "commission_input_amount"
            ],
            school_commission=prepared["school_commission"],
            commercial_margin_unit=prepared[
                "commercial_margin_unit"
            ],
            commercial_margin_total=prepared[
                "commercial_margin_total"
            ],
            commercial_margin_percent=prepared[
                "commercial_margin_percent"
            ],
            profitability_band=prepared["profitability_band"],
            max_green_discount_percent=prepared[
                "max_green_discount_percent"
            ],
            green_discount_headroom_points=prepared[
                "green_discount_headroom_points"
            ],
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
    locked_quotation.commercial_line = projection.commercial_line
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
            "commercial_line",
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

    resolved_lines = {
        resolve_product_commercial_line(payload.get("product"))
        for payload in items
        if payload.get("product") is not None
    }
    resolved_lines.discard(OTHER)
    quotation_line = (
        next(iter(resolved_lines))
        if len(resolved_lines) == 1
        else OTHER
    )

    quotation = CommercialQuotation(
        opportunity=locked_opportunity,
        version=current_version + 1,
        status=CommercialQuotation.Status.DRAFT,
        school_name_snapshot=locked_opportunity.school.name,
        campaign_name_snapshot=locked_opportunity.campaign.name,
        commercial_line=quotation_line,
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
            commercial_line=resolve_product_commercial_line(product),
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

    if locked_quotation.status == CommercialQuotation.Status.SENT:
        return locked_quotation

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
            allow_quotation_sent=True,
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

    if locked_quotation.status == CommercialQuotation.Status.ACCEPTED:
        return locked_quotation

    if locked_quotation.status != CommercialQuotation.Status.SENT:
        raise CommercialQuotationError(
            "Solo una cotización enviada puede registrar aceptación."
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

@transaction.atomic
def reopen_commercial_quotation_negotiation(
    *,
    quotation,
    actor,
    reason,
):
    locked_quotation = (
        CommercialQuotation.objects
        .select_for_update()
        .select_related("opportunity")
        .get(pk=quotation.pk)
    )

    if locked_quotation.status != CommercialQuotation.Status.ACCEPTED:
        raise CommercialQuotationError(
            "Solo una cotización aceptada puede reabrir la negociación."
        )

    if locked_quotation.opportunity.is_closed:
        raise CommercialQuotationError(
            "No se puede reabrir una negociación de una oportunidad cerrada."
        )

    if locked_quotation.opportunity.adoptions.filter(
        is_current=True,
    ).exists():
        raise CommercialQuotationError(
            (
                "La oportunidad ya tiene una adopción vigente. "
                "Los cambios posteriores deben gestionarse desde Adopción."
            )
        )

    cleaned_reason = (reason or "").strip()
    if not cleaned_reason:
        raise CommercialQuotationError(
            "Registra el motivo para reabrir la negociación."
        )

    locked_quotation.status = CommercialQuotation.Status.SUPERSEDED
    locked_quotation.reopened_at = timezone.now()
    locked_quotation.reopened_by = actor
    locked_quotation.reopen_reason = cleaned_reason
    locked_quotation.save(
        update_fields=[
            "status",
            "reopened_at",
            "reopened_by",
            "reopen_reason",
            "updated_at",
        ]
    )

    return locked_quotation

