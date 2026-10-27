import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0007_stock_entry_cost"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StockMovement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("kind", models.CharField(choices=[("courtesy", "Cortesía a colegio")], max_length=24)),
                ("quantity_delta", models.IntegerField()),
                ("recipient_name", models.CharField(max_length=200)),
                ("recipient_role", models.CharField(max_length=80)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("unit_cost_snapshot", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("idempotency_key", models.UUIDField(editable=False, unique=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_movements_created", to=settings.AUTH_USER_MODEL)),
                ("school", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_movements", to="crm.school")),
                ("source_entry", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="movements", to="warehouse.stockentry")),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
                "permissions": [
                    ("view_stock_movements", "Puede consultar movimientos de stock"),
                    ("manage_stock_courtesies", "Puede registrar cortesías desde almacén"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity_delta__lt=0),
                name="wh_stock_movement_negative",
            ),
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["source_entry", "created_at"], name="wh_move_entry_date_idx"),
        ),
    ]
