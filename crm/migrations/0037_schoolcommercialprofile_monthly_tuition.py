from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0036_alter_schoolimportbatch_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="schoolcommercialprofile",
            name="monthly_tuition",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[MinValueValidator(0)],
                verbose_name="Pensión mensual referencial",
            ),
        ),
    ]
