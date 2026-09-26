from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from catalog.models import Area, Grade, Level, Product, ProductPrice, Provider
from crm.models import (
    Campaign,
    CommercialProjection,
    CommercialProjectionGrade,
    CommercialProjectionItem,
    CommercialQuotation,
    Pipeline,
    PipelineStage,
    School,
    SchoolEducationalService,
)
from crm.services import (
    CommercialQuotationError,
    approve_commercial_quotation_discount,
    create_commercial_quotation_from_projection,
    send_commercial_quotation,
    update_commercial_quotation_from_projection,
)


User = get_user_model()


class CRMQuotationFromProjectionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="crm-quote-admin",
            email="quote-admin@example.com",
            password="test-password",
        )
        self.advisor = User.objects.create_user(
            username="crm-quote-advisor",
            password="test-password",
        )

        self.school = School.objects.create(
            name="Colegio Cotización",
            created_by=self.admin,
        )
        self.campaign = Campaign.objects.create(
            code="CRM-QUOTE-2027",
            name="Campaña escolar 2027",
            year=2027,
            campaign_type=Campaign.CampaignType.SCHOOL,
            status=Campaign.Status.ACTIVE,
            created_by=self.admin,
        )
        self.pipeline = Pipeline.objects.create(
            code="CRM-QUOTE-PIPE",
            name="Pipeline cotización",
            is_default=True,
            created_by=self.admin,
        )
        self.projection_stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="proyeccion_ventas",
            name="Proyección de ventas",
            order=10,
            category=PipelineStage.Category.OPEN,
            is_initial=True,
            created_by=self.admin,
        )
        self.quotation_stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="cotizacion_enviada",
            name="Cotización enviada",
            order=40,
            category=PipelineStage.Category.OPEN,
            created_by=self.admin,
        )
        self.opportunity = self.school.opportunities.create(
            title="Campaña 2027 - Colegio Cotización",
            campaign=self.campaign,
            pipeline=self.pipeline,
            stage=self.projection_stage,
            owner=self.advisor,
            created_by=self.admin,
        )

        self.level = Level.objects.create(
            name="Primaria Cotización",
            is_active=True,
        )
        self.grade = Grade.objects.create(
            name="4to Primaria Cotización",
            order=4,
            is_active=True,
        )
        self.area = Area.objects.create(
            name="Matemática Cotización",
            is_active=True,
        )
        self.provider = Provider.objects.create(
            name="Editorial Cotización",
            is_active=True,
        )
        self.product = Product.objects.create(
            provider=self.provider,
            name="Matemática 4 Cotización",
            level=self.level,
            grade=self.grade,
            area=self.area,
            is_active=True,
        )
        ProductPrice.objects.create(
            product=self.product,
            year=2027,
            campaign="Campaña escolar",
            price=Decimal("100.00"),
            cost_price=Decimal("60.00"),
            is_active=True,
        )

        self.service = SchoolEducationalService.objects.create(
            school=self.school,
            level=self.level,
            is_active=True,
            created_by=self.admin,
        )
        self.projection = CommercialProjection.objects.create(
            opportunity=self.opportunity,
            version=1,
            is_current=True,
            school_name_snapshot=self.school.name,
            campaign_name_snapshot=self.campaign.name,
            campaign_year_snapshot=self.campaign.year,
            created_by=self.advisor,
        )
        self.projection_grade = CommercialProjectionGrade.objects.create(
            projection=self.projection,
            service=self.service,
            grade=self.grade,
            level_name_snapshot=self.level.name,
            grade_name_snapshot=self.grade.name,
            section_count=1,
            student_count=20,
        )
        self.projection_item = CommercialProjectionItem.objects.create(
            projection=self.projection,
            grade_line=self.projection_grade,
            product=self.product,
            product_name_snapshot=self.product.name,
            provider_name_snapshot=self.provider.name,
            level_name_snapshot=self.level.name,
            grade_name_snapshot=self.grade.name,
            area_name_snapshot=self.area.name,
            quantity=20,
            unit_price=Decimal("100.00"),
            price_year_snapshot=2027,
            price_campaign_snapshot="Campaña escolar",
        )

    def test_create_from_projection_uses_backend_prices_and_standard_discount(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.advisor,
        )

        item = quotation.items.get()

        self.assertEqual(quotation.source_projection, self.projection)
        self.assertFalse(quotation.requires_discount_approval)
        self.assertEqual(
            quotation.discount_approval_status,
            CommercialQuotation.DiscountApprovalStatus.NOT_REQUIRED,
        )
        self.assertEqual(item.quantity, 20)
        self.assertEqual(item.pvp, Decimal("100.00"))
        self.assertEqual(item.supplier_cost, Decimal("60.00"))
        self.assertEqual(item.school_discount_percent, Decimal("20.00"))
        self.assertEqual(item.school_price, Decimal("80.00"))
        self.assertEqual(item.parent_price, Decimal("100.00"))
        self.assertFalse(item.uses_reference_price)

    def test_discount_over_standard_requires_approval_before_send(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.advisor,
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "school_discount_percent": Decimal("25.00"),
                }
            ],
        )

        item = quotation.items.get()

        self.assertTrue(quotation.requires_discount_approval)
        self.assertEqual(
            quotation.discount_approval_status,
            CommercialQuotation.DiscountApprovalStatus.PENDING,
        )
        self.assertEqual(item.school_price, Decimal("75.00"))

        with self.assertRaisesMessage(
            CommercialQuotationError,
            "necesita aprobación",
        ):
            send_commercial_quotation(
                quotation=quotation,
                actor=self.advisor,
            )

        approved = approve_commercial_quotation_discount(
            quotation=quotation,
            actor=self.admin,
            note="Descuento autorizado por jefatura comercial.",
        )
        sent = send_commercial_quotation(
            quotation=approved,
            actor=self.advisor,
        )

        self.opportunity.refresh_from_db()

        self.assertEqual(
            sent.discount_approval_status,
            CommercialQuotation.DiscountApprovalStatus.APPROVED,
        )
        self.assertEqual(sent.discount_approved_by, self.admin)
        self.assertEqual(sent.status, CommercialQuotation.Status.SENT)
        self.assertEqual(self.opportunity.stage, self.quotation_stage)

    def test_reference_price_can_be_drafted_but_not_sent(self):
        ProductPrice.objects.create(
            product=self.product,
            year=2026,
            campaign="Campaña escolar",
            price=Decimal("90.00"),
            cost_price=Decimal("55.00"),
            is_active=True,
        )
        self.projection_item.unit_price = Decimal("90.00")
        self.projection_item.price_year_snapshot = 2026
        self.projection_item.save(
            update_fields=[
                "unit_price",
                "price_year_snapshot",
                "updated_at",
            ]
        )

        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.advisor,
        )

        item = quotation.items.get()

        self.assertTrue(item.uses_reference_price)
        self.assertEqual(item.price_year_snapshot, 2026)
        self.assertEqual(item.supplier_cost, Decimal("55.00"))

        with self.assertRaisesMessage(
            CommercialQuotationError,
            "precios referenciales",
        ):
            send_commercial_quotation(
                quotation=quotation,
                actor=self.advisor,
            )

    def test_adjustment_must_belong_to_current_projection(self):
        another_projection = CommercialProjection.objects.create(
            opportunity=self.opportunity,
            version=2,
            is_current=False,
            school_name_snapshot=self.school.name,
            campaign_name_snapshot=self.campaign.name,
            campaign_year_snapshot=self.campaign.year,
            created_by=self.advisor,
        )
        another_grade = CommercialProjectionGrade.objects.create(
            projection=another_projection,
            service=self.service,
            grade=self.grade,
            level_name_snapshot=self.level.name,
            grade_name_snapshot=self.grade.name,
            section_count=1,
            student_count=10,
        )
        another_item = CommercialProjectionItem.objects.create(
            projection=another_projection,
            grade_line=another_grade,
            product=self.product,
            product_name_snapshot=self.product.name,
            provider_name_snapshot=self.provider.name,
            level_name_snapshot=self.level.name,
            grade_name_snapshot=self.grade.name,
            area_name_snapshot=self.area.name,
            quantity=10,
            unit_price=Decimal("100.00"),
            price_year_snapshot=2027,
            price_campaign_snapshot="Campaña escolar",
        )

        with self.assertRaisesMessage(
            CommercialQuotationError,
            "no pertenece a la proyección vigente",
        ):
            create_commercial_quotation_from_projection(
                opportunity=self.opportunity,
                actor=self.advisor,
                item_adjustments=[
                    {
                        "projection_item": another_item,
                    }
                ],
            )

    def test_draft_can_be_edited_without_creating_new_version(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.advisor,
        )

        updated = update_commercial_quotation_from_projection(
            quotation=quotation,
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "quantity": 15,
                    "school_discount_percent": Decimal("25.00"),
                    "parent_price": Decimal("95.00"),
                    "school_commission": Decimal("5.00"),
                }
            ],
            notes="Ajuste comercial de prueba.",
        )

        item = updated.items.get()

        self.assertEqual(updated.pk, quotation.pk)
        self.assertEqual(updated.version, 1)
        self.assertEqual(
            self.opportunity.quotations.count(),
            1,
        )
        self.assertEqual(item.quantity, 15)
        self.assertEqual(item.school_discount_percent, Decimal("25.00"))
        self.assertEqual(item.school_price, Decimal("75.00"))
        self.assertEqual(item.parent_price, Decimal("95.00"))
        self.assertEqual(item.school_commission, Decimal("5.00"))
        self.assertEqual(updated.notes, "Ajuste comercial de prueba.")
        self.assertTrue(updated.requires_discount_approval)
        self.assertEqual(
            updated.discount_approval_status,
            CommercialQuotation.DiscountApprovalStatus.PENDING,
        )

    def test_sent_quotation_cannot_be_edited(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.advisor,
        )
        sent = send_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )

        with self.assertRaisesMessage(
            CommercialQuotationError,
            "Solo una cotización en borrador puede editarse.",
        ):
            update_commercial_quotation_from_projection(
                quotation=sent,
                item_adjustments=[
                    {
                        "projection_item": self.projection_item,
                        "quantity": 10,
                    }
                ],
            )

