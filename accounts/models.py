from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="book_express_profile",
        verbose_name="Usuario",
    )
    phone = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Celular",
    )
    whatsapp = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="WhatsApp",
    )

    class Meta:
        verbose_name = "Perfil de usuario"
        verbose_name_plural = "Perfiles de usuario"

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class RolePermissionAudit(models.Model):
    """Auditoría de cambios a permisos base de cada rol administrativo."""

    group = models.ForeignKey(
        "auth.Group", on_delete=models.PROTECT, related_name="book_express_permission_changes",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="book_express_role_permission_changes",
    )
    previous_permissions = models.JSONField(default=list)
    new_permissions = models.JSONField(default=list)
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-changed_at", "-pk"]
