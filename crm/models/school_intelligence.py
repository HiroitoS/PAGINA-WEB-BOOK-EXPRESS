from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel

from .campaign import Campaign
from .school import School, SchoolEducationalService


class InformationSource(models.TextChoices):
    MINEDU = "minedu", "MINEDU"
    IMPORT = "import", "Importación"
    ADVISOR = "advisor", "Asesor comercial"
    MANAGEMENT = "management", "Jefatura comercial"
    MANUAL = "manual", "Registro manual"
    OTHER = "other", "Otro"


class SchoolPopulationRecord(TimeStampedModel):
    """
    Historial de población estudiantil por servicio educativo.

    No sobrescribimos la información anterior: cada nueva verificación
    genera un registro y el último válido queda marcado como actual.
    """

    service = models.ForeignKey(
        SchoolEducationalService,
        on_delete=models.CASCADE,
        related_name="population_records",
        verbose_name="Servicio educativo",
    )
    year = models.PositiveIntegerField(
        db_index=True,
        verbose_name="Año",
    )
    student_count = models.PositiveIntegerField(
        verbose_name="Cantidad de alumnos",
    )
    source = models.CharField(
        max_length=30,
        choices=InformationSource.choices,
        default=InformationSource.MANUAL,
        verbose_name="Fuente",
    )
    source_detail = models.CharField(
        max_length=250,
        blank=True,
        verbose_name="Detalle de la fuente",
    )
    is_current = models.BooleanField(
        default=True,
        verbose_name="Dato vigente",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_crm_school_populations",
        verbose_name="Registrado por",
    )

    class Meta:
        verbose_name = "Población de colegio"
        verbose_name_plural = "Historial de población de colegios"
        ordering = ["-year", "-created_at"]
        indexes = [
            models.Index(
                fields=["service", "year", "is_current"],
                name="crm_population_current_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["service"],
                condition=Q(is_current=True),
                name="crm_population_one_current",
            ),
        ]

    def __str__(self):
        return (
            f"{self.service} - "
            f"{self.year}: {self.student_count}"
        )


class SchoolEditorialUsage(TimeStampedModel):
    """
    Editorial/proveedor que el colegio utiliza o utilizó en un área.

    No representa todavía una adopción Book Express.
    Es inteligencia de mercado del colegio.
    """

    class Status(models.TextChoices):
        CURRENT = "current", "Uso actual"
        PREVIOUS = "previous", "Uso anterior"
        REPORTED = "reported", "Información por confirmar"

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="editorial_usages",
        verbose_name="Colegio",
    )
    year = models.PositiveIntegerField(
        db_index=True,
        verbose_name="Año",
    )
    service = models.ForeignKey(
        SchoolEducationalService,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="editorial_usages",
        verbose_name="Servicio educativo",
    )
    area = models.ForeignKey(
        "catalog.Area",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_school_editorial_usages",
        verbose_name="Área",
    )
    provider = models.ForeignKey(
        "catalog.Provider",
        on_delete=models.PROTECT,
        related_name="crm_school_usages",
        verbose_name="Editorial",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REPORTED,
        verbose_name="Estado de información",
    )
    source = models.CharField(
        max_length=30,
        choices=InformationSource.choices,
        default=InformationSource.MANUAL,
        verbose_name="Fuente",
    )
    observed_on = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de verificación",
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Observaciones",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_crm_editorial_usages",
        verbose_name="Registrado por",
    )

    class Meta:
        verbose_name = "Uso editorial del colegio"
        verbose_name_plural = "Usos editoriales de colegios"
        ordering = [
            "school__name",
            "-year",
            "area__name",
            "provider__name",
        ]
        indexes = [
            models.Index(
                fields=["school", "year"],
                name="crm_usage_school_year_idx",
            ),
            models.Index(
                fields=["provider", "year"],
                name="crm_usage_provider_year_idx",
            ),
            models.Index(
                fields=["status", "year"],
                name="crm_usage_status_year_idx",
            ),
        ]

    def __str__(self):
        area = self.area.name if self.area else "Área no especificada"

        return (
            f"{self.school.name} - "
            f"{self.provider.name} - "
            f"{area} - {self.year}"
        )


class SchoolCommercialProfile(TimeStampedModel):
    """
    Snapshot de inteligencia comercial por colegio y campaña.

    Segmento y prioridad NO significan lo mismo.

    - Segmento: potencial estructural por población.
    - Prioridad: conveniencia comercial basada en señales.
    """

    class Segment(models.TextChoices):
        A = "A", "A"
        B = "B", "B"
        C = "C", "C"
        OUT = "OUT", "Fuera del objetivo base"

    class Priority(models.TextChoices):
        HIGH = "high", "Alta"
        MEDIUM = "medium", "Media"
        LOW = "low", "Baja"
        UNDEFINED = "undefined", "Sin evaluar"

    class TextbookUsage(models.TextChoices):
        UNKNOWN = "unknown", "Sin información"
        CORE = "core", "Utiliza textos principales"
        COMPLEMENTARY = "complementary", "Solo áreas complementarias"
        NONE = "none", "No utiliza textos escolares"

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="commercial_profiles",
        verbose_name="Colegio",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.PROTECT,
        related_name="school_commercial_profiles",
        verbose_name="Campaña",
    )

    population_total = models.PositiveIntegerField(
        default=0,
        verbose_name="Población total considerada",
    )
    segment = models.CharField(
        max_length=10,
        choices=Segment.choices,
        default=Segment.OUT,
        verbose_name="Segmento",
    )

    textbook_usage = models.CharField(
        max_length=30,
        choices=TextbookUsage.choices,
        default=TextbookUsage.UNKNOWN,
        verbose_name="Uso de textos",
    )

    priority_score = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Puntaje de prioridad",
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.UNDEFINED,
        verbose_name="Prioridad comercial",
    )

    score_reasons = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Factores del puntaje",
    )
    score_version = models.CharField(
        max_length=30,
        default="v1",
        verbose_name="Versión del cálculo",
    )
    scored_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Último cálculo",
    )

    class Meta:
        verbose_name = "Perfil comercial de colegio"
        verbose_name_plural = "Perfiles comerciales de colegios"
        ordering = ["-campaign__year", "school__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "campaign"],
                name="crm_unique_school_campaign_profile",
            ),
        ]
        indexes = [
            models.Index(
                fields=["campaign", "segment"],
                name="crm_profile_segment_idx",
            ),
            models.Index(
                fields=["campaign", "priority"],
                name="crm_profile_priority_idx",
            ),
        ]

    @staticmethod
    def segment_for_population(population_total):
        if population_total >= 500:
            return SchoolCommercialProfile.Segment.A
        if population_total >= 250:
            return SchoolCommercialProfile.Segment.B
        if population_total >= 101:
            return SchoolCommercialProfile.Segment.C

        return SchoolCommercialProfile.Segment.OUT

    def save(self, *args, **kwargs):
        self.segment = self.segment_for_population(self.population_total)
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.school.name} - "
            f"{self.campaign.name}"
        )