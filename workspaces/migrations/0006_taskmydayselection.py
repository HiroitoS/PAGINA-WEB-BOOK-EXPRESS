# Generated manually for Book Express ToDo T2

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0005_alter_calendarevent_event_type"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskMyDaySelection",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Fecha de creación",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Fecha de actualización",
                    ),
                ),
                (
                    "selected_date",
                    models.DateField(
                        db_index=True,
                        default=django.utils.timezone.localdate,
                        verbose_name="Día seleccionado",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="my_day_selections",
                        to="workspaces.task",
                        verbose_name="Tarea",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="task_my_day_selections",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
            ],
            options={
                "verbose_name": "Selección de Mi día",
                "verbose_name_plural": "Selecciones de Mi día",
                "ordering": ["-selected_date", "-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="taskmydayselection",
            constraint=models.UniqueConstraint(
                fields=("task", "user"),
                name="workspace_unique_task_my_day_user",
            ),
        ),
    ]
