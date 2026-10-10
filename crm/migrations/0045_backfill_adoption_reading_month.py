from django.db import migrations


def backfill_adoption_reading_month(apps, schema_editor):
    AdoptionItem = apps.get_model("crm", "AdoptionItem")

    queryset = (
        AdoptionItem.objects
        .filter(reading_month__isnull=True)
        .exclude(quotation_item__reading_month__isnull=True)
        .select_related("quotation_item")
    )

    for adoption_item in queryset.iterator():
        adoption_item.reading_month = (
            adoption_item.quotation_item.reading_month
        )
        adoption_item.save(update_fields=["reading_month"])


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0044_enable_unaccent"),
    ]

    operations = [
        migrations.RunPython(
            backfill_adoption_reading_month,
            migrations.RunPython.noop,
        ),
    ]
