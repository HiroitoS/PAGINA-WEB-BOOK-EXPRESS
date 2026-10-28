"""P-08.1b: ubicación inicial auditable por lote.

No asigna automáticamente existencias históricas. Las entradas anteriores
quedan sin ubicación hasta conciliación física expresa.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0009_warehouse_location"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StockEntryLocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("origin", models.CharField(max_length=20, choices=[
                    ("receipt", "Recepción con ubicación principal"),
                    ("reconciliation", "Conciliación física inicial"),
                ])),
                ("available_at_assignment", models.PositiveIntegerField(default=0)),
                ("observed_at_assignment", models.PositiveIntegerField(default=0)),
                ("notes", models.CharField(max_length=500, blank=True)),
                ("assigned_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="stock_locations_assigned",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("location", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="initial_stock_entries",
                    to="warehouse.warehouselocation",
                )),
                ("stock_entry", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="initial_location",
                    to="warehouse.stockentry",
                )),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
    ]
