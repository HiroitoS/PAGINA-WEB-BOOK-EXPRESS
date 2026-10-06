from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0042_commercialactivityevidence"),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialactivity",
            name="latitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
                verbose_name="Latitud registrada",
            ),
        ),
        migrations.AddField(
            model_name="commercialactivity",
            name="longitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
                verbose_name="Longitud registrada",
            ),
        ),
        migrations.AddField(
            model_name="commercialactivity",
            name="location_accuracy_m",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=8,
                null=True,
                verbose_name="Precisión de ubicación (m)",
            ),
        ),
        migrations.AddField(
            model_name="commercialactivity",
            name="location_captured_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Fecha de captura de ubicación",
            ),
        ),
    ]
