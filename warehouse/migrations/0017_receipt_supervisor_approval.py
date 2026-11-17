"""Recepción: almacenero registra, jefatura aprueba antes de ingreso a inventario."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0016_distribution_preparation_transport_draft")]

    operations = [
        migrations.AlterField(
            model_name="goodsreceipt", name="status",
            field=models.CharField(
                max_length=12, default="draft", db_index=True,
                choices=[
                    ("draft", "Borrador"),
                    ("submitted", "Pendiente de aprobación"),
                    ("validated", "Validada"),
                    ("cancelled", "Anulada"),
                ],
            ),
        ),
    ]
