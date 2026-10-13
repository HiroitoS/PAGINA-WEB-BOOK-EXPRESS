from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0040_crmworkitemlink_commercial_action_type"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CRMHistoryEvent",
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
                    "category",
                    models.CharField(
                        choices=[
                            ("school", "Colegio"),
                            ("contact", "Contacto"),
                            ("activity", "Actividad"),
                            ("opportunity", "Oportunidad"),
                            ("projection", "Proyección"),
                            ("quotation", "Cotización"),
                            ("adoption", "Adopción"),
                            ("population", "Población"),
                            ("assignment", "Asignación"),
                            ("evidence", "Evidencia"),
                            ("other", "Otro"),
                        ],
                        db_index=True,
                        max_length=24,
                        verbose_name="Categoría",
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        db_index=True,
                        max_length=64,
                        verbose_name="Tipo de evento",
                    ),
                ),
                (
                    "title",
                    models.CharField(
                        max_length=220,
                        verbose_name="Título",
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
                    "source_type",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=64,
                        verbose_name="Tipo de origen",
                    ),
                ),
                (
                    "source_id",
                    models.PositiveBigIntegerField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="ID de origen",
                    ),
                ),
                (
                    "platform",
                    models.CharField(
                        default="Página Web",
                        max_length=40,
                        verbose_name="Plataforma",
                    ),
                ),
                (
                    "metadata",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        verbose_name="Metadatos",
                    ),
                ),
                (
                    "occurred_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        verbose_name="Fecha del evento",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Fecha de registro",
                    ),
                ),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="crm_history_events",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="history_events",
                        to="crm.schoolcontact",
                        verbose_name="Contacto",
                    ),
                ),
                (
                    "opportunity",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="history_events",
                        to="crm.opportunity",
                        verbose_name="Oportunidad",
                    ),
                ),
                (
                    "school",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="history_events",
                        to="crm.school",
                        verbose_name="Colegio",
                    ),
                ),
            ],
            options={
                "verbose_name": "Evento de historial CRM",
                "verbose_name_plural": "Eventos de historial CRM",
                "ordering": ["-occurred_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="crmhistoryevent",
            index=models.Index(
                fields=["school", "-occurred_at"],
                name="crm_hist_school_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="crmhistoryevent",
            index=models.Index(
                fields=["opportunity", "-occurred_at"],
                name="crm_hist_opp_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="crmhistoryevent",
            index=models.Index(
                fields=["category", "event_type"],
                name="crm_hist_cat_type_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="crmhistoryevent",
            constraint=models.UniqueConstraint(
                fields=("source_type", "source_id", "event_type"),
                name="crm_hist_source_event_uniq",
            ),
        ),
    ]
