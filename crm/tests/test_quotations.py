from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from catalog.models import (
    Area,
    Grade,
    Level,
    Product,
    ProductPrice,
    ProductType,
    Provider,
)
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
    accept_commercial_quotation,
    approve_commercial_quotation_discount,
    create_commercial_quotation_from_projection,
    reopen_commercial_quotation_negotiation,
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
        self.school_text_type = ProductType.objects.create(
            name="Texto escolar",
            is_active=True,
        )
        self.product = Product.objects.create(
            provider=self.provider,
            name="Matemática 4 Cotización",
            code="MAT-4-COT",
            level=self.level,
            grade=self.grade,
            area=self.area,
            product_type=self.school_text_type,
            commercial_line=Product.CommercialLine.SCHOOL_TEXT,
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
            commercial_line=CommercialProjection.CommercialLine.SCHOOL_TEXT,
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
        self.assertEqual(
            quotation.internal_code,
            f"BE-COT-2027-{quotation.pk:06d}-V01",
        )
        self.assertEqual(
            quotation.commercial_line,
            CommercialQuotation.CommercialLine.SCHOOL_TEXT,
        )
        self.assertFalse(quotation.requires_discount_approval)
        self.assertEqual(
            quotation.discount_approval_status,
            CommercialQuotation.DiscountApprovalStatus.NOT_REQUIRED,
        )
        self.assertEqual(item.quantity, 20)
        self.assertEqual(item.pvp, Decimal("100.00"))
        self.assertEqual(item.supplier_cost, Decimal("0.00"))
        self.assertIsNone(item.supplier_discount_percent)
        self.assertEqual(item.school_discount_percent, Decimal("20.00"))
        self.assertEqual(item.school_price, Decimal("80.00"))
        self.assertEqual(item.parent_price, Decimal("100.00"))
        self.assertEqual(item.product_code_snapshot, "MAT-4-COT")
        self.assertEqual(
            item.commercial_line,
            item.CommercialLine.SCHOOL_TEXT,
        )
        self.assertEqual(
            item.commercial_margin_unit,
            Decimal("0.00"),
        )
        self.assertEqual(
            item.commercial_margin_total,
            Decimal("0.00"),
        )
        self.assertEqual(
            item.commercial_margin_percent,
            Decimal("0.00"),
        )
        self.assertEqual(
            item.profitability_band,
            item.ProfitabilityBand.UNCLASSIFIED,
        )
        self.assertIsNone(item.max_green_discount_percent)
        self.assertIsNone(item.green_discount_headroom_points)
        self.assertFalse(item.uses_reference_price)

    def test_cannot_send_without_editorial_discount(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.advisor,
            sale_mode=CommercialQuotation.SaleMode.POINT_OF_SALE,
            service_date=date(2027, 1, 15),
        )

        with self.assertRaisesMessage(
            CommercialQuotationError,
            "descuento editorial",
        ):
            send_commercial_quotation(
                quotation=quotation,
                actor=self.advisor,
            )

    def test_discount_over_standard_requires_approval_before_send(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.admin,
            sale_mode=CommercialQuotation.SaleMode.POINT_OF_SALE,
            service_date=date(2027, 1, 15),
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "school_discount_percent": Decimal("25.00"),
                    "supplier_discount_percent": Decimal("40.00"),
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
                actor=self.admin,
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
            actor=self.admin,
            sale_mode=CommercialQuotation.SaleMode.POINT_OF_SALE,
            service_date=date(2027, 1, 15),
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "supplier_discount_percent": Decimal("40.00"),
                }
            ],
        )

        item = quotation.items.get()

        self.assertTrue(item.uses_reference_price)
        self.assertEqual(item.price_year_snapshot, 2026)
        self.assertEqual(
            item.supplier_discount_percent,
            Decimal("40.00"),
        )
        self.assertEqual(item.supplier_cost, Decimal("54.00"))

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
            commercial_line=CommercialProjection.CommercialLine.SCHOOL_TEXT,
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
            actor=self.admin,
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "school_discount_percent": Decimal("25.00"),
                    "supplier_discount_percent": Decimal("40.00"),
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
            updated.internal_code,
            quotation.internal_code,
        )
        self.assertEqual(
            self.opportunity.quotations.count(),
            1,
        )
        self.assertEqual(item.quantity, 20)
        self.assertEqual(item.school_discount_percent, Decimal("25.00"))
        self.assertEqual(item.school_price, Decimal("75.00"))
        self.assertEqual(item.parent_price, Decimal("95.00"))
        self.assertEqual(item.school_commission, Decimal("5.00"))
        self.assertEqual(
            item.commission_mode,
            item.CommissionMode.PER_UNIT,
        )
        self.assertEqual(
            item.commission_input_amount,
            Decimal("5.00"),
        )
        self.assertEqual(
            item.commercial_margin_unit,
            Decimal("10.00"),
        )
        self.assertEqual(
            item.profitability_band,
            item.ProfitabilityBand.RED,
        )
        self.assertEqual(updated.notes, "Ajuste comercial de prueba.")
        self.assertTrue(updated.requires_discount_approval)
        self.assertEqual(
            updated.discount_approval_status,
            CommercialQuotation.DiscountApprovalStatus.PENDING,
        )

    def test_advisor_cannot_register_positive_commission(self):
        with self.assertRaisesMessage(
            CommercialQuotationError,
            "Solo supervisión comercial",
        ):
            create_commercial_quotation_from_projection(
                opportunity=self.opportunity,
                actor=self.advisor,
                item_adjustments=[
                    {
                        "projection_item": self.projection_item,
                        "school_commission": Decimal("5.00"),
                    }
                ],
            )

    def test_supervisor_can_use_total_commission(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.admin,
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "supplier_discount_percent": Decimal("40.00"),
                    "commission_mode": "total",
                    "commission_amount": Decimal("100.00"),
                }
            ],
        )

        item = quotation.items.get()

        self.assertEqual(item.commission_mode, "total")
        self.assertEqual(
            item.commission_input_amount,
            Decimal("100.00"),
        )
        self.assertEqual(item.school_commission, Decimal("5.00"))
        self.assertEqual(
            item.commercial_margin_unit,
            Decimal("15.00"),
        )
        self.assertEqual(
            item.profitability_band,
            item.ProfitabilityBand.AMBER,
        )

    def test_plan_lector_uses_approved_profitability_thresholds(self):
        plan_lector_type = ProductType.objects.create(
            name="Plan lector",
            is_active=True,
        )
        self.product.product_type = plan_lector_type
        self.product.commercial_line = Product.CommercialLine.READING_PLAN
        self.product.save(
            update_fields=[
                "product_type",
                "commercial_line",
                "updated_at",
            ]
        )

        ProductPrice.objects.filter(product=self.product).update(
            cost_price=Decimal("74.00")
        )
        self.projection.commercial_line = (
            CommercialProjection.CommercialLine.READING_PLAN
        )
        self.projection.save(
            update_fields=["commercial_line", "updated_at"]
        )

        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.admin,
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "supplier_discount_percent": Decimal("26.00"),
                    "reading_month": 4,
                }
            ],
        )

        item = quotation.items.get()

        self.assertEqual(
            item.commercial_line,
            item.CommercialLine.READING_PLAN,
        )
        self.assertEqual(item.reading_month, 4)
        self.assertEqual(
            item.commercial_margin_unit,
            Decimal("6.00"),
        )
        self.assertEqual(
            item.profitability_band,
            item.ProfitabilityBand.GREEN,
        )
        self.assertEqual(
            item.max_green_discount_percent,
            Decimal("20.99"),
        )

    def test_plan_lector_requires_reading_month(self):
        self.projection.commercial_line = (
            CommercialProjection.CommercialLine.READING_PLAN
        )
        self.projection.save(
            update_fields=["commercial_line", "updated_at"]
        )

        with self.assertRaisesMessage(
            CommercialQuotationError,
            "Selecciona el mes de lectura",
        ):
            create_commercial_quotation_from_projection(
                opportunity=self.opportunity,
                actor=self.admin,
            )

    def test_quantity_must_be_changed_in_projection_not_quotation(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.advisor,
        )

        with self.assertRaisesMessage(
            CommercialQuotationError,
            "proviene de la proyección",
        ):
            update_commercial_quotation_from_projection(
                quotation=quotation,
                actor=self.advisor,
                item_adjustments=[
                    {
                        "projection_item": self.projection_item,
                        "quantity": 15,
                    }
                ],
            )

        item = quotation.items.get()
        self.assertEqual(item.quantity, 20)

    def _create_ready_quotation(self):
        return create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.admin,
            sale_mode=CommercialQuotation.SaleMode.POINT_OF_SALE,
            service_date=date(2027, 1, 15),
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "supplier_discount_percent": Decimal("40.00"),
                }
            ],
        )

    def test_send_requires_sale_mode_and_service_date(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.admin,
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "supplier_discount_percent": Decimal("40.00"),
                }
            ],
        )

        with self.assertRaisesMessage(
            CommercialQuotationError,
            "modalidad de venta",
        ):
            send_commercial_quotation(
                quotation=quotation,
                actor=self.advisor,
            )

    def test_fair_requires_start_and_end_time_before_send(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.admin,
            sale_mode=CommercialQuotation.SaleMode.FAIR,
            service_date=date(2027, 1, 18),
            fair_start_time=time(15, 0),
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "supplier_discount_percent": Decimal("40.00"),
                }
            ],
        )

        with self.assertRaisesMessage(
            CommercialQuotationError,
            "hora de inicio y la hora de fin",
        ):
            send_commercial_quotation(
                quotation=quotation,
                actor=self.advisor,
            )

    def test_fair_end_time_must_be_after_start_time(self):
        with self.assertRaisesMessage(
            CommercialQuotationError,
            "hora de fin de la feria",
        ):
            create_commercial_quotation_from_projection(
                opportunity=self.opportunity,
                actor=self.admin,
                sale_mode=CommercialQuotation.SaleMode.FAIR,
                service_date=date(2027, 1, 18),
                fair_start_time=time(18, 0),
                fair_end_time=time(15, 0),
                item_adjustments=[
                    {
                        "projection_item": self.projection_item,
                        "supplier_discount_percent": Decimal("40.00"),
                    }
                ],
            )

    def test_non_fair_mode_clears_fair_hours(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.admin,
            sale_mode=CommercialQuotation.SaleMode.CONSIGNMENT,
            service_date=date(2027, 1, 20),
            fair_start_time=time(8, 0),
            fair_end_time=time(13, 0),
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "supplier_discount_percent": Decimal("40.00"),
                }
            ],
        )

        self.assertEqual(
            quotation.sale_mode,
            CommercialQuotation.SaleMode.CONSIGNMENT,
        )
        self.assertEqual(quotation.service_date, date(2027, 1, 20))
        self.assertIsNone(quotation.fair_start_time)
        self.assertIsNone(quotation.fair_end_time)

    def test_sending_twice_is_idempotent(self):
        quotation = self._create_ready_quotation()

        first = send_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )
        first_sent_at = first.sent_at
        history_count = self.opportunity.stage_history.count()

        second = send_commercial_quotation(
            quotation=first,
            actor=self.advisor,
        )

        self.opportunity.refresh_from_db()

        self.assertEqual(second.status, CommercialQuotation.Status.SENT)
        self.assertEqual(second.sent_at, first_sent_at)
        self.assertEqual(
            self.opportunity.stage,
            self.quotation_stage,
        )
        self.assertEqual(
            self.opportunity.stage_history.count(),
            history_count,
        )

    def test_acceptance_keeps_opportunity_in_quotation_stage(self):
        quotation = self._create_ready_quotation()
        sent = send_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )
        history_count = self.opportunity.stage_history.count()

        accepted = accept_commercial_quotation(
            quotation=sent,
            actor=self.advisor,
        )
        first_accepted_at = accepted.accepted_at

        accepted_again = accept_commercial_quotation(
            quotation=accepted,
            actor=self.advisor,
        )

        self.opportunity.refresh_from_db()

        self.assertEqual(
            accepted_again.status,
            CommercialQuotation.Status.ACCEPTED,
        )
        self.assertEqual(
            accepted_again.accepted_at,
            first_accepted_at,
        )
        self.assertEqual(
            self.opportunity.stage,
            self.quotation_stage,
        )
        self.assertEqual(
            self.opportunity.stage_history.count(),
            history_count,
        )

    def test_accepted_quotation_can_reopen_negotiation_before_adoption(self):
        quotation = self._create_ready_quotation()
        quotation = send_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )
        quotation = accept_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )
        accepted_at = quotation.accepted_at
        accepted_by_id = quotation.accepted_by_id

        reopened = reopen_commercial_quotation_negotiation(
            quotation=quotation,
            actor=self.admin,
            reason="El colegio solicita modificar la población.",
        )

        self.opportunity.refresh_from_db()

        self.assertEqual(
            reopened.status,
            CommercialQuotation.Status.SUPERSEDED,
        )
        self.assertEqual(reopened.accepted_at, accepted_at)
        self.assertEqual(reopened.accepted_by_id, accepted_by_id)
        self.assertEqual(reopened.reopened_by, self.admin)
        self.assertIsNotNone(reopened.reopened_at)
        self.assertEqual(
            reopened.reopen_reason,
            "El colegio solicita modificar la población.",
        )
        self.assertEqual(
            self.opportunity.stage,
            self.quotation_stage,
        )

        replacement = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.advisor,
        )

        self.assertEqual(replacement.version, 2)
        self.assertEqual(
            replacement.status,
            CommercialQuotation.Status.DRAFT,
        )

    def test_reopen_negotiation_requires_reason(self):
        quotation = self._create_ready_quotation()
        quotation = send_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )
        quotation = accept_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )

        with self.assertRaisesMessage(
            CommercialQuotationError,
            "Registra el motivo",
        ):
            reopen_commercial_quotation_negotiation(
                quotation=quotation,
                actor=self.admin,
                reason="   ",
            )

    def test_sent_quotation_cannot_be_edited(self):
        quotation = self._create_ready_quotation()
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
                actor=self.advisor,
                item_adjustments=[
                    {
                        "projection_item": self.projection_item,
                        "quantity": 10,
                    }
                ],
            )

    def test_supervisor_supplier_discount_calculates_supplier_cost(self):
        quotation = create_commercial_quotation_from_projection(
            opportunity=self.opportunity,
            actor=self.admin,
            item_adjustments=[
                {
                    "projection_item": self.projection_item,
                    "supplier_discount_percent": Decimal("30.00"),
                }
            ],
        )

        item = quotation.items.get()

        self.assertEqual(
            item.supplier_discount_percent,
            Decimal("30.00"),
        )
        self.assertEqual(item.supplier_cost, Decimal("70.00"))
        self.assertEqual(item.school_price, Decimal("80.00"))
        self.assertEqual(item.commercial_margin_unit, Decimal("10.00"))
        self.assertEqual(
            item.profitability_band,
            item.ProfitabilityBand.RED,
        )

    def test_advisor_cannot_register_supplier_discount(self):
        with self.assertRaisesMessage(
            CommercialQuotationError,
            "Solo supervisión comercial",
        ):
            create_commercial_quotation_from_projection(
                opportunity=self.opportunity,
                actor=self.advisor,
                item_adjustments=[
                    {
                        "projection_item": self.projection_item,
                        "supplier_discount_percent": Decimal("30.00"),
                    }
                ],
            )

