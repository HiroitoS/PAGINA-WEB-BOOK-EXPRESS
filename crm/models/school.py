from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel

from .team import CommercialTeam


class School(TimeStampedModel):
    """
    Institución educativa entendida como cliente/prospecto comercial.

    Cada School representa una institución educativa dentro del CRM.
    Una institución puede operar en una o varias sedes físicas. Los
    servicios educativos conservan además la relación directa al colegio
    por compatibilidad, pero su ubicación vigente se registra en campus.

    Los campos de dirección, modular_code, estimated_students y levels se mantienen
    temporalmente por compatibilidad mientras el frontend y las
    importaciones terminan de migrar al nuevo modelo.
    """

    book_express_code = models.CharField(
        max_length=24,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        verbose_name="Código Book Express",
    )
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
    dependency = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Dependencia",
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

        if not self.book_express_code and self.pk:
            code = f"BE-IE-{self.pk:06d}"
            type(self).objects.filter(
                pk=self.pk,
                book_express_code__isnull=True,
            ).update(book_express_code=code)
            self.book_express_code = code

    def __str__(self):
        return self.name


class SchoolCampus(TimeStampedModel):
    """
    Sede física de una institución educativa.

    La institución conserva la relación comercial, mientras cada sede
    preserva su ubicación y permite separar población/servicios cuando
    un colegio opera en más de un local.
    """

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="campuses",
        verbose_name="Colegio",
    )
    sequence = models.PositiveSmallIntegerField(
        default=1,
        verbose_name="Número de sede",
    )
    name = models.CharField(
        max_length=150,
        default="Sede principal",
        verbose_name="Nombre de la sede",
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
        db_index=True,
        verbose_name="Departamento",
    )
    province = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name="Provincia",
    )
    district = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name="Distrito",
    )
    is_main = models.BooleanField(
        default=False,
        verbose_name="Sede principal",
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
        related_name="created_crm_school_campuses",
        verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Sede de colegio"
        verbose_name_plural = "Sedes de colegios"
        ordering = ["school__name", "sequence", "id"]
        indexes = [
            models.Index(
                fields=["school", "is_active"],
                name="crm_campus_school_active_idx",
            ),
            models.Index(
                fields=["department", "province", "district"],
                name="crm_campus_location_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "sequence"],
                name="crm_campus_unique_school_sequence",
            ),
            models.UniqueConstraint(
                fields=["school"],
                condition=Q(is_main=True),
                name="crm_campus_one_main_per_school",
            ),
        ]

    @property
    def book_express_code(self):
        school_code = self.school.book_express_code or "BE-IE"
        return f"{school_code}-S{self.sequence:02d}"

    def __str__(self):
        return f"{self.school.name} - {self.name}"


class SchoolEducationalService(TimeStampedModel):
    """
    Servicio o nivel educativo ofrecido por una sede del colegio.

    Aquí vive el código modular porque identifica el servicio educativo.
    La relación school se conserva para consultas comerciales y
    compatibilidad; campus permite diferenciar sedes físicas.
    """

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="educational_services",
        verbose_name="Colegio",
    )
    campus = models.ForeignKey(
        SchoolCampus,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="educational_services",
        verbose_name="Sede",
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
        ordering = [
            "school__name",
            "campus__sequence",
            "level__name",
        ]
        indexes = [
            models.Index(
                fields=["school", "is_active"],
                name="crm_service_school_active_idx",
            ),
            models.Index(
                fields=["campus", "is_active"],
                name="crm_service_campus_active_idx",
            ),
            models.Index(
                fields=["level", "is_active"],
                name="crm_service_level_active_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "level"],
                condition=Q(campus__isnull=True),
                name="crm_service_unique_school_level_legacy",
            ),
            models.UniqueConstraint(
                fields=["campus", "level"],
                condition=Q(campus__isnull=False),
                name="crm_service_unique_campus_level",
            ),
            models.UniqueConstraint(
                fields=["modular_code"],
                condition=Q(modular_code__isnull=False),
                name="crm_service_unique_modular_code",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.campus_id
            and self.school_id
            and self.campus.school_id != self.school_id
        ):
            raise ValidationError(
                {"campus": "La sede seleccionada no pertenece al colegio."}
            )

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
    class DecisionRole(models.TextChoices):
        DECISION_MAKER = "decision_maker", "Decisor"
        INFLUENCER = "influencer", "Influenciador"
        OTHER = "other", "Otro"

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="contacts",
        verbose_name="Colegio",
    )
    first_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Nombre",
    )
    last_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Apellido",
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
    decision_role = models.CharField(
        max_length=30,
        choices=DecisionRole.choices,
        blank=True,
        default="",
        verbose_name="Rol en la decisión",
    )
    relationship_level = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ],
        verbose_name="Nivel de relacionamiento",
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

    def save(self, *args, **kwargs):
        first_name = " ".join((self.first_name or "").split())
        last_name = " ".join((self.last_name or "").split())

        self.first_name = first_name
        self.last_name = last_name
        self.position = " ".join((self.position or "").split())
        self.phone = (self.phone or "").strip()
        self.whatsapp = (self.whatsapp or "").strip()
        self.email = (self.email or "").strip().lower()

        if first_name or last_name:
            self.full_name = " ".join(
                value for value in [first_name, last_name] if value
            )
        else:
            self.full_name = " ".join((self.full_name or "").split())

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} - {self.school.name}"