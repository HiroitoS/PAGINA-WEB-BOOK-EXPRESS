from django.db import migrations, models


def backfill_primary_task_reminders(apps, schema_editor):
    Task = apps.get_model("workspaces", "Task")
    Reminder = apps.get_model("workspaces", "Reminder")

    tasks = (
        Task.objects
        .filter(
            reminder_at__isnull=False,
            assigned_to__isnull=False,
        )
        .order_by("id")
    )

    for task in tasks.iterator():
        created_by_id = task.created_by_id or task.assigned_to_id

        Reminder.objects.update_or_create(
            task_id=task.id,
            source="task",
            defaults={
                "created_by_id": created_by_id,
                "user_id": task.assigned_to_id,
                "group_id": task.group_id,
                "event_id": None,
                "title": task.title,
                "message": "",
                "remind_at": task.reminder_at,
                "status": "pending",
                "completed_at": None,
            },
        )


def remove_backfilled_primary_task_reminders(apps, schema_editor):
    Reminder = apps.get_model("workspaces", "Reminder")
    Reminder.objects.filter(source="task").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0007_workspacetasklist_task_task_list"),
    ]

    operations = [
        migrations.AddField(
            model_name="reminder",
            name="source",
            field=models.CharField(
                choices=[
                    ("manual", "Manual"),
                    ("task", "Tarea"),
                ],
                db_index=True,
                default="manual",
                max_length=20,
                verbose_name="Origen",
            ),
        ),
        migrations.RunPython(
            backfill_primary_task_reminders,
            remove_backfilled_primary_task_reminders,
        ),
    ]
