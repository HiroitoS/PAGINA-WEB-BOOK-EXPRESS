# Generated manually for CRM commercial projections.

import decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0018_commercialquotation_adoption"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CommercialProjection",
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
                    "version",
                    models.PositiveSmallIntegerField(
                        verbose_name="Versión",
                    ),
                ),
                (
                    "is_current",
                    models.BooleanField(
                        db_index=True,
                        default=True,
                        verbose_name="Versión vigente",
                    ),
                ),
                (
                    "school_name_snapshot",
                    models.CharField(
                        max_length=220,
                        verbose_name="Colegio al proyectar",
                    ),
                ),
                (
                    "campaign_name_snapshot",
                    models.CharField(
                        max_length=150,
                        verbose_name="Campaña al proyectar",
                    ),
                ),
                (
                    "campaign_year_snapshot",
                    models.PositiveSmallIntegerField(
                        verbose_name="Año de campaña",
                    ),
                ),
                (
                    "notes",
                    models.TextField(
                        blank=True,
                        verbose_name="Observaciones",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_crm_projections",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Creada por",
                    ),
                ),
                (
                    "opportunity",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="projections",
                        to="crm.opportunity",
                        verbose_name="Oportunidad",
                    ),
                ),
            ],
            options={
                "verbose_name": "Proyección comercial",
                "verbose_name_plural": "Proyecciones comerciales",
                "ordering": ["opportunity", "-version"],
            },
        ),
        migrations.CreateModel(
            name="CommercialProjectionGrade",
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
                    "level_name_snapshot",
                    models.CharField(
                        max_length=100,
                        verbose_name="Nivel al proyectar",
                    ),
                ),
                (
                    "grade_name_snapshot",
                    models.CharField(
                        max_length=100,
                        verbose_name="Grado al proyectar",
                    ),
                ),
                (
                    "section_count",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(1)
                        ],
                        verbose_name="Número de secciones",
                    ),
                ),
                (
                    "student_count",
                    models.PositiveIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1)
                        ],
                        verbose_name="Alumnos proyectados",
                    ),
                ),
                (
                    "grade",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_projection_grades",
                        to="catalog.grade",
                        verbose_name="Grado",
                    ),
                ),
                (
                    "projection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grades",
                        to="crm.commercialprojection",
                        verbose_name="Proyección",
                    ),
                ),
                (
                    "service",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="projection_grades",
                        to="crm.schooleducationalservice",
                        verbose_name="Servicio educativo",
                    ),
                ),
            ],
            options={
                "verbose_name": "Grado de proyección",
                "verbose_name_plural": "Grados de proyección",
                "ordering": [
                    "service__level__name",
                    "grade__order",
                    "grade__name",
                ],
            },
        ),
        migrations.CreateModel(
            name="CommercialProjectionItem",
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
                    "product_name_snapshot",
                    models.CharField(
                        max_length=250,
                        verbose_name="Producto al proyectar",
                    ),
                ),
                (
                    "provider_name_snapshot",
                    models.CharField(
                        max_length=150,
                        verbose_name="Editorial al proyectar",
                    ),
                ),
                (
                    "level_name_snapshot",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Nivel del producto",
                    ),
                ),
                (
                    "grade_name_snapshot",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Grado del producto",
                    ),
                ),
                (
                    "area_name_snapshot",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Área del producto",
                    ),
                ),
                (
                    "quantity",
                    models.PositiveIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1)
                        ],
                        verbose_name="Cantidad proyectada",
                    ),
                ),
                (
                    "unit_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            )
                        ],
                        verbose_name="Precio unitario proyectado",
                    ),
                ),
                (
                    "price_year_snapshot",
                    models.PositiveSmallIntegerField(
                        verbose_name="Año del precio",
                    ),
                ),
                (
                    "price_campaign_snapshot",
                    models.CharField(
                        max_length=100,
                        verbose_name="Campaña del precio",
                    ),
                ),
                (
                    "grade_line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="crm.commercialprojectiongrade",
                        verbose_name="Grado proyectado",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_projection_items",
                        to="catalog.product",
                        verbose_name="Producto",
                    ),
                ),
                (
                    "projection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="crm.commercialprojection",
                        verbose_name="Proyección",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ítem de proyección",
                "verbose_name_plural": "Ítems de proyección",
                "ordering": ["id"],
            },
        ),
        migrations.AddConstraint(
            model_name="commercialprojection",
            constraint=models.UniqueConstraint(
                fields=("opportunity", "version"),
                name="crm_proj_unique_opp_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="commercialprojection",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_current", True)),
                fields=("opportunity",),
                name="crm_proj_one_current",
            ),
        ),
        migrations.AddIndex(
            model_name="commercialprojection",
            index=models.Index(
                fields=["opportunity", "is_current"],
                name="crm_proj_opp_current_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="commercialprojectiongrade",
            constraint=models.UniqueConstraint(
                fields=("projection", "service", "grade"),
                name="crm_proj_grade_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="commercialprojectiongrade",
            index=models.Index(
                fields=["projection", "service"],
                name="crm_proj_grade_service_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="commercialprojectionitem",
            constraint=models.UniqueConstraint(
                fields=("projection", "grade_line", "product"),
                name="crm_proj_item_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="commercialprojectionitem",
            index=models.Index(
                fields=["projection", "product"],
                name="crm_proj_item_product_idx",
            ),
        ),
    ]
