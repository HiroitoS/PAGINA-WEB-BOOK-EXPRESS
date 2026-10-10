from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0037_schoolcommercialprofile_monthly_tuition"),
    ]

    operations = [
        migrations.AddField(
            model_name="schoolcommercialprofile",
            name="commercial_affinity",
            field=models.CharField(
                choices=[
                    ("unknown", "Sin evaluar"),
                    ("pedagogical", "Pedagógica"),
                    ("mixed", "Mixta"),
                    ("commercial", "Comercial"),
                ],
                default="unknown",
                max_length=20,
                verbose_name="Afinidad pedagógica/comercial",
            ),
        ),
    ]
