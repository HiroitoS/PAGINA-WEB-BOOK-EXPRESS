from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from catalog.models import Area, Grade, Level, Product, Provider
from crm.models import (
    Adoption,
    Campaign,
    CommercialQuotation,
    CommercialTeam,
    CommercialTeamMembership,
    OpportunityStageHistory,
    Pipeline,
    PipelineStage,
    School,
    SchoolContact,
)
from crm.services import (
    AdoptionError,
    accept_commercial_quotation,
    confirm_adoption,
    create_commercial_quotation,
    create_opportunity,
    send_commercial_quotation,
)


User = get_user_model()


class CRMAdoptionFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="crm-adoption-admin",
            password="test-password",
            first_name="Admin",
            last_name="CRM",
        )
        self.advisor = User.objects.create_user(
            username="crm-adoption-advisor",
            password="test-password",
            first_name="Asesor",
            last_name="Book Express",
        )

        self.team = CommercialTeam.objects.create(
            code="CRM-ADOPTION-TEAM",
            name="Equipo adopciones",
            created_by=self.admin,
        )
        CommercialTeamMembership.objects.create(
            team=self.team,
            user=self.advisor,
            role=CommercialTeamMembership.Role.ADVISOR,
            created_by=self.admin,
        )

        self.school = School.objects.create(
            name="Colegio Adopción",
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )
        self.contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Directora Adopción",
            position="Directora",
            decision_role=SchoolContact.DecisionRole.DECISION_MAKER,
            is_primary=True,
            created_by=self.admin,
        )

        self.campaign = Campaign.objects.create(
            code="CRM-ADOPTION-2027",
            name="Campaña escolar 2027",
            year=2027,
            campaign_type=Campaign.CampaignType.SCHOOL,
            status=Campaign.Status.ACTIVE,
            created_by=self.admin,
        )

        self.pipeline = Pipeline.objects.create(
            code="CRM-ADOPTION-PIPE",
            name="Pipeline adopciones",
            is_default=True,
            created_by=self.admin,
        )
        self.initial_stage = PipelineStage.objects.create(
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
        self.won_stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="cierre_ganado_adopcion",
            name="Cierre ganado (adopción)",
            order=50,
            category=PipelineStage.Category.WON,
            created_by=self.admin,
        )
        self.lost_stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="cierre_perdido",
            name="Cierre perdido",
            order=60,
            category=PipelineStage.Category.LOST,
            created_by=self.admin,
        )

        self.opportunity = create_opportunity(
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            created_by=self.admin,
        )

        provider = Provider.objects.create(
            name="Editorial Adopción",
            is_active=True,
        )
        level = Level.objects.create(
            name="Primaria Adopción",
            is_active=True,
        )
        grade = Grade.objects.create(
            name="4to Primaria Adopción",
            order=4,
            is_active=True,
        )
        area = Area.objects.create(
            name="Matemática Adopción",
            is_active=True,
        )

        self.product = Product.objects.create(
            provider=provider,
            name="Matemática 4 Adopción",
            level=level,
            grade=grade,
            area=area,
            is_active=True,
        )

    def quotation_items(self):
        return [
            {
                "product": self.product,
                "quantity": 60,
                "pvp": Decimal("120.00"),
                "supplier_cost": Decimal("70.00"),
                "school_price": Decimal("90.00"),
                "parent_price": Decimal("110.00"),
                "school_commission": Decimal("5.00"),
            }
        ]

    def test_quotation_versions_keep_product_snapshots(self):
        first = create_commercial_quotation(
            opportunity=self.opportunity,
            actor=self.advisor,
            items=self.quotation_items(),
            notes="Primera propuesta.",
        )
        second = create_commercial_quotation(
            opportunity=self.opportunity,
            actor=self.advisor,
            items=self.quotation_items(),
            notes="Segunda propuesta.",
        )

        self.assertEqual(first.version, 1)
        self.assertEqual(second.version, 2)

        item = first.items.get()

        self.assertEqual(
            item.product_name_snapshot,
            "Matemática 4 Adopción",
        )
        self.assertEqual(
            item.provider_name_snapshot,
            "Editorial Adopción",
        )
        self.assertEqual(
            item.level_name_snapshot,
            "Primaria Adopción",
        )
        self.assertEqual(
            item.grade_name_snapshot,
            "4to Primaria Adopción",
        )
        self.assertEqual(
            item.area_name_snapshot,
            "Matemática Adopción",
        )

    def test_sending_quotation_moves_opportunity_to_quote_stage(self):
        quotation = create_commercial_quotation(
            opportunity=self.opportunity,
            actor=self.advisor,
            items=self.quotation_items(),
        )

        sent = send_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )

        self.opportunity.refresh_from_db()

        self.assertEqual(
            sent.status,
            CommercialQuotation.Status.SENT,
        )
        self.assertEqual(
            self.opportunity.stage,
            self.quotation_stage,
        )
        self.assertTrue(
            OpportunityStageHistory.objects.filter(
                opportunity=self.opportunity,
                to_stage=self.quotation_stage,
            ).exists()
        )

    def test_confirm_adoption_copies_snapshot_and_closes_won(self):
        quotation = create_commercial_quotation(
            opportunity=self.opportunity,
            actor=self.advisor,
            items=self.quotation_items(),
        )
        quotation = send_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )
        quotation = accept_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )

        signed_at = timezone.now() - timedelta(minutes=10)

        adoption = confirm_adoption(
            quotation=quotation,
            authorized_contact=self.contact,
            signed_at=signed_at,
            actor=self.admin,
            notes="Formato firmado por la dirección.",
        )

        self.opportunity.refresh_from_db()

        self.assertEqual(
            self.opportunity.stage,
            self.won_stage,
        )
        self.assertIsNotNone(self.opportunity.closed_at)
        self.assertEqual(
            self.opportunity.closed_by,
            self.admin,
        )
        self.assertEqual(
            adoption.school,
            self.school,
        )
        self.assertEqual(
            adoption.campaign,
            self.campaign,
        )
        self.assertEqual(
            adoption.authorized_contact,
            self.contact,
        )
        self.assertEqual(
            adoption.advisor,
            self.advisor,
        )
        self.assertEqual(
            adoption.advisor_name_snapshot,
            "Asesor Book Express",
        )
        self.assertTrue(adoption.is_current)

        adoption_item = adoption.items.get()

        self.assertEqual(adoption_item.product, self.product)
        self.assertEqual(adoption_item.quantity, 60)
        self.assertEqual(
            adoption_item.school_price,
            Decimal("90.00"),
        )
        self.assertEqual(
            adoption_item.parent_price,
            Decimal("110.00"),
        )
        self.assertEqual(
            adoption_item.supplier_cost,
            Decimal("70.00"),
        )
        self.assertEqual(
            Adoption.objects.filter(
                opportunity=self.opportunity,
                is_current=True,
            ).count(),
            1,
        )

    def test_adoption_rejects_future_signature(self):
        quotation = create_commercial_quotation(
            opportunity=self.opportunity,
            actor=self.advisor,
            items=self.quotation_items(),
        )
        quotation = send_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )
        quotation = accept_commercial_quotation(
            quotation=quotation,
            actor=self.advisor,
        )

        with self.assertRaises(AdoptionError):
            confirm_adoption(
                quotation=quotation,
                authorized_contact=self.contact,
                signed_at=timezone.now() + timedelta(days=1),
                actor=self.admin,
            )

        self.opportunity.refresh_from_db()

        self.assertEqual(
            self.opportunity.stage,
            self.quotation_stage,
        )
        self.assertFalse(
            Adoption.objects.filter(
                opportunity=self.opportunity,
            ).exists()
        )
