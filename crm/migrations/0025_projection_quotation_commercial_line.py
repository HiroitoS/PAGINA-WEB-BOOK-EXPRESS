from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models
from django.utils.text import slugify


SCHOOL_TEXT = "school_text"
READING_PLAN = "reading_plan"
OTHER = "other"
MONEY = Decimal("0.01")


def _norm(value):
    return slugify(str(value or "")).lower()


def _product_line(product):
    explicit_line = getattr(product, "commercial_line", OTHER)
    if explicit_line in {SCHOOL_TEXT, READING_PLAN}:
        return explicit_line

    product_type = getattr(product, "product_type", None)
    area = getattr(product, "area", None)
    series = getattr(product, "series", None)

    signals = [
        _norm(getattr(product_type, "name", "")),
        _norm(getattr(product_type, "slug", "")),
        _norm(getattr(area, "name", "")),
        _norm(getattr(area, "slug", "")),
        _norm(getattr(series, "name", "")),
        _norm(getattr(series, "slug", "")),
        _norm(getattr(product, "name", "")),
    ]
    joined = " ".join(filter(None, signals))

    if any(
        marker in joined
        for marker in ("plan-lector", "plan-de-lectura", "lectura-plan")
    ):
        return READING_PLAN

    if any(
        marker in joined
        for marker in (
            "texto-escolar",
            "textos-escolares",
            "proyecto-evolucion",
            "pack-proyecto",
        )
    ):
        return SCHOOL_TEXT

    if product.level_id and product.grade_id and product.area_id:
        return SCHOOL_TEXT

    return OTHER


def _projection_line(projection):
    resolved = set()
    for item in projection.items.select_related(
        "product__product_type",
        "product__area",
        "product__series",
    ):
        line = _product_line(item.product)
        if line != OTHER:
            resolved.add(line)

    if len(resolved) == 1:
        return next(iter(resolved))

    return OTHER


def _quotation_line(quotation):
    if quotation.source_projection_id:
        line = quotation.source_projection.commercial_line
        if line != OTHER:
            return line

    resolved = {
        item.commercial_line
        for item in quotation.items.all()
        if item.commercial_line != OTHER
    }
    if len(resolved) == 1:
        return next(iter(resolved))

    return OTHER


def _profitability(line, margin_unit):
    if line == SCHOOL_TEXT:
        if margin_unit > Decimal("20.00"):
            return "green", Decimal("20.01")
        if margin_unit >= Decimal("15.00"):
            return "amber", Decimal("20.01")
        if margin_unit >= Decimal("0.00"):
            return "red", Decimal("20.01")
        return "loss", Decimal("20.01")

    if line == READING_PLAN:
        if margin_unit > Decimal("5.00"):
            return "green", Decimal("5.01")
        if margin_unit > Decimal("2.00"):
            return "amber", Decimal("5.01")
        if margin_unit >= Decimal("0.00"):
            return "red", Decimal("5.01")
        return "loss", Decimal("5.01")

    return "unclassified", None


def backfill_commercial_lines(apps, schema_editor):
    CommercialProjection = apps.get_model("crm", "CommercialProjection")
    CommercialQuotation = apps.get_model("crm", "CommercialQuotation")
    CommercialQuotationItem = apps.get_model("crm", "CommercialQuotationItem")

    for projection in CommercialProjection.objects.all().iterator():
        line = _projection_line(projection)
        CommercialProjection.objects.filter(pk=projection.pk).update(
            commercial_line=line,
        )

    items = CommercialQuotationItem.objects.select_related(
        "product__product_type",
        "product__area",
        "product__series",
    )

    for item in items.iterator():
        line = _product_line(item.product)
        margin_unit = (
            item.school_price
            - item.supplier_cost
            - item.school_commission
        ).quantize(MONEY, rounding=ROUND_HALF_UP)
        margin_total = (
            margin_unit * Decimal(item.quantity)
        ).quantize(MONEY, rounding=ROUND_HALF_UP)

        margin_percent = Decimal("0.00")
        if item.school_price > Decimal("0.00"):
            margin_percent = (
                margin_unit / item.school_price * Decimal("100.00")
            ).quantize(MONEY, rounding=ROUND_HALF_UP)

        band, threshold = _profitability(line, margin_unit)
        max_green_discount = None
        green_headroom = None

        if threshold is not None and item.pvp > Decimal("0.00"):
            minimum_green_price = (
                item.supplier_cost + item.school_commission + threshold
            )
            max_green_discount = (
                (
                    Decimal("1.00")
                    - (minimum_green_price / item.pvp)
                )
                * Decimal("100.00")
            ).quantize(MONEY, rounding=ROUND_HALF_UP)
            green_headroom = (
                max_green_discount - item.school_discount_percent
            ).quantize(MONEY, rounding=ROUND_HALF_UP)

        CommercialQuotationItem.objects.filter(pk=item.pk).update(
            commercial_line=line,
            commercial_margin_unit=margin_unit,
            commercial_margin_total=margin_total,
            commercial_margin_percent=margin_percent,
            profitability_band=band,
            max_green_discount_percent=max_green_discount,
            green_discount_headroom_points=green_headroom,
        )

    for quotation in CommercialQuotation.objects.select_related(
        "source_projection"
    ).prefetch_related("items").iterator(chunk_size=200):
        CommercialQuotation.objects.filter(pk=quotation.pk).update(
            commercial_line=_quotation_line(quotation),
        )


def reverse_backfill(apps, schema_editor):
    CommercialProjection = apps.get_model("crm", "CommercialProjection")
    CommercialQuotation = apps.get_model("crm", "CommercialQuotation")

    CommercialProjection.objects.update(commercial_line=OTHER)
    CommercialQuotation.objects.update(commercial_line=OTHER)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0005_product_commercial_line"),
        ("crm", "0024_backfill_quotation_financial_analysis"),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialprojection",
            name="commercial_line",
            field=models.CharField(
                choices=[
                    ("school_text", "Texto escolar"),
                    ("reading_plan", "Plan lector"),
                    ("other", "Sin clasificar"),
                ],
                db_index=True,
                default="other",
                max_length=20,
                verbose_name="Línea comercial",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="commercial_line",
            field=models.CharField(
                choices=[
                    ("school_text", "Texto escolar"),
                    ("reading_plan", "Plan lector"),
                    ("other", "Sin clasificar"),
                ],
                db_index=True,
                default="other",
                max_length=20,
                verbose_name="Línea comercial",
            ),
        ),
        migrations.RunPython(
            backfill_commercial_lines,
            reverse_backfill,
        ),
    ]
