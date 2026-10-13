# Generated manually for CRM activity evidence support.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import crm.models.activity_evidence


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0041_crmhistoryevent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CommercialActivityEvidence",
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
                    "evidence_type",
                    models.CharField(
                        choices=[
                            ("photo", "Foto"),
                            ("document", "Documento"),
                        ],
                        max_length=20,
                        verbose_name="Tipo de evidencia",
                    ),
                ),
                (
                    "file",
                    models.FileField(
                        max_length=500,
                        upload_to=crm.models.activity_evidence.activity_evidence_upload_to,
                        verbose_name="Archivo",
                    ),
                ),
                (
                    "original_name",
                    models.CharField(
                        max_length=255,
                        verbose_name="Nombre original",
                    ),
                ),
                (
                    "mime_type",
                    models.CharField(
                        blank=True,
                        max_length=120,
                        verbose_name="Tipo MIME",
                    ),
                ),
                (
                    "size_bytes",
                    models.PositiveBigIntegerField(
                        default=0,
                        verbose_name="Tamaño en bytes",
                    ),
                ),
                (
                    "note",
                    models.CharField(
                        blank=True,
                        max_length=240,
                        verbose_name="Nota",
                    ),
                ),
                (
                    "latitude",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=9,
                        null=True,
                        verbose_name="Latitud",
                    ),
                ),
                (
                    "longitude",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=9,
                        null=True,
                        verbose_name="Longitud",
                    ),
                ),
                (
                    "accuracy_m",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=8,
                        null=True,
                        verbose_name="Precisión en metros",
                    ),
                ),
                (
                    "captured_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Fecha de captura",
                    ),
                ),
                (
                    "activity",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="evidences",
                        to="crm.commercialactivity",
                        verbose_name="Actividad comercial",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_crm_activity_evidences",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Subido por",
                    ),
                ),
            ],
            options={
                "verbose_name": "Evidencia de actividad comercial",
                "verbose_name_plural": "Evidencias de actividades comerciales",
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="commercialactivityevidence",
            index=models.Index(
                fields=["activity", "created_at"],
                name="crm_evid_activity_date_idx",
            ),
        ),
    ]
