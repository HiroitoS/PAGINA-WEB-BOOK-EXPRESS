from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class CommercialTeam(TimeStampedModel):
    code = models.CharField(
        max_length=40,
        unique=True,
        verbose_name="Código",
    )
    name = models.CharField(
        max_length=150,
        verbose_name="Nombre del equipo",
    )
    description = models.TextField(
        blank=True,
        verbose_name="Descripción",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_teams",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Equipo comercial"
        verbose_name_plural = "Equipos comerciales"
        ordering = ["name"]
        indexes = [
            models.Index(
                fields=["is_active", "name"],
                name="crm_team_active_name_idx",
            ),
        ]

    def __str__(self):
        return self.name


class CommercialTeamMembership(TimeStampedModel):
    class Role(models.TextChoices):
        SUPERVISOR = "supervisor", "Supervisor"
        ADVISOR = "advisor", "Asesor comercial"
        SUPPORT = "support", "Apoyo comercial"

    team = models.ForeignKey(
        CommercialTeam,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="Equipo comercial",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="crm_team_memberships",
        verbose_name="Usuario",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ADVISOR,
        verbose_name="Rol en el equipo",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo",
    )
    joined_on = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de ingreso",
    )
    ended_on = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de salida",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_team_memberships",
        verbose_name="Registrado por",
    )

    class Meta:
        verbose_name = "Miembro de equipo comercial"
        verbose_name_plural = "Miembros de equipos comerciales"
        ordering = ["team__name", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"],
                name="crm_team_unique_user",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(joined_on__isnull=True)
                    | models.Q(ended_on__isnull=True)
                    | models.Q(ended_on__gte=models.F("joined_on"))
                ),
                name="crm_team_valid_dates",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "is_active"],
                name="crm_team_user_active_idx",
            ),
            models.Index(
                fields=["team", "role", "is_active"],
                name="crm_team_role_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.team} ({self.get_role_display()})"
