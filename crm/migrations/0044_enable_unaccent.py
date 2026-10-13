from django.db import migrations


def enable_unaccent_when_available(apps, schema_editor):
    """
    Keep this migration usable on shared PostgreSQL hosting where the
    unaccent extension is not offered. CRM queries do not require it.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = %s",
            ["unaccent"],
        )
        available = cursor.fetchone() is not None

    if available:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0043_commercialactivity_location"),
    ]

    operations = [
        migrations.RunPython(
            enable_unaccent_when_available,
            migrations.RunPython.noop,
        ),
    ]
