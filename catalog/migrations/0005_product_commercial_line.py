from django.db import migrations, models
from django.utils.text import slugify


SCHOOL_TEXT = "school_text"
READING_PLAN = "reading_plan"
OTHER = "other"


def _norm(value):
    return slugify(str(value or "")).lower()


def _infer(product):
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
            "pack",
        )
    ):
        return SCHOOL_TEXT

    return OTHER


def backfill_commercial_line(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")

    products = Product.objects.select_related(
        "product_type",
        "area",
        "series",
    )

    for product in products.iterator():
        Product.objects.filter(pk=product.pk).update(
            commercial_line=_infer(product),
        )


def reverse_backfill(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    Product.objects.update(commercial_line=OTHER)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0004_alter_cargaexcel_options_alter_product_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
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
            backfill_commercial_line,
            reverse_backfill,
        ),
    ]
