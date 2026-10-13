from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0010_protect_task_history"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskChangeHistory",
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
                    "changes",
                    models.JSONField(
                        default=list,
                        verbose_name="Cambios realizados",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Fecha de modificación",
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="task_metadata_changes",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Modificado por",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="change_history",
                        to="workspaces.task",
                        verbose_name="Tarea",
                    ),
                ),
            ],
            options={
                "verbose_name": "Auditoría de tarea",
                "verbose_name_plural": "Auditorías de tareas",
                "ordering": ["-created_at", "-pk"],
            },
        ),
    ]
