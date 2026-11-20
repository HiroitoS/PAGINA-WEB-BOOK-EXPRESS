"""B5.1: incidencias auditables al confirmar recepción en destino."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0021_distribution_dispatch_internal"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DistributionArrivalIncident",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Fecha de actualización")),
                ("status", models.CharField(
                    max_length=10, default="open", db_index=True,
                    choices=[
                        ("open", "Pendiente de revisión"),
                        ("resolved", "Recuento conforme supervisado"),
                    ],
                )),
                ("receiver_name", models.CharField(max_length=180)),
                ("observations", models.CharField(max_length=1000)),
                ("counts_snapshot", models.JSONField(default=list)),
                ("resolution_note", models.CharField(max_length=1000, blank=True)),
                ("recount_snapshot", models.JSONField(default=list)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("dispatch", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="arrival_incidents",
                    to="warehouse.distributiondispatch",
                )),
                ("reported_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="warehouse_arrival_incidents_reported",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("resolved_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    null=True, blank=True,
                    related_name="warehouse_arrival_incidents_resolved",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.AddConstraint(
            model_name="distributionarrivalincident",
            constraint=models.UniqueConstraint(
                fields=["dispatch"],
                condition=models.Q(status="open"),
                name="wh_one_open_arrival_incident",
            ),
        ),
    ]
