from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0033_school_campuses_and_internal_codes"),
    ]

    operations = [
        migrations.AddField(
            model_name="schoolimportbatch",
            name="total_warnings",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="schoolimportrow",
            name="warnings",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="Advertencias",
            ),
        ),
        migrations.AlterField(
            model_name="schoolimportrow",
            name="errors",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="Errores que requieren revisión",
            ),
        ),
    ]
}
