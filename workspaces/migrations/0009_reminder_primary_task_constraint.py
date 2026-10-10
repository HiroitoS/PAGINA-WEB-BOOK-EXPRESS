from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0008_reminder_source_primary_task"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="reminder",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    source="task",
                    task__isnull=False,
                ),
                fields=("task",),
                name="workspace_unique_primary_task_reminder",
            ),
        ),
    ]
