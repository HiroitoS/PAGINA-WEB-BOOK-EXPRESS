from django.db import migrations
from django.utils.text import slugify


def migrate_market_editorials(apps, schema_editor):
    Provider = apps.get_model("catalog", "Provider")
    MarketEditorial = apps.get_model("crm", "MarketEditorial")
    SchoolEditorialUsage = apps.get_model("crm", "SchoolEditorialUsage")

    for provider in Provider.objects.all().iterator():
        name = " ".join((provider.name or "").split())

        base_normalized = slugify(name) or name.casefold()
        base_normalized = base_normalized[:200]

        normalized_name = base_normalized

        existing_collision = MarketEditorial.objects.filter(
            normalized_name=normalized_name
        ).exclude(
            catalog_provider_id=provider.id
        ).exists()

        if existing_collision:
            normalized_name = (
                f"{base_normalized}-{provider.id}"
            )[:220]

        market_editorial, created = MarketEditorial.objects.get_or_create(
            catalog_provider_id=provider.id,
            defaults={
                "name": name,
                "normalized_name": normalized_name,
                "verification_status": "verified",
                "is_active": provider.is_active,
            },
        )

        if not created:
            fields_to_update = []

            if market_editorial.name != name:
                market_editorial.name = name
                fields_to_update.append("name")

            if market_editorial.is_active != provider.is_active:
                market_editorial.is_active = provider.is_active
                fields_to_update.append("is_active")

            if market_editorial.verification_status != "verified":
                market_editorial.verification_status = "verified"
                fields_to_update.append("verification_status")

            if fields_to_update:
                market_editorial.save(update_fields=fields_to_update)

        SchoolEditorialUsage.objects.filter(
            provider_id=provider.id,
            editorial__isnull=True,
        ).update(
            editorial_id=market_editorial.id
        )


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0011_schooleditorialusage_editorial"),
    ]

    operations = [
        migrations.RunPython(
            migrate_market_editorials,
            migrations.RunPython.noop,
        ),
    ]