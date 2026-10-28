"""P-08: catálogo de ubicaciones. No reasigna stock histórico ni inventa saldos."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0008_stock_movement")]

    operations = [
        migrations.CreateModel(
            name="WarehouseLocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("code", models.CharField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("kind", models.CharField(
                    max_length=20,
                    choices=[
                        ("main", "Almacén principal"),
                        ("store", "Tienda"),
                        ("fair", "Feria temporal"),
                        ("consignment", "Consignación"),
                        ("other", "Otro depósito"),
                    ],
                )),
                ("address", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
            ],
            options={
                "ordering": ["name", "pk"],
                "permissions": [
                    ("view_warehouse_locations", "Puede consultar ubicaciones de almacén"),
                    ("manage_warehouse_locations", "Puede gestionar ubicaciones de almacén"),
                ],
            },
        ),
    ]
