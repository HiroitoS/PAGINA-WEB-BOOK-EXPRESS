from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse", "0003_recepcion_conciliacion"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ReceivingIncident",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(choices=[("shortage", "Faltante frente a guía"), ("nonconforming", "No conforme")], max_length=20)),
                ("quantity", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("status", models.CharField(choices=[("open", "Pendiente"), ("resolved", "Resuelta")], default="open", max_length=12)),
                ("detected_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="receiving_incidents_detected", to=settings.AUTH_USER_MODEL)),
                ("receipt_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="incidents", to="warehouse.goodsreceiptline")),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.AddConstraint(model_name="receivingincident", constraint=models.UniqueConstraint(fields=("receipt_line", "kind"), name="wh_incident_line_kind_unique")),
        migrations.AddConstraint(model_name="receivingincident", constraint=models.CheckConstraint(condition=models.Q(quantity__gte=1), name="wh_incident_positive")),
    ]
