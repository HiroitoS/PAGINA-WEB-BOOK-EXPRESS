from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0038_schoolcommercialprofile_commercial_affinity"),
    ]

    operations = [
        migrations.AddField(
            model_name="schoolcontact",
            name="first_name",
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name="Nombre",
            ),
        ),
        migrations.AddField(
            model_name="schoolcontact",
            name="last_name",
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name="Apellido",
            ),
        ),
    ]
