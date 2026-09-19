from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel

from .team import CommercialTeam


class School(TimeStampedModel):
    """
    Institución educativa entendida como cliente/prospecto comercial.

    Cada School representa una institución educativa dentro del CRM.
    Sus niveles o servicios educativos dependen directamente del colegio,
    sin una capa intermedia de sedes.

    Los campos modular_code, estimated_students y levels se mantienen
    temporalmente por compatibilidad mientras el frontend y las
    importaciones terminan de migrar al nuevo modelo.
    """

    institution_code = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Código de institución",
    )
    name = models.CharField(
        max_length=220,
        db_index=True,
        verbose_name="Nombre del colegio",
    )

    # LEGACY: retirar cuando frontend/importaciones utilicen
    # SchoolEducationalService.
    modular_code = models.CharField(
        max_length=30,
        blank=True,
        db_index=True,
        verbose_name="Código modular",
    )

    ruc = models.CharField(
        max_length=11,
        blank=True,
        db_index=True,
        verbose_name="RUC",
    )
    phone = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Teléfono",
    )
    whatsapp = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="WhatsApp",
    )
    email = models.EmailField(
        blank=True,
        verbose_name="Correo",
    )

    address = models.CharField(
        max_length=250,
        blank=True,
        verbose_name="Dirección",
    )
    reference = models.CharField(
        max_length=250,
        blank=True,
        verbose_name="Referencia",
    )
    department = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Departamento",
    )
    province = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Provincia",
    )
    district = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Distrito",
    )

    # LEGACY: la población real pasará a SchoolPopulationRecord.
    estimated_students = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Alumnos estimados",
    )

    # LEGACY: los niveles reales se obtendrán de los servicios educativos.
    levels = models.ManyToManyField(
        "catalog.Level",
        blank=True,
        related_name="crm_schools",
        verbose_name="Niveles educativos",
    )

    team = models.ForeignKey(
        CommercialTeam,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schools",
        verbose_name="Equipo comercial",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_owned_schools",
        verbose_name="Asesor responsable",
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Observaciones",
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
        related_name="created_crm_schools",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Colegio"
        verbose_name_plural = "Colegios"
        ordering = ["name"]
        indexes = [
            models.Index(
                fields=["is_active", "name"],
                name="crm_school_active_name_idx",
            ),
            models.Index(
                fields=["owner", "is_active"],
                name="crm_school_owner_active_idx",
            ),
            models.Index(
                fields=["team", "is_active"],
                name="crm_school_team_active_idx",
            ),
            models.Index(
                fields=["department", "province", "district"],
                name="crm_school_location_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["institution_code"],
                condition=Q(institution_code__isnull=False),
                name="crm_school_unique_institution_code",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.institution_code:
            self.institution_code = self.institution_code.strip() or None

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class SchoolEducationalService(TimeStampedModel):
    """
    Servicio o nivel educativo ofrecido directamente por el colegio.

    Aquí vive el código modular porque identifica el servicio educativo
    correspondiente, no necesariamente a toda la institución.
    """

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="educational_services",
        verbose_name="Colegio",
    )
    level = models.ForeignKey(
        "catalog.Level",
        on_delete=models.PROTECT,
        related_name="crm_school_services",
        verbose_name="Nivel educativo",
    )
    modular_code = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Código modular",
    )
    modality = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Modalidad",
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
        related_name="created_crm_school_services",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Servicio educativo"
        verbose_name_plural = "Servicios educativos"
        ordering = ["school__name", "level__name"]
        indexes = [
            models.Index(
                fields=["school", "is_active"],
                name="crm_service_school_active_idx",
            ),
            models.Index(
                fields=["level", "is_active"],
                name="crm_service_level_active_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["modular_code"],
                condition=Q(modular_code__isnull=False),
                name="crm_service_unique_modular_code",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.modular_code:
            self.modular_code = self.modular_code.strip() or None

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.school.name} - "
            f"{self.level.name}"
        )


class SchoolContact(TimeStampedModel):
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="contacts",
        verbose_name="Colegio",
    )
    full_name = models.CharField(
        max_length=180,
        verbose_name="Nombre completo",
    )
    position = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Cargo / función",
    )
    phone = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Teléfono",
    )
    whatsapp = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="WhatsApp",
    )
    email = models.EmailField(
        blank=True,
        verbose_name="Correo",
    )
    is_primary = models.BooleanField(
        default=False,
        verbose_name="Contacto principal",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo",
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Observaciones",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_school_contacts",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Contacto de colegio"
        verbose_name_plural = "Contactos de colegios"
        ordering = ["school__name", "-is_primary", "full_name"]
        indexes = [
            models.Index(
                fields=["school", "is_active"],
                name="crm_contact_school_active_idx",
            ),
            models.Index(
                fields=["school", "is_primary"],
                name="crm_contact_school_main_idx",
            ),
        ]

    def __str__(self):
        return f"{self.full_name} - {self.school.name}"