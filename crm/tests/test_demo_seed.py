"""La demostración se mantiene aislada de las instituciones importadas."""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.models import Grade, Level, Product, ProductPrice, Provider
from crm.models import (
    Campaign, CommercialProjection, CommercialQuotation,
    Opportunity, Pipeline, PipelineStage, School,
)


class DemoSeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_superuser(
            username="demoerp-admin", email="demoerp@example.test", password="test",
        )
        cls.school = School.objects.create(
            name="Institución del padrón", created_by=cls.actor,
        )
        cls.level = Level.objects.create(name="Primaria")
        cls.grade = Grade.objects.create(name="4to Primaria", order=4)
        cls.provider = Provider.objects.create(name="Editorial del catálogo")
        cls.product = Product.objects.create(
            name="Matemática del catálogo", code="DEMO-MAT4",
            provider=cls.provider, level=cls.level, grade=cls.grade,
            commercial_line=Product.CommercialLine.SCHOOL_TEXT,
        )
        ProductPrice.objects.create(
            product=cls.product, year=2027, campaign="Campaña escolar",
            price=Decimal("95.00"), cost_price=Decimal("57.00"),
            is_active=True,
        )
        cls.campaign = Campaign.objects.create(
            code="SCHOOL-2027",
            name="Campaña escolar 2027",
            year=2027,
            campaign_type=Campaign.CampaignType.SCHOOL,
            status=Campaign.Status.ACTIVE,
            created_by=cls.actor,
        )
        cls.pipeline = Pipeline.objects.create(
            code="CRM-PIPELINE-DEMO-TEST", name="Pipeline de test",
            is_default=True, created_by=cls.actor,
        )
        PipelineStage.objects.create(
            pipeline=cls.pipeline, code="proyeccion_ventas",
            name="Proyección", order=10, category=PipelineStage.Category.OPEN,
            is_initial=True, created_by=cls.actor,
        )
        PipelineStage.objects.create(
            pipeline=cls.pipeline, code="cotizacion_enviada",
            name="Cotización enviada", order=40, category=PipelineStage.Category.OPEN,
            created_by=cls.actor,
        )

    def params(self):
        return [
            "--year", "2027", "--school-id", str(self.school.pk),
            "--product-id", str(self.product.pk),
        ]

    def test_vista_previa_no_escribe_en_bd(self):
        result = StringIO()
        call_command("preparar_demo_erp", *self.params(), stdout=result)
        self.assertIn("No se cambió ningún registro", result.getvalue())
        self.assertEqual(School.objects.count(), 1)
        self.assertFalse(Opportunity.objects.exists())
        self.assertFalse(CommercialQuotation.objects.exists())

    def test_creacion_exige_bd_aislada(self):
        with self.assertRaisesMessage(CommandError, "Operación bloqueada"):
            call_command("preparar_demo_erp", *self.params(), "--crear", stdout=StringIO())
        self.assertEqual(School.objects.count(), 1)

    def test_local_necesita_autorizacion_explicita(self):
        with patch(
            "crm.management.commands.preparar_demo_erp._is_local_dev_database",
            return_value=True,
        ):
            with self.assertRaisesMessage(CommandError, "Operación bloqueada"):
                call_command("preparar_demo_erp", *self.params(), "--crear", stdout=StringIO())

            with patch(
                "crm.management.commands.preparar_demo_erp._is_demo_database",
                return_value=False,
            ):
                call_command(
                    "preparar_demo_erp", *self.params(),
                    "--crear", "--local", stdout=StringIO(),
                )
        self.assertEqual(School.objects.count(), 2)
        self.assertEqual(Campaign.objects.count(), 1)

    def test_local_bloqueado_fuera_del_entorno_permitido(self):
        with patch(
            "crm.management.commands.preparar_demo_erp._is_local_dev_database",
            return_value=False,
        ):
            with self.assertRaisesMessage(CommandError, "Operación bloqueada"):
                call_command(
                    "preparar_demo_erp", *self.params(),
                    "--crear", "--local", stdout=StringIO(),
                )
        self.assertEqual(School.objects.count(), 1)

    def test_no_crea_campana_activa_por_si_mismo(self):
        Campaign.objects.all().delete()
        with self.assertRaisesMessage(CommandError, "campaña escolar activa"):
            call_command("preparar_demo_erp", *self.params(), stdout=StringIO())
        self.assertEqual(School.objects.count(), 1)

    def test_crea_demostracion_con_producto_real_y_cotizacion_en_borrador(self):
        with patch(
            "crm.management.commands.preparar_demo_erp._is_demo_database",
            return_value=True,
        ):
            call_command("preparar_demo_erp", *self.params(), "--crear", stdout=StringIO())
            call_command("preparar_demo_erp", *self.params(), "--crear", stdout=StringIO())

        self.assertEqual(School.objects.count(), 2)
        real = School.objects.get(pk=self.school.pk)
        self.assertEqual(real.name, "Institución del padrón")
        demo_school = School.objects.exclude(pk=real.pk).get()
        self.assertTrue(demo_school.name.startswith("[PRUEBA ERP]"))
        self.assertIsNone(demo_school.institution_code)
        opportunity = Opportunity.objects.get(school=demo_school)
        self.assertTrue(opportunity.title.startswith("[PRUEBA ERP]"))
        projection = CommercialProjection.objects.get(opportunity=opportunity)
        self.assertEqual(projection.items.count(), 1)
        self.assertEqual(projection.items.get().quantity, 10)
        self.assertEqual(projection.items.get().product_id, self.product.pk)
        quotation = CommercialQuotation.objects.get(opportunity=opportunity)
        self.assertEqual(quotation.status, CommercialQuotation.Status.DRAFT)
        self.assertEqual(quotation.items.get().quantity, 10)
        self.assertEqual(quotation.items.get().pvp, Decimal("95.00"))
        self.assertEqual(quotation.items.get().product_id, self.product.pk)
        self.assertEqual(Campaign.objects.count(), 1)
        self.assertEqual(Campaign.objects.get().pk, self.campaign.pk)
        self.assertEqual(opportunity.campaign_id, self.campaign.pk)

    def test_lote_selecciona_colegios_y_no_duplica_borradores(self):
        segundo = School.objects.create(
            name="Otro colegio importado", created_by=self.actor,
        )
        otra_editorial = Provider.objects.create(name="Editorial para la segunda prueba")
        segundo_libro = Product.objects.create(
            name="Comunicación del catálogo", code="DEMO-COM4",
            provider=otra_editorial, level=self.level, grade=self.grade,
            commercial_line=Product.CommercialLine.SCHOOL_TEXT,
        )
        ProductPrice.objects.create(
            product=segundo_libro, year=2027, campaign="Campaña escolar",
            price=Decimal("80.00"), cost_price=Decimal("50.00"),
            is_active=True,
        )

        vista_previa = StringIO()
        call_command(
            "preparar_demo_erp_lote", "--year", "2027", "--cantidad", "2",
            stdout=vista_previa,
        )
        self.assertIn("No se guardó ningún registro", vista_previa.getvalue())
        self.assertEqual(School.objects.count(), 2)
        self.assertFalse(Opportunity.objects.exists())

        with patch(
            "crm.management.commands.preparar_demo_erp_lote._is_demo_database",
            return_value=True,
        ), patch(
            "crm.management.commands.preparar_demo_erp._is_demo_database",
            return_value=True,
        ):
            call_command(
                "preparar_demo_erp_lote", "--year", "2027", "--cantidad", "2",
                "--crear", stdout=StringIO(),
            )
            call_command(
                "preparar_demo_erp_lote", "--year", "2027", "--cantidad", "2",
                "--crear", stdout=StringIO(),
            )
        self.assertEqual(School.objects.count(), 4)
        self.assertEqual(Opportunity.objects.count(), 2)
        self.assertEqual(CommercialQuotation.objects.count(), 2)
        self.assertEqual(
            set(CommercialQuotation.objects.values_list(
                "items__product__provider_id", flat=True,
            )),
            {self.provider.pk, otra_editorial.pk},
        )
        self.assertTrue(School.objects.filter(pk=segundo.pk).exists())
        self.assertTrue(all(
            quotation.status == CommercialQuotation.Status.DRAFT
            for quotation in CommercialQuotation.objects.all()
        ))

    def test_lote_bloqueado_fuera_de_entorno_local(self):
        School.objects.create(name="Colegio de apoyo", created_by=self.actor)
        with self.assertRaisesMessage(CommandError, "Operación bloqueada"):
            call_command(
                "preparar_demo_erp_lote", "--year", "2027", "--cantidad", "2",
                "--crear", "--local", stdout=StringIO(),
            )
        self.assertFalse(Opportunity.objects.exists())
