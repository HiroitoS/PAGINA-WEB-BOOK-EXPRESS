from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations


MONEY_QUANTUM = Decimal("0.01")


def money(value):
    return Decimal(value or 0).quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def commercial_line_for_item(item):
    product = item.product
    product_type = getattr(product, "product_type", None)

    if product_type is None:
        return "other", ""

    product_type_name = product_type.name or ""
    normalized = " ".join(
        value
        for value in (
            (product_type.slug or "").lower(),
            product_type_name.lower(),
        )
        if value
    )

    if "plan" in normalized and "lector" in normalized:
        return "reading_plan", product_type_name

    if "texto" in normalized and "escolar" in normalized:
        return "school_text", product_type_name

    return "other", product_type_name


def profitability_values(item, commercial_line):
    pvp = money(item.pvp)
    school_price = money(item.school_price)
    supplier_cost = money(item.supplier_cost)
    school_commission = money(item.school_commission)
    quantity = Decimal(item.quantity or 0)
    discount = money(item.school_discount_percent)

    margin_unit = money(
        school_price - supplier_cost - school_commission
    )
    margin_total = money(margin_unit * quantity)

    if school_price > Decimal("0.00"):
        margin_percent = money(
            margin_unit / school_price * Decimal("100.00")
        )
    else:
        margin_percent = Decimal("0.00")

    green_threshold = None
    band = "unclassified"

    if commercial_line == "school_text":
        green_threshold = Decimal("20.00")
        if margin_unit >= Decimal("20.00"):
            band = "green"
        elif margin_unit >= Decimal("15.00"):
            band = "amber"
        elif margin_unit >= Decimal("0.00"):
            band = "red"
        else:
            band = "loss"
    elif commercial_line == "reading_plan":
        green_threshold = Decimal("5.00")
        if margin_unit >= Decimal("5.00"):
            band = "green"
        elif margin_unit > Decimal("2.00"):
            band = "amber"
        elif margin_unit >= Decimal("0.00"):
            band = "red"
        else:
            band = "loss"

    max_green_discount = None
    green_headroom = None

    if green_threshold is not None and pvp > Decimal("0.00"):
        minimum_green_price = (
            supplier_cost + school_commission + green_threshold
        )
        max_green_discount = money(
            (
                Decimal("1.00")
                - (minimum_green_price / pvp)
            )
            * Decimal("100.00")
        )
        green_headroom = money(
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


def backfill_quotation_financial_analysis(apps, schema_editor):
    CommercialQuotationItem = apps.get_model(
        "crm",
        "CommercialQuotationItem",
    )

    items = CommercialQuotationItem.objects.select_related(
        "product__product_type",
    ).all()

    for item in items.iterator():
        product = item.product
        commercial_line, product_type_name = commercial_line_for_item(
            item
        )
        profitability = profitability_values(
            item,
            commercial_line,
        )

        item.product_code_snapshot = (
            product.code or product.sku or item.product_code_snapshot or ""
        )
        item.product_type_name_snapshot = (
            product_type_name
            or item.product_type_name_snapshot
            or ""
        )
        item.commercial_line = commercial_line
        item.commission_mode = "per_unit"
        item.commission_input_amount = money(
            item.school_commission
        )

        for field_name, value in profitability.items():
            setattr(item, field_name, value)

        item.save(
            update_fields=[
                "product_code_snapshot",
                "product_type_name_snapshot",
                "commercial_line",
                "commission_mode",
                "commission_input_amount",
                "commercial_margin_unit",
                "commercial_margin_total",
                "commercial_margin_percent",
                "profitability_band",
                "max_green_discount_percent",
                "green_discount_headroom_points",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0023_quotation_financial_analysis"),
    ]

    operations = [
        migrations.RunPython(
            backfill_quotation_financial_analysis,
            migrations.RunPython.noop,
        ),
    ]
