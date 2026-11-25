"""Fotos y documentos privados para incidencias de recepción."""
import django.db.models.deletion
import warehouse.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0017_receipt_supervisor_approval"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ReceivingEvidence",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("kind", models.CharField(max_length=15, choices=[
                    ("damaged", "Dañado o deteriorado"),
                    ("incorrect", "Libro incorrecto"),
                    ("shortage", "Faltante frente a la guía"),
                    ("other", "Otra observación"),
                ])),
                ("description", models.CharField(max_length=500)),
                ("file", models.FileField(
                    upload_to=warehouse.models.receiving_evidence_path,
                    storage=warehouse.models.private_receiving_storage,
                )),
                ("original_name", models.CharField(max_length=220)),
                ("created_by", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                    related_name="receiving_evidences_created",
                )),
                ("receipt_line", models.ForeignKey(
                    to="warehouse.goodsreceiptline", on_delete=django.db.models.deletion.PROTECT,
                    related_name="evidences",
                )),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
    ]
