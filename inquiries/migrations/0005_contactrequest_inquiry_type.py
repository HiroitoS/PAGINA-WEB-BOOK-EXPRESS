from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inquiries", "0004_alter_contactrequest_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="contactrequest",
            name="inquiry_type",
            field=models.CharField(
                choices=[
                    ("product", "Libro o material educativo"),
                    ("school", "Consulta para colegio"),
                    ("reading_plan", "Plan lector"),
                    ("catalog", "Editoriales y catálogo"),
                    ("training", "Capacitación docente"),
                    ("other", "Otra consulta"),
                ],
                db_index=True,
                default="other",
                max_length=30,
                verbose_name="Tipo de consulta",
            ),
        ),
    ]
