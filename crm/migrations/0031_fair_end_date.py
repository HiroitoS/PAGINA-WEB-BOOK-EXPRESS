from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0030_sale_mode_and_adoption_schedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialquotation",
            name="service_end_date",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="Fecha de fin de feria",
            ),
        ),
        migrations.AddField(
            model_name="adoption",
            name="service_end_date",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="Fecha de fin de feria",
            ),
        ),
    ]
