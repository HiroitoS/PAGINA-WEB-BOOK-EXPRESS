from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0022_commercialactivity_activity_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialquotationitem",
            name="product_code_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=100,
                verbose_name="Código de producto al cotizar",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="product_type_name_snapshot",
            field=models.CharField(
                blank=True,
                default="",
                max_length=100,
                verbose_name="Tipo de producto al cotizar",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="commercial_line",
            field=models.CharField(
                choices=[
                    ("school_text", "Texto escolar"),
                    ("reading_plan", "Plan lector"),
                    ("other", "Otra línea"),
                ],
                default="other",
                max_length=20,
                verbose_name="Línea comercial",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="reading_month",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                validators=[
                    MinValueValidator(1),
                    MaxValueValidator(12),
                ],
                verbose_name="Mes de lectura",
            ),
        ),
        migrations.AlterField(
            model_name="commercialquotationitem",
            name="school_commission",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
                validators=[MinValueValidator(Decimal("0.00"))],
                verbose_name="Comisión unitaria autorizada",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="commission_mode",
            field=models.CharField(
                choices=[
                    ("per_unit", "Por unidad"),
                    ("total", "Monto total"),
                ],
                default="per_unit",
                max_length=20,
                verbose_name="Modalidad de comisión",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="commission_input_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
                validators=[MinValueValidator(Decimal("0.00"))],
                verbose_name="Comisión ingresada",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="commercial_margin_unit",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
                verbose_name="Margen comercial unitario",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="commercial_margin_total",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=16,
                verbose_name="Margen comercial proyectado",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="commercial_margin_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=7,
                verbose_name="Margen comercial (%)",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="profitability_band",
            field=models.CharField(
                choices=[
                    ("green", "Verde"),
                    ("amber", "Ámbar"),
                    ("red", "Rojo"),
                    ("loss", "Pérdida"),
                    ("unclassified", "Sin clasificar"),
                ],
                default="unclassified",
                max_length=20,
                verbose_name="Semáforo de rentabilidad",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="max_green_discount_percent",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=7,
                null=True,
                verbose_name="Descuento máximo para mantener verde (%)",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="green_discount_headroom_points",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=7,
                null=True,
                verbose_name="Margen de negociación hasta verde (puntos)",
            ),
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE crm_commercialquotationitem "
                "SET commission_input_amount = school_commission, "
                "commission_mode = 'per_unit'"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
