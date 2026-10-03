from django.db import migrations, models


def backfill_internal_codes(apps, schema_editor):
    CommercialQuotation = apps.get_model(
        "crm",
        "CommercialQuotation",
    )

    quotations = (
        CommercialQuotation.objects
        .select_related("opportunity__campaign")
        .order_by("pk")
    )

    for quotation in quotations:
        year = quotation.opportunity.campaign.year
        code = (
            f"BE-COT-{year}-"
            f"{quotation.pk:06d}-V{quotation.version:02d}"
        )
        CommercialQuotation.objects.filter(pk=quotation.pk).update(
            internal_code=code
        )


def clear_internal_codes(apps, schema_editor):
    CommercialQuotation = apps.get_model(
        "crm",
        "CommercialQuotation",
    )
    CommercialQuotation.objects.all().update(internal_code=None)


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0028_quotation_party_snapshots"),
    ]

    operations = [
        migrations.AddField(
            model_name="commercialquotation",
            name="internal_code",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=40,
                null=True,
                unique=True,
                verbose_name="Código interno",
            ),
        ),
        migrations.RunPython(
            backfill_internal_codes,
            clear_internal_codes,
        ),
    ]
