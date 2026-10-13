from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0045_backfill_adoption_reading_month"),
    ]

    operations = [
        migrations.AlterField(
            model_name="crmworkitemlink",
            name="event",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="crm_links",
                to="workspaces.calendarevent",
                verbose_name="Evento",
            ),
        ),
        migrations.AlterField(
            model_name="crmworkitemlink",
            name="reminder",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="crm_links",
                to="workspaces.reminder",
                verbose_name="Recordatorio",
            ),
        ),
        migrations.AlterField(
            model_name="crmworkitemlink",
            name="task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.PROTECT,
                related_name="crm_links",
                to="workspaces.task",
                verbose_name="Tarea",
            ),
        ),
    ]
