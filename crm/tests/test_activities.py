from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from crm.models import (
    Campaign,
    CommercialActivity,
    CommercialTeam,
    CommercialTeamMembership,
    CRMWorkItemLink,
    Pipeline,
    PipelineStage,
    School,
    SchoolContact,
)
from crm.selectors import (
    commercial_activities_for_opportunity,
    commercial_activities_for_school,
    work_items_for_opportunity,
)
from crm.services import (
    CommercialActivityError,
    CRMWorkItemLinkError,
    create_opportunity,
    create_opportunity_task,
    link_work_item_to_opportunity,
    link_work_item_to_school,
    record_commercial_activity,
    transition_opportunity_stage,
)
from workspaces.models import CalendarEvent, Reminder, Task


User = get_user_model()


class CRMActivityAndWorkItemTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="crm-admin-activity",
            password="test-password",
        )
        self.advisor = User.objects.create_user(
            username="crm-advisor-activity",
            password="test-password",
        )
        self.team = CommercialTeam.objects.create(
            code="CRM-ACTIVITY-TEAM",
            name="Equipo CRM actividad",
            created_by=self.admin,
        )
        CommercialTeamMembership.objects.create(
            team=self.team,
            user=self.advisor,
            role=CommercialTeamMembership.Role.ADVISOR,
            created_by=self.admin,
        )
        self.school = School.objects.create(
            name="Colegio Actividad CRM",
            team=self.team,
            owner=self.advisor,
            created_by=self.admin,
        )
        self.contact = SchoolContact.objects.create(
            school=self.school,
            full_name="Directora CRM",
            position="Directora",
            is_primary=True,
            created_by=self.admin,
        )
        self.other_school = School.objects.create(
            name="Otro Colegio CRM",
            created_by=self.admin,
        )
        self.other_contact = SchoolContact.objects.create(
            school=self.other_school,
            full_name="Otro contacto",
            created_by=self.admin,
        )
        self.campaign = Campaign.objects.create(
            code="CRM-ACTIVITY-2027",
            name="Campaña CRM actividad 2027",
            year=2027,
            status=Campaign.Status.ACTIVE,
            created_by=self.admin,
        )
        self.pipeline = Pipeline.objects.create(
            code="CRM-ACTIVITY-PIPE",
            name="Pipeline CRM actividad",
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
            title="Oportunidad actividad",
            school=self.school,
            campaign=self.campaign,
            pipeline=self.pipeline,
            created_by=self.admin,
            primary_contact=self.contact,
        )

    def test_record_activity_updates_last_activity_at(self):
        occurred_at = timezone.now() - timedelta(hours=1)

        activity = record_commercial_activity(
            opportunity=self.opportunity,
            activity_type=CommercialActivity.ActivityType.VISIT,
            summary="Visita al colegio",
            result="La directora solicitó revisar la propuesta.",
            performed_by=self.advisor,
            created_by=self.advisor,
            contact=self.contact,
            occurred_at=occurred_at,
        )

        self.opportunity.refresh_from_db()

        self.assertEqual(activity.school, self.school)
        self.assertEqual(activity.opportunity, self.opportunity)
        self.assertEqual(
            self.opportunity.last_activity_at,
            occurred_at,
        )

    def test_activity_rejects_future_occurred_at(self):
        with self.assertRaises(CommercialActivityError):
            record_commercial_activity(
                opportunity=self.opportunity,
                activity_type=CommercialActivity.ActivityType.PRESENTATION,
                summary="Presentación futura",
                result="La presentación aún no se ha realizado.",
                performed_by=self.advisor,
                created_by=self.advisor,
                contact=self.contact,
                occurred_at=timezone.now() + timedelta(days=1),
            )

        self.opportunity.refresh_from_db()
        self.assertIsNone(self.opportunity.last_activity_at)
    def test_activity_can_be_registered_before_opportunity(self):
        activity = record_commercial_activity(
            school=self.school,
            activity_type=CommercialActivity.ActivityType.CALL,
            summary="Primer contacto",
            result="La directora acepta recibir información.",
            performed_by=self.advisor,
            created_by=self.advisor,
            contact=self.contact,
        )

        self.assertEqual(activity.school, self.school)
        self.assertEqual(activity.contact, self.contact)
        self.assertIsNone(activity.opportunity)

    def test_activity_rejects_contact_from_another_school(self):
        with self.assertRaises(CommercialActivityError):
            record_commercial_activity(
                school=self.school,
                activity_type=CommercialActivity.ActivityType.CALL,
                summary="Llamada",
                result="Se conversó con el contacto.",
                performed_by=self.advisor,
                created_by=self.advisor,
                contact=self.other_contact,
            )

    def test_activity_cannot_be_added_to_closed_opportunity(self):
        closed = transition_opportunity_stage(
            opportunity=self.opportunity,
            to_stage=self.lost_stage,
            changed_by=self.advisor,
            note="El colegio no continuará este año.",
        )

        with self.assertRaises(CommercialActivityError):
            record_commercial_activity(
                opportunity=closed,
                activity_type=CommercialActivity.ActivityType.CALL,
                summary="Llamada posterior",
                result="Intento posterior al cierre.",
                performed_by=self.advisor,
                created_by=self.advisor,
            )

    def test_activity_selector_uses_single_query(self):
        for index in range(3):
            record_commercial_activity(
                opportunity=self.opportunity,
                performed_by=self.advisor,
                activity_type=CommercialActivity.ActivityType.FOLLOW_UP,
                summary=f"Seguimiento {index}",
                result="Resultado de prueba.",
                created_by=self.advisor,
            )

        with self.assertNumQueries(1):
            activities = list(
                commercial_activities_for_opportunity(
                    self.opportunity
                )
            )
            for activity in activities:
                _ = activity.school.name
                _ = activity.performed_by.username
                _ = activity.created_by.username

        self.assertEqual(len(activities), 3)

    def test_school_activity_selector_includes_pre_opportunity_activity(self):
        record_commercial_activity(
            school=self.school,
            performed_by=self.advisor,
            activity_type=CommercialActivity.ActivityType.WHATSAPP,
            summary="Primer WhatsApp",
            result="Contacto inicial registrado.",
            created_by=self.advisor,
        )

        activities = list(
            commercial_activities_for_school(self.school)
        )

        self.assertEqual(len(activities), 1)
        self.assertIsNone(activities[0].opportunity)

    def test_crm_next_task_retains_school_opportunity_origin_and_reminder(self):
        activity = record_commercial_activity(
            opportunity=self.opportunity,
            activity_type=CommercialActivity.ActivityType.VISIT,
            summary="Presentación de textos al colegio",
            result="Solicitaron una propuesta educativa.",
            performed_by=self.advisor,
            created_by=self.advisor,
            contact=self.contact,
        )
        remind_at = timezone.now() + timedelta(hours=4)

        task = create_opportunity_task(
            opportunity=self.opportunity,
            actor=self.advisor,
            title="Enviar propuesta al colegio",
            reminder_at=remind_at,
            origin_activity=activity,
            commercial_action_type=CommercialActivity.ActivityType.FOLLOW_UP,
        )

        link = CRMWorkItemLink.objects.select_related(
            "school", "opportunity", "origin_activity", "task"
        ).get(task=task)
        reminder = Reminder.objects.get(task=task, source="task")

        self.assertEqual(link.school_id, self.school.id)
        self.assertEqual(link.opportunity_id, self.opportunity.id)
        self.assertEqual(link.origin_activity_id, activity.id)
        self.assertEqual(link.created_by_id, self.advisor.id)
        self.assertEqual(link.commercial_action_type, "follow_up")
        self.assertEqual(task.assigned_to_id, self.advisor.id)
        self.assertEqual(reminder.user_id, self.advisor.id)
        self.assertEqual(reminder.remind_at, task.reminder_at)
        self.assertEqual(reminder.status, "pending")
        self.assertEqual(
            CRMWorkItemLink.objects.filter(task=task).count(), 1
        )
        self.assertFalse(
            CRMWorkItemLink.objects.filter(reminder=reminder).exists()
        )

    def test_private_crm_work_item_is_not_exposed_to_other_users(self):
        other_user = User.objects.create_user(
            username="crm-private-task-observer",
            password="test-password",
        )
        task = Task.objects.create(
            title="Seguimiento reservado",
            created_by=self.admin,
            assigned_to=self.advisor,
            is_private=True,
        )
        reminder = Reminder.objects.create(
            title="Aviso privado de tarea",
            task=task,
            created_by=self.admin,
            user=self.advisor,
            remind_at=timezone.now() + timedelta(hours=3),
            source="manual",
        )
        task_link = link_work_item_to_opportunity(
            opportunity=self.opportunity,
            created_by=self.admin,
            task=task,
        )
        reminder_link = link_work_item_to_opportunity(
            opportunity=self.opportunity,
            created_by=self.admin,
            reminder=reminder,
        )

        visible_to_other = work_items_for_opportunity(
            self.opportunity,
            user=other_user,
        )
        self.assertFalse(
            visible_to_other.filter(pk__in=[task_link.pk, reminder_link.pk]).exists()
        )

        for allowed_user in [self.admin, self.advisor]:
            ids = set(
                work_items_for_opportunity(
                    self.opportunity,
                    user=allowed_user,
                ).values_list("id", flat=True)
            )
            self.assertIn(task_link.pk, ids)
            self.assertIn(reminder_link.pk, ids)

    def test_crm_linked_task_cannot_be_deleted_or_cascade(self):
        task = Task.objects.create(
            title="Preparar propuesta para adopción",
            created_by=self.admin,
            assigned_to=self.advisor,
        )
        link = link_work_item_to_opportunity(
            opportunity=self.opportunity,
            created_by=self.admin,
            task=task,
        )

        workspace_permission = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="use_workspace",
        )
        self.admin.user_permissions.add(workspace_permission)
        self.client.force_login(self.admin)

        response = self.client.delete(f"/api/admin/tasks/{task.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Task.objects.filter(pk=task.id).exists())
        self.assertTrue(CRMWorkItemLink.objects.filter(pk=link.pk).exists())

        with self.assertRaises(ProtectedError):
            task.delete()
        self.assertTrue(CRMWorkItemLink.objects.filter(pk=link.pk).exists())

    def test_link_accepts_exactly_one_workspace_item(self):
        task = Task.objects.create(
            title="Preparar propuesta",
            created_by=self.admin,
            assigned_to=self.advisor,
        )
        event = CalendarEvent.objects.create(
            title="Visita al colegio",
            created_by=self.admin,
            assigned_to=self.advisor,
            start_at=timezone.now() + timedelta(days=1),
        )

        with self.assertRaises(CRMWorkItemLinkError):
            link_work_item_to_opportunity(
                opportunity=self.opportunity,
                created_by=self.admin,
                task=task,
                event=event,
            )

    def test_task_link_is_idempotent_for_same_opportunity(self):
        task = Task.objects.create(
            title="Enviar propuesta",
            created_by=self.admin,
            assigned_to=self.advisor,
        )

        first = link_work_item_to_opportunity(
            opportunity=self.opportunity,
            created_by=self.admin,
            task=task,
        )
        second = link_work_item_to_opportunity(
            opportunity=self.opportunity,
            created_by=self.admin,
            task=task,
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.school, self.school)
        self.assertEqual(
            CRMWorkItemLink.objects.filter(task=task).count(),
            1,
        )

    def test_task_can_be_linked_to_school_before_opportunity(self):
        task = Task.objects.create(
            title="Confirmar reunión con dirección",
            created_by=self.admin,
            assigned_to=self.advisor,
        )

        link = link_work_item_to_school(
            school=self.school,
            contact=self.contact,
            created_by=self.admin,
            task=task,
        )

        self.assertEqual(link.school, self.school)
        self.assertEqual(link.contact, self.contact)
        self.assertIsNone(link.opportunity)

    def test_school_task_rejects_contact_from_another_school(self):
        task = Task.objects.create(
            title="Tarea inválida",
            created_by=self.admin,
            assigned_to=self.advisor,
        )

        with self.assertRaises(CRMWorkItemLinkError):
            link_work_item_to_school(
                school=self.school,
                contact=self.other_contact,
                created_by=self.admin,
                task=task,
            )

    def test_database_rejects_more_than_one_workspace_item(self):
        task = Task.objects.create(
            title="Tarea inválida",
            created_by=self.admin,
            assigned_to=self.advisor,
        )
        reminder = Reminder.objects.create(
            created_by=self.admin,
            user=self.advisor,
            task=task,
            title="Recordatorio inválido",
            remind_at=timezone.now() + timedelta(hours=2),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CRMWorkItemLink.objects.create(
                    school=self.school,
                    opportunity=self.opportunity,
                    task=task,
                    reminder=reminder,
                    created_by=self.admin,
                )
