from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="is_resolved",
            field=models.BooleanField(
                db_index=True,
                default=False,
                verbose_name="Resuelta",
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="resolved_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Fecha de resolución",
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["recipient", "is_resolved", "-created_at"],
                name="notif_rec_resolved_created_idx",
            ),
        ),
    ]
