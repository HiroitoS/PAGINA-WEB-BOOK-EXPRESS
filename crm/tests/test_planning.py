from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from crm.models import (
    Campaign,
    CommercialTeam,
    CommercialTeamMembership,
    CRMWorkItemLink,
    Pipeline,
    PipelineStage,
    School,
)
from crm.services import (
    CRMPlanningError,
    create_opportunity,
    create_opportunity_event,
    create_opportunity_reminder,
    create_opportunity_task,
    transition_opportunity_stage,
)
from notifications.models import Notification
from workspaces.models import Task


User = get_user_model()


class CRMPlanningTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="crm-planning-admin",
            email="admin@example.com",
            password="test-password",
        )
        self.advisor = User.objects.create_user(
            username="crm-planning-advisor",
            password="test-password",
        )
        self.outsider = User.objects.create_user(
            username="crm-planning-outsider",
            password="test-password",
        )

        self.team = CommercialTeam.objects.create(
            code="CRM-PLAN-TEAM",
            name="Equipo comercial de prueba",
            created_by=self.admin,
        )
        CommercialTeamMembership.objects.create(
            team=self.team,
            user=self.advisor,
            role=CommercialTeamMembership.Role.ADVISOR,
            created_by=self.admin,
        )

        self.school = School.objects.create(
            name="Colegio planificación CRM",
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )
        self.campaign = Campaign.objects.create(
            code="CRM-PLAN-2027",
            name="Campaña CRM 2027",
            year=2027,
            status=Campaign.Status.ACTIVE,
            created_by=self.admin,
        )
        self.pipeline = Pipeline.objects.create(
            code="CRM-PLAN-PIPE",
            name="Pipeline planificación",
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
        self.lost_stage = PipelineStage.objects.create(
            pipeline=self.pipeline,
            code="no_concretada",
            name="No concretada",
            order=60,
            category=PipelineStage.Category.LOST,
            created_by=self.admin,
        )

        self.opportunity = create_opportunity(
            title="Oportunidad de planificación",
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            created_by=self.admin,
        )

    def test_task_defaults_to_opportunity_owner_and_creates_link(self):
        with self.captureOnCommitCallbacks(execute=True):
            task = create_opportunity_task(
                opportunity=self.opportunity,
                actor=self.admin,
                title="Preparar propuesta comercial",
                due_at=timezone.now() + timedelta(days=1),
            )

        self.assertEqual(task.assigned_to, self.advisor)
        self.assertEqual(task.task_type, "school")
        self.assertTrue(
            CRMWorkItemLink.objects.filter(
                opportunity=self.opportunity,
                task=task,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.advisor,
                event_type="workspace.task_assigned",
                source_id=str(task.id),
            ).exists()
        )

    def test_event_is_created_and_linked_to_opportunity(self):
        event = create_opportunity_event(
            opportunity=self.opportunity,
            actor=self.admin,
            title="Visita al colegio",
            start_at=timezone.now() + timedelta(days=2),
            location="Colegio de prueba",
        )

        self.assertEqual(event.assigned_to, self.advisor)
        self.assertEqual(event.event_type, "visit")
        self.assertTrue(
            CRMWorkItemLink.objects.filter(
                opportunity=self.opportunity,
                event=event,
            ).exists()
        )

    def test_reminder_can_be_attached_to_linked_task(self):
        task = create_opportunity_task(
            opportunity=self.opportunity,
            actor=self.admin,
            title="Enviar propuesta",
        )

        reminder = create_opportunity_reminder(
            opportunity=self.opportunity,
            actor=self.admin,
            title="Recordar envío",
            remind_at=timezone.now() + timedelta(hours=4),
            task=task,
        )

        self.assertEqual(reminder.user, self.advisor)
        self.assertEqual(reminder.task, task)
        self.assertTrue(
            CRMWorkItemLink.objects.filter(
                opportunity=self.opportunity,
                reminder=reminder,
            ).exists()
        )

    def test_reminder_rejects_task_from_another_opportunity(self):
        other_opportunity = create_opportunity(
            title="Otra oportunidad",
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            created_by=self.admin,
        )
        other_task = create_opportunity_task(
            opportunity=other_opportunity,
            actor=self.admin,
            title="Tarea de otra oportunidad",
        )

        with self.assertRaises(CRMPlanningError):
            create_opportunity_reminder(
                opportunity=self.opportunity,
                actor=self.admin,
                title="Recordatorio inválido",
                remind_at=timezone.now() + timedelta(hours=2),
                task=other_task,
            )

    def test_assignee_outside_commercial_team_is_rejected(self):
        with self.assertRaises(CRMPlanningError):
            create_opportunity_task(
                opportunity=self.opportunity,
                actor=self.admin,
                assigned_to=self.outsider,
                title="Tarea fuera de equipo",
            )

    def test_closed_opportunity_rejects_new_planning(self):
        closed = transition_opportunity_stage(
            opportunity=self.opportunity,
            to_stage=self.lost_stage,
            changed_by=self.admin,
            note="No se concretó la oportunidad.",
        )

        with self.assertRaises(CRMPlanningError):
            create_opportunity_task(
                opportunity=closed,
                actor=self.admin,
                title="No debe crearse",
            )

        self.assertFalse(
            Task.objects.filter(title="No debe crearse").exists()
        )
