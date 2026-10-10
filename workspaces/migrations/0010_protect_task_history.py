from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0009_reminder_primary_task_constraint"),
    ]

    operations = [
        migrations.AlterField(
            model_name="taskcomment",
            name="task",
            field=models.ForeignKey(
                on_delete=models.PROTECT,
                related_name="comments",
                to="workspaces.task",
                verbose_name="Tarea",
            ),
        ),
        migrations.AlterField(
            model_name="taskstatushistory",
            name="task",
            field=models.ForeignKey(
                on_delete=models.PROTECT,
                related_name="status_history",
                to="workspaces.task",
                verbose_name="Tarea",
            ),
        ),
    ]
