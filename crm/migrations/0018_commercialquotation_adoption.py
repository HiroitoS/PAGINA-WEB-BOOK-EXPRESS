# Generated manually for the approved CRM quotation/adoption domain.

import decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0004_alter_cargaexcel_options_alter_product_options_and_more"),
        ("crm", "0017_schoolpopulationdetail"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CommercialQuotation",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Borrador"),
                            ("sent", "Enviada"),
                            ("accepted", "Aceptada"),
                            ("rejected", "Rechazada"),
                            ("superseded", "Reemplazada"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=20,
                        verbose_name="Estado",
                    ),
                ),
                (
                    "school_name_snapshot",
                    models.CharField(
                        max_length=220,
                        verbose_name="Colegio al cotizar",
                    ),
                ),
                (
                    "campaign_name_snapshot",
                    models.CharField(
                        max_length=150,
                        verbose_name="Campaña al cotizar",
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
                    "sent_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Fecha de envío",
                    ),
                ),
                (
                    "accepted_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Fecha de aceptación",
                    ),
                ),
                (
                    "accepted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="accepted_crm_quotations",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Aceptada por",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_crm_quotations",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Creada por",
                    ),
                ),
                (
                    "opportunity",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="quotations",
                        to="crm.opportunity",
                        verbose_name="Oportunidad",
                    ),
                ),
                (
                    "sent_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sent_crm_quotations",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Enviada por",
                    ),
                ),
            ],
            options={
                "verbose_name": "Cotización comercial",
                "verbose_name_plural": "Cotizaciones comerciales",
                "ordering": ["opportunity", "-version"],
            },
        ),
        migrations.CreateModel(
            name="CommercialQuotationItem",
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
                        verbose_name="Producto al cotizar",
                    ),
                ),
                (
                    "provider_name_snapshot",
                    models.CharField(
                        max_length=150,
                        verbose_name="Editorial al cotizar",
                    ),
                ),
                (
                    "level_name_snapshot",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Nivel al cotizar",
                    ),
                ),
                (
                    "grade_name_snapshot",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Grado al cotizar",
                    ),
                ),
                (
                    "area_name_snapshot",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Área al cotizar",
                    ),
                ),
                (
                    "quantity",
                    models.PositiveIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                        ],
                        verbose_name="Cantidad estimada",
                    ),
                ),
                (
                    "pvp",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            ),
                        ],
                        verbose_name="PVP",
                    ),
                ),
                (
                    "supplier_cost",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            ),
                        ],
                        verbose_name="Costo editorial",
                    ),
                ),
                (
                    "school_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            ),
                        ],
                        verbose_name="Precio colegio",
                    ),
                ),
                (
                    "parent_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            ),
                        ],
                        verbose_name="Precio sugerido PPFF",
                    ),
                ),
                (
                    "school_commission",
                    models.DecimalField(
                        decimal_places=2,
                        default=decimal.Decimal("0.00"),
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            ),
                        ],
                        verbose_name="Comisión colegio",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_quotation_items",
                        to="catalog.product",
                        verbose_name="Producto",
                    ),
                ),
                (
                    "quotation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="crm.commercialquotation",
                        verbose_name="Cotización",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ítem de cotización",
                "verbose_name_plural": "Ítems de cotización",
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="Adoption",
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
                        default=1,
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
                        verbose_name="Colegio al confirmar",
                    ),
                ),
                (
                    "campaign_name_snapshot",
                    models.CharField(
                        max_length=150,
                        verbose_name="Campaña al confirmar",
                    ),
                ),
                (
                    "advisor_name_snapshot",
                    models.CharField(
                        blank=True,
                        max_length=180,
                        verbose_name="Asesor al confirmar",
                    ),
                ),
                (
                    "authorized_contact_name_snapshot",
                    models.CharField(
                        max_length=180,
                        verbose_name="Directivo al confirmar",
                    ),
                ),
                (
                    "signed_at",
                    models.DateTimeField(
                        verbose_name="Fecha de firma / aprobación",
                    ),
                ),
                (
                    "confirmed_at",
                    models.DateTimeField(
                        verbose_name="Fecha de confirmación",
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
                    "advisor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="crm_adoptions_as_advisor",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Asesor responsable",
                    ),
                ),
                (
                    "authorized_contact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authorized_adoptions",
                        to="crm.schoolcontact",
                        verbose_name="Directivo que autorizó",
                    ),
                ),
                (
                    "campaign",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="adoptions",
                        to="crm.campaign",
                        verbose_name="Campaña",
                    ),
                ),
                (
                    "confirmed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="confirmed_crm_adoptions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Confirmada por",
                    ),
                ),
                (
                    "opportunity",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="adoptions",
                        to="crm.opportunity",
                        verbose_name="Oportunidad",
                    ),
                ),
                (
                    "quotation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="adoption",
                        to="crm.commercialquotation",
                        verbose_name="Cotización aceptada",
                    ),
                ),
                (
                    "school",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="adoptions",
                        to="crm.school",
                        verbose_name="Colegio",
                    ),
                ),
            ],
            options={
                "verbose_name": "Adopción",
                "verbose_name_plural": "Adopciones",
                "ordering": ["-confirmed_at", "-version"],
            },
        ),
        migrations.CreateModel(
            name="AdoptionItem",
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
                        verbose_name="Producto adoptado",
                    ),
                ),
                (
                    "provider_name_snapshot",
                    models.CharField(
                        max_length=150,
                        verbose_name="Editorial adoptada",
                    ),
                ),
                (
                    "level_name_snapshot",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Nivel",
                    ),
                ),
                (
                    "grade_name_snapshot",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Grado",
                    ),
                ),
                (
                    "area_name_snapshot",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Área",
                    ),
                ),
                (
                    "quantity",
                    models.PositiveIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                        ],
                        verbose_name="Cantidad confirmada",
                    ),
                ),
                (
                    "pvp",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            ),
                        ],
                        verbose_name="PVP confirmado",
                    ),
                ),
                (
                    "supplier_cost",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            ),
                        ],
                        verbose_name="Costo editorial confirmado",
                    ),
                ),
                (
                    "school_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            ),
                        ],
                        verbose_name="Precio colegio confirmado",
                    ),
                ),
                (
                    "parent_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            ),
                        ],
                        verbose_name="Precio PPFF confirmado",
                    ),
                ),
                (
                    "school_commission",
                    models.DecimalField(
                        decimal_places=2,
                        default=decimal.Decimal("0.00"),
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.00")
                            ),
                        ],
                        verbose_name="Comisión colegio confirmada",
                    ),
                ),
                (
                    "reading_month",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(12),
                        ],
                        verbose_name="Mes de lectura",
                    ),
                ),
                (
                    "adoption",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="crm.adoption",
                        verbose_name="Adopción",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crm_adoption_items",
                        to="catalog.product",
                        verbose_name="Producto",
                    ),
                ),
                (
                    "quotation_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="adoption_items",
                        to="crm.commercialquotationitem",
                        verbose_name="Ítem de cotización origen",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ítem de adopción",
                "verbose_name_plural": "Ítems de adopción",
                "ordering": ["id"],
            },
        ),
        migrations.AddConstraint(
            model_name="commercialquotation",
            constraint=models.UniqueConstraint(
                fields=("opportunity", "version"),
                name="crm_quote_unique_opp_version",
            ),
        ),
        migrations.AddIndex(
            model_name="commercialquotation",
            index=models.Index(
                fields=["opportunity", "status"],
                name="crm_quote_opp_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="commercialquotationitem",
            index=models.Index(
                fields=["quotation", "product"],
                name="crm_quote_item_prod_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="adoption",
            constraint=models.UniqueConstraint(
                fields=("opportunity", "version"),
                name="crm_adoption_unique_opp_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="adoption",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_current", True)),
                fields=("opportunity",),
                name="crm_adoption_one_current",
            ),
        ),
        migrations.AddIndex(
            model_name="adoption",
            index=models.Index(
                fields=["school", "campaign", "is_current"],
                name="crm_adopt_school_cmp_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="adoptionitem",
            index=models.Index(
                fields=["adoption", "product"],
                name="crm_adopt_item_prod_idx",
            ),
        ),
    ]
