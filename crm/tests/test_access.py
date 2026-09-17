from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from crm.models import (
    Campaign,
    CommercialTeam,
    CommercialTeamMembership,
    Opportunity,
    Pipeline,
    PipelineStage,
    School,
)
from crm.selectors import (
    visible_opportunities_queryset,
    visible_schools_queryset,
)


User = get_user_model()


def grant_permission(user, codename):
    permission = Permission.objects.get(
        content_type__app_label="crm",
        codename=codename,
    )
    user.user_permissions.add(permission)


class CRMAccessScopeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="crm-access-admin",
            email="admin@example.com",
            password="test-password",
        )
        self.supervisor = User.objects.create_user(
            username="crm-access-supervisor",
            password="test-password",
        )
        self.advisor = User.objects.create_user(
            username="crm-access-advisor",
            password="test-password",
        )
        self.other_advisor = User.objects.create_user(
            username="crm-access-other",
            password="test-password",
        )
        self.no_access = User.objects.create_user(
            username="crm-access-none",
            password="test-password",
        )

        for user in (
            self.supervisor,
            self.advisor,
            self.other_advisor,
        ):
            grant_permission(user, "view_crm")

        grant_permission(self.supervisor, "supervise_crm")

        self.team = CommercialTeam.objects.create(
            code="ACCESS-TEAM",
            name="Equipo acceso CRM",
            created_by=self.admin,
        )
        self.other_team = CommercialTeam.objects.create(
            code="ACCESS-OTHER",
            name="Otro equipo CRM",
            created_by=self.admin,
        )

        CommercialTeamMembership.objects.create(
            team=self.team,
            user=self.supervisor,
            role=CommercialTeamMembership.Role.SUPERVISOR,
            created_by=self.admin,
        )
        CommercialTeamMembership.objects.create(
            team=self.team,
            user=self.advisor,
            role=CommercialTeamMembership.Role.ADVISOR,
            created_by=self.admin,
        )
        CommercialTeamMembership.objects.create(
            team=self.other_team,
            user=self.other_advisor,
            role=CommercialTeamMembership.Role.ADVISOR,
            created_by=self.admin,
        )

        self.school_advisor = School.objects.create(
            name="Colegio asesor",
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )
        self.school_other = School.objects.create(
            name="Colegio otro asesor",
            team=self.other_team,
            owner=self.other_advisor,
            created_by=self.admin,
        )

        self.campaign = Campaign.objects.create(
            code="ACCESS-2027",
            name="Campaña acceso 2027",
            year=2027,
            status=Campaign.Status.ACTIVE,
            created_by=self.admin,
        )
        self.pipeline = Pipeline.objects.create(
            code="ACCESS-PIPE",
            name="Pipeline acceso",
            is_default=True,
            created_by=self.admin,
        )
        self.stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="por_contactar",
            name="Por contactar",
            order=10,
            category=PipelineStage.Category.OPEN,
            is_initial=True,
            created_by=self.admin,
        )

        self.opportunity_advisor = Opportunity.objects.create(
            title="Oportunidad asesor",
            school=self.school_advisor,
            campaign=self.campaign,
            pipeline=self.pipeline,
            stage=self.stage,
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )
        self.opportunity_other = Opportunity.objects.create(
            title="Oportunidad otro asesor",
            school=self.school_other,
            campaign=self.campaign,
            pipeline=self.pipeline,
            stage=self.stage,
            team=self.other_team,
            owner=self.other_advisor,
            created_by=self.admin,
        )

    def test_admin_can_see_all_schools_and_opportunities(self):
        self.assertEqual(
            visible_schools_queryset(self.admin).count(),
            2,
        )
        self.assertEqual(
            visible_opportunities_queryset(self.admin).count(),
            2,
        )

    def test_advisor_only_sees_owned_scope(self):
        self.assertEqual(
            list(
                visible_schools_queryset(self.advisor)
                .values_list("id", flat=True)
            ),
            [self.school_advisor.id],
        )
        self.assertEqual(
            list(
                visible_opportunities_queryset(self.advisor)
                .values_list("id", flat=True)
            ),
            [self.opportunity_advisor.id],
        )

    def test_supervisor_sees_only_supervised_team_scope(self):
        school_ids = set(
            visible_schools_queryset(self.supervisor)
            .values_list("id", flat=True)
        )
        opportunity_ids = set(
            visible_opportunities_queryset(self.supervisor)
            .values_list("id", flat=True)
        )

        self.assertEqual(
            school_ids,
            {self.school_advisor.id},
        )
        self.assertEqual(
            opportunity_ids,
            {self.opportunity_advisor.id},
        )

    def test_user_without_view_crm_sees_nothing(self):
        self.assertFalse(
            visible_schools_queryset(self.no_access).exists()
        )
        self.assertFalse(
            visible_opportunities_queryset(self.no_access).exists()
        )
