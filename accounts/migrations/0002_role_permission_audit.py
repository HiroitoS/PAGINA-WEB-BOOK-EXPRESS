"""Auditoría de permisos por rol administrados desde Seguridad y accesos."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_userprofile"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RolePermissionAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("previous_permissions", models.JSONField(default=list)),
                ("new_permissions", models.JSONField(default=list)),
                ("changed_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("actor", models.ForeignKey(
                    to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="book_express_role_permission_changes",
                )),
                ("group", models.ForeignKey(
                    to="auth.group",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="book_express_permission_changes",
                )),
            ],
            options={"ordering": ["-changed_at", "-pk"]},
        )
    ]
