# Generated manually for the Book Express CRM contact context.

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0014_schooleditorialusage_product_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="schoolcontact",
            name="decision_role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("decision_maker", "Decisor"),
                    ("influencer", "Influenciador"),
                    ("other", "Otro"),
                ],
                default="",
                max_length=30,
                verbose_name="Rol en la decisión",
            ),
        ),
        migrations.AddField(
            model_name="schoolcontact",
            name="relationship_level",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                validators=[
                    MinValueValidator(1),
                    MaxValueValidator(5),
                ],
                verbose_name="Nivel de relacionamiento",
            ),
        ),
    ]
