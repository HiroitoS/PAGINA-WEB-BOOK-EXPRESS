from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0035_alter_schooleducationalservice_options"),
    ]

    operations = [
        migrations.AlterField(
            model_name="schoolimportbatch",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pendiente"),
                    ("validated", "Validado"),
                    ("imported", "Importado"),
                    ("partial", "Importado con pendientes"),
                    ("error", "Revisión pendiente"),
                ],
                default="pending",
                max_length=20,
                verbose_name="Estado",
            ),
        ),
    ]
