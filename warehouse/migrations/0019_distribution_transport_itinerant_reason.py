"""Añadir motivo de referencia para emisor itinerante al borrador logístico.

La opción no asigna automáticamente el código fiscal ni emite una GRE.
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0018_receiving_evidence"),
    ]

    operations = [
        migrations.AlterField(
            model_name="distributiontransportdraft",
            name="transfer_reason",
            field=models.CharField(
                blank=True,
                max_length=30,
                choices=[
                    ("consignment", "Consignación"),
                    ("company_transfer", "Entre establecimientos"),
                    ("itinerant", "Traslado por emisor itinerante"),
                    ("sale", "Venta"),
                    ("other", "Otro motivo (verificar)"),
                ],
            ),
        ),
    ]
