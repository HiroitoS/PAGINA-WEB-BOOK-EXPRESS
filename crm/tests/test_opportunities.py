from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from crm.models import (
    Campaign,
    CommercialTeam,
    CommercialTeamMembership,
    Opportunity,
    OpportunityStageHistory,
    Pipeline,
    PipelineStage,
    School,
    SchoolContact,
)
from crm.services import (
    OpportunityTransitionError,
    create_opportunity,
    reopen_opportunity,
    transition_opportunity_stage,
)


User = get_user_model()


class CRMOpportunityFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="crm-admin-flow",
            password="test-password",
        )
        self.advisor = User.objects.create_user(
            username="crm-advisor-flow",
            password="test-password",
        )

        self.team = CommercialTeam.objects.create(
            code="VENTAS-HYO-FLOW",
            name="Equipo Huancayo",
            created_by=self.admin,
        )
        CommercialTeamMembership.objects.create(
            team=self.team,
            user=self.advisor,
            role=CommercialTeamMembership.Role.ADVISOR,
            created_by=self.admin,
        )

        self.school = School.objects.create(
            name="Colegio CRM",
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )
        self.campaign = Campaign.objects.create(
            code="ESCOLAR-2027-FLOW",
            name="Campaña escolar 2027",
            year=2027,
            campaign_type=Campaign.CampaignType.SCHOOL,
            status=Campaign.Status.ACTIVE,
            created_by=self.admin,
        )
        self.pipeline = Pipeline.objects.create(
            code="BOOK-EXPRESS-FLOW",
            name="Proceso comercial Book Express",
            is_default=True,
            created_by=self.admin,
        )
        self.initial_stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="por_contactar",
            name="Por contactar",
            order=10,
            category=PipelineStage.Category.OPEN,
            is_initial=True,
            created_by=self.admin,
        )
        self.negotiation_stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="propuesta_negociacion",
            name="Propuesta / negociación",
            order=40,
            category=PipelineStage.Category.OPEN,
            created_by=self.admin,
        )
        self.won_stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="adopcion_confirmada",
            name="Adopción confirmada",
            order=50,
            category=PipelineStage.Category.WON,
            created_by=self.admin,
        )
        self.lost_stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="no_concretada",
            name="No concretada",
            order=60,
            category=PipelineStage.Category.LOST,
            created_by=self.admin,
        )

    def test_pipeline_allows_only_one_initial_stage(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PipelineStage.objects.create(
                    pipeline=self.pipeline,
                    code="otra_inicial",
                    name="Otra inicial",
                    order=20,
                    category=PipelineStage.Category.OPEN,
                    is_initial=True,
                    created_by=self.admin,
                )

    def test_create_opportunity_resolves_school_defaults_and_history(self):
        contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Directora CRM",
            position="Directora",
            is_primary=True,
            created_by=self.admin,
        )

        opportunity = create_opportunity(
            school=self.school,
            created_by=self.admin,
        )

        self.assertEqual(
            opportunity.title,
            "Campaña escolar 2027 - Colegio CRM",
        )
        self.assertEqual(opportunity.campaign, self.campaign)
        self.assertEqual(opportunity.pipeline, self.pipeline)
        self.assertEqual(opportunity.stage, self.initial_stage)
        self.assertEqual(opportunity.primary_contact, contact)
        self.assertEqual(opportunity.owner, self.advisor)
        self.assertEqual(opportunity.team, self.team)
        self.assertEqual(opportunity.stage_history.count(), 1)

        history = opportunity.stage_history.first()
        self.assertEqual(
            history.transition_type,
            OpportunityStageHistory.TransitionType.CREATED,
        )
        self.assertIsNone(history.from_stage)
        self.assertEqual(history.to_stage, self.initial_stage)

    def test_open_duplicate_for_same_school_campaign_pipeline_is_rejected(
        self,
    ):
        create_opportunity(
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            created_by=self.admin,
        )

        with self.assertRaises(OpportunityTransitionError):
            create_opportunity(
                school=self.school,
                campaign=self.campaign,
                pipeline=self.pipeline,
                created_by=self.admin,
            )

    def test_new_opportunity_is_allowed_after_previous_one_is_closed(self):
        first = create_opportunity(
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            created_by=self.admin,
        )

        transition_opportunity_stage(
            opportunity=first,
            to_stage=self.lost_stage,
            changed_by=self.advisor,
            note="El colegio no continuará este año.",
        )

        second = create_opportunity(
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            created_by=self.admin,
        )

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(
            Opportunity.objects.filter(
                school=self.school,
                campaign=self.campaign,
                pipeline=self.pipeline,
            ).count(),
            2,
        )
        self.assertFalse(second.is_closed)

    def test_lost_transition_requires_reason_and_closes_opportunity(self):
        opportunity = create_opportunity(
            title="Adopción escolar 2027",
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            created_by=self.admin,
        )

        with self.assertRaises(OpportunityTransitionError):
            transition_opportunity_stage(
                opportunity=opportunity,
                to_stage=self.lost_stage,
                changed_by=self.advisor,
                note="",
            )

        closed = transition_opportunity_stage(
            opportunity=opportunity,
            to_stage=self.lost_stage,
            changed_by=self.advisor,
            note="El colegio continuará con su propuesta actual.",
        )

        self.assertTrue(closed.is_closed)
        self.assertIsNotNone(closed.closed_at)
        self.assertEqual(closed.closed_by, self.advisor)
        self.assertEqual(
            closed.closure_note,
            "El colegio continuará con su propuesta actual.",
        )

    def test_closed_opportunity_requires_explicit_reopen(self):
        opportunity = create_opportunity(
            title="Adopción escolar 2027",
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            created_by=self.admin,
        )
        closed = transition_opportunity_stage(
            opportunity=opportunity,
            to_stage=self.lost_stage,
            changed_by=self.advisor,
            note="No se concretó la negociación.",
        )

        with self.assertRaises(OpportunityTransitionError):
            transition_opportunity_stage(
                opportunity=closed,
                to_stage=self.negotiation_stage,
                changed_by=self.admin,
                note="Volver a negociar.",
            )

        reopened = reopen_opportunity(
            opportunity=closed,
            to_stage=self.negotiation_stage,
            changed_by=self.admin,
            reason="El colegio solicitó retomar la propuesta.",
        )

        self.assertFalse(reopened.is_closed)
        self.assertIsNone(reopened.closed_at)
        self.assertEqual(reopened.closure_note, "")

        latest_history = reopened.stage_history.first()
        self.assertEqual(
            latest_history.transition_type,
            OpportunityStageHistory.TransitionType.REOPENED,
        )
        self.assertEqual(
            latest_history.note,
            "El colegio solicitó retomar la propuesta.",
        )

    def test_won_stage_is_reserved_for_adoption_flow(self):
        opportunity = create_opportunity(
            title="Adopción escolar 2027",
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            created_by=self.admin,
        )

        with self.assertRaises(OpportunityTransitionError):
            transition_opportunity_stage(
                opportunity=opportunity,
                to_stage=self.won_stage,
                changed_by=self.advisor,
                note="Colegio confirma adopción.",
            )
