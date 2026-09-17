from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from crm.models import (
    Campaign,
    CommercialTeam,
    CommercialTeamMembership,
    CRMWorkItemLink,
    Opportunity,
    Pipeline,
    PipelineStage,
    School,
)


User = get_user_model()


def grant_permission(user, codename):
    permission = Permission.objects.get(content_type__app_label="crm", codename=codename)
    user.user_permissions.add(permission)


class CRMApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(username="crm-api-admin", email="admin@example.com", password="test-password")
        self.supervisor = User.objects.create_user(username="crm-api-supervisor", password="test-password")
        self.advisor = User.objects.create_user(username="crm-api-advisor", password="test-password")
        self.other_advisor = User.objects.create_user(username="crm-api-other", password="test-password")
        self.no_access = User.objects.create_user(username="crm-api-no-access", password="test-password")
        for user in (self.supervisor, self.advisor, self.other_advisor):
            grant_permission(user, "view_crm")
            grant_permission(user, "manage_schools")
            grant_permission(user, "manage_own_opportunities")
        grant_permission(self.supervisor, "supervise_crm")
        grant_permission(self.supervisor, "assign_schools")
        grant_permission(self.supervisor, "assign_opportunities")

        self.team = CommercialTeam.objects.create(code="API-TEAM", name="Equipo API", created_by=self.admin)
        self.other_team = CommercialTeam.objects.create(code="API-OTHER", name="Otro equipo API", created_by=self.admin)
        CommercialTeamMembership.objects.create(team=self.team, user=self.supervisor, role=CommercialTeamMembership.Role.SUPERVISOR, created_by=self.admin)
        CommercialTeamMembership.objects.create(team=self.team, user=self.advisor, role=CommercialTeamMembership.Role.ADVISOR, created_by=self.admin)
        CommercialTeamMembership.objects.create(team=self.other_team, user=self.other_advisor, role=CommercialTeamMembership.Role.ADVISOR, created_by=self.admin)

        self.school = School.objects.create(name="Colegio API", team=self.team, owner=self.advisor, created_by=self.admin)
        self.other_school = School.objects.create(name="Otro Colegio API", team=self.other_team, owner=self.other_advisor, created_by=self.admin)
        self.campaign = Campaign.objects.create(code="API-2027", name="Campaña API 2027", year=2027, status=Campaign.Status.ACTIVE, created_by=self.admin)
        self.pipeline = Pipeline.objects.create(code="API-PIPE", name="Pipeline API", is_default=True, created_by=self.admin)
        self.initial_stage = PipelineStage.objects.create(pipeline=self.pipeline, code="por_contactar", name="Por contactar", order=10, category=PipelineStage.Category.OPEN, is_initial=True, created_by=self.admin)
        self.follow_up_stage = PipelineStage.objects.create(pipeline=self.pipeline, code="seguimiento", name="Seguimiento", order=20, category=PipelineStage.Category.OPEN, created_by=self.admin)
        self.lost_stage = PipelineStage.objects.create(pipeline=self.pipeline, code="no_concretada", name="No concretada", order=90, category=PipelineStage.Category.LOST, created_by=self.admin)
        self.opportunity = Opportunity.objects.create(title="Oportunidad API", school=self.school, campaign=self.campaign, pipeline=self.pipeline, stage=self.initial_stage, team=self.team, owner=self.advisor, created_by=self.admin)
        self.other_opportunity = Opportunity.objects.create(title="Otra oportunidad API", school=self.other_school, campaign=self.campaign, pipeline=self.pipeline, stage=self.initial_stage, team=self.other_team, owner=self.other_advisor, created_by=self.admin)

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_user_without_crm_permission_is_denied(self):
        self.authenticate(self.no_access)
        self.assertEqual(self.client.get(reverse("crm:school-list")).status_code, 403)

    def test_advisor_only_lists_own_scope(self):
        self.authenticate(self.advisor)
        response = self.client.get(reverse("crm:school-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.school.id)
        response = self.client.get(reverse("crm:opportunity-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.opportunity.id)

    def test_supervisor_sees_supervised_team_only(self):
        self.authenticate(self.supervisor)
        response = self.client.get(reverse("crm:opportunity-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.data["results"]}, {self.opportunity.id})

    def test_summary_respects_visible_scope(self):
        self.authenticate(self.advisor)
        response = self.client.get(reverse("crm:summary"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["schools"], 1)
        self.assertEqual(response.data["open_opportunities"], 1)

    def test_advisor_can_register_commercial_activity(self):
        self.authenticate(self.advisor)
        response = self.client.post(
            reverse("crm:opportunity-activities", args=[self.opportunity.id]),
            {"activity_type": "call", "summary": "Llamada a dirección", "result": "Solicitaron nueva visita."},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.opportunity.refresh_from_db()
        self.assertIsNotNone(self.opportunity.last_activity_at)

    def test_advisor_can_move_own_opportunity_to_open_stage(self):
        self.authenticate(self.advisor)
        response = self.client.post(
            reverse("crm:opportunity-change-stage", args=[self.opportunity.id]),
            {"stage": self.follow_up_stage.id, "note": "Se realizó primer contacto."},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.stage_id, self.follow_up_stage.id)

    def test_lost_stage_requires_reason(self):
        self.authenticate(self.advisor)
        response = self.client.post(
            reverse("crm:opportunity-change-stage", args=[self.opportunity.id]),
            {"stage": self.lost_stage.id, "note": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_advisor_can_create_task_linked_to_opportunity(self):
        self.authenticate(self.advisor)
        response = self.client.post(
            reverse("crm:opportunity-create-task", args=[self.opportunity.id]),
            {"title": "Preparar propuesta", "due_at": (timezone.now() + timedelta(days=1)).isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(CRMWorkItemLink.objects.filter(opportunity=self.opportunity, task_id=response.data["id"]).exists())

    def test_school_delete_is_not_exposed(self):
        self.authenticate(self.admin)
        response = self.client.delete(reverse("crm:school-detail", args=[self.school.id]))
        self.assertEqual(response.status_code, 405)
