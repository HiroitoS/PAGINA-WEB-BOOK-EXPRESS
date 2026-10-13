# Generated for Book Express CRM quotation negotiation reopening.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0020_quotation_projection_discount_approval"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialquotation",
            name="reopen_reason",
            field=models.TextField(
                blank=True,
                verbose_name="Motivo de reapertura",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="reopened_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Fecha de reapertura de negociación",
            ),
        ),
        migrations.AddField(
            model_name="commercialquotation",
            name="reopened_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reopened_crm_quotations",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Negociación reabierta por",
            ),
        ),
    ]
