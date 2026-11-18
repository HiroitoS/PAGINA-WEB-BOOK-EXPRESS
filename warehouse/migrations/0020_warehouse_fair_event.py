"""B3.2: una feria = un evento con ubicación interna exclusiva.

No crea existencias, no asigna traslados y no representa un establecimiento SUNAT.
"""
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0019_distribution_transport_itinerant_reason"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WarehouseFairEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("reference", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("idempotency_key", models.UUIDField(editable=False, unique=True)),
                ("name", models.CharField(max_length=150)),
                ("venue_name", models.CharField(max_length=180)),
                ("venue_address", models.CharField(max_length=255)),
                ("starts_on", models.DateField()),
                ("ends_on", models.DateField()),
                ("responsible_name", models.CharField(max_length=180)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("created_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="warehouse_fair_events_created",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("location", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="fair_event",
                    to="warehouse.warehouselocation",
                )),
            ],
            options={"ordering": ["-starts_on", "-pk"]},
        ),
        migrations.AddConstraint(
            model_name="warehousefairevent",
            constraint=models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")),
                name="wh_fair_dates_valid",
            ),
        ),
    ]
