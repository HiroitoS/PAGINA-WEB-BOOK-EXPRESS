from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0034_school_import_warnings"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="schooleducationalservice",
            options={
                "ordering": [
                    "school__name",
                    "campus__sequence",
                    "level__name",
                ],
                "verbose_name": "Servicio educativo",
                "verbose_name_plural": "Servicios educativos",
            },
        ),
    ]
