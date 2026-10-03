from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0026_commercialquotationitem_supplier_discount_percent"),
    ]

    operations = [
        migrations.AddField(
            model_name="adoptionitem",
            name="supplier_discount_percent",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=5,
                null=True,
                validators=[
                    MinValueValidator(Decimal("0.00")),
                    MaxValueValidator(Decimal("100.00")),
                ],
                verbose_name="Descuento editorial confirmado (%)",
            ),
        ),
    ]
