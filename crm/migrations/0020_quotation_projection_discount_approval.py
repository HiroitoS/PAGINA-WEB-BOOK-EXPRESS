# Generated manually for CRM quotation traceability and discount approval.

import decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0019_commercialprojection"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialquotation",
            name="source_projection",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotations",
                to="crm.commercialprojection",
                verbose_name="Proyección de origen",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="requires_discount_approval",
            field=models.BooleanField(
                default=False,
                verbose_name="Requiere aprobación de descuento",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="discount_approval_status",
            field=models.CharField(
                choices=[
                    ("not_required", "No requerida"),
                    ("pending", "Pendiente"),
                    ("approved", "Aprobada"),
                ],
                db_index=True,
                default="not_required",
                max_length=20,
                verbose_name="Estado de aprobación de descuento",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="discount_approved_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Fecha de aprobación de descuento",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="discount_approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="approved_crm_quotation_discounts",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Descuento aprobado por",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="discount_approval_note",
            field=models.TextField(
                blank=True,
                verbose_name="Observación de aprobación",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="school_discount_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=decimal.Decimal("0.00"),
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(
                        decimal.Decimal("0.00")
                    ),
                ],
                verbose_name="Descuento colegio (%)",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="price_year_snapshot",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                verbose_name="Año del precio usado",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="price_campaign_snapshot",
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name="Campaña del precio usado",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotationitem",
            name="uses_reference_price",
            field=models.BooleanField(
                default=False,
                verbose_name="Usa precio referencial anterior",
            ),
        ),
    ]
