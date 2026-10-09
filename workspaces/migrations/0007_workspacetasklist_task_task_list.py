# Generated manually for Book Express ToDo T3

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0006_taskmydayselection"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkspaceTaskList",
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
                    "name",
                    models.CharField(
                        max_length=150,
                        verbose_name="Nombre de la lista",
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        blank=True,
                        verbose_name="Descripción",
                    ),
                ),
                (
                    "color",
                    models.CharField(
                        blank=True,
                        default="#dc2626",
                        max_length=30,
                        verbose_name="Color",
                    ),
                ),
                (
                    "position",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Orden",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        verbose_name="Activa",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_workspace_task_lists",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Creado por",
                    ),
                ),
                (
                    "workspace_group",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="task_lists",
                        to="workspaces.workspacegroup",
                        verbose_name="Equipo de trabajo",
                    ),
                ),
            ],
            options={
                "verbose_name": "Lista de tareas",
                "verbose_name_plural": "Listas de tareas",
                "ordering": ["position", "name", "id"],
            },
        ),
        migrations.AddField(
            model_name="task",
            name="task_list",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tasks",
                to="workspaces.workspacetasklist",
                verbose_name="Lista de tareas",
            ),
        ),
    ]
