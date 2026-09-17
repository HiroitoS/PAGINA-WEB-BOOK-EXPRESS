from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone

from notifications.models import Notification
from workspaces.models import WorkspaceGroup, WorkspaceMembership
from workspaces.services import (
    WorkspaceOperationError,
    create_workspace_event,
    create_workspace_reminder,
    create_workspace_task,
)


User = get_user_model()


class WorkspaceCreationServicesTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="workspace-manager-service",
            password="test-password",
        )
        self.assignee = User.objects.create_user(
            username="workspace-assignee-service",
            password="test-password",
        )
        self.outsider = User.objects.create_user(
            username="workspace-outsider-service",
            password="test-password",
        )

        assign_permission = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="assign_work",
        )
        self.manager.user_permissions.add(assign_permission)

    def test_task_creation_sends_assignment_notification(self):
        with self.captureOnCommitCallbacks(execute=True):
            task = create_workspace_task(
                actor=self.manager,
                assigned_to=self.assignee,
                title="Tarea creada por servicio",
            )

        self.assertEqual(task.assigned_to, self.assignee)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.assignee,
                event_type="workspace.task_assigned",
                source_id=str(task.id),
            ).exists()
        )

    def test_event_rejects_end_before_start(self):
        start_at = timezone.now() + timedelta(days=1)

        with self.assertRaises(WorkspaceOperationError):
            create_workspace_event(
                actor=self.manager,
                assigned_to=self.assignee,
                title="Evento inválido",
                start_at=start_at,
                end_at=start_at - timedelta(hours=1),
            )

    def test_reminder_rejects_task_and_event_together(self):
        task = create_workspace_task(
            actor=self.manager,
            assigned_to=self.assignee,
            title="Tarea",
        )
        event = create_workspace_event(
            actor=self.manager,
            assigned_to=self.assignee,
            title="Evento",
            start_at=timezone.now() + timedelta(days=1),
        )

        with self.assertRaises(WorkspaceOperationError):
            create_workspace_reminder(
                actor=self.manager,
                user=self.assignee,
                title="Recordatorio inválido",
                remind_at=timezone.now() + timedelta(hours=1),
                task=task,
                event=event,
            )

    def test_user_without_assignment_permission_cannot_assign_other_user(self):
        with self.assertRaises(WorkspaceOperationError):
            create_workspace_task(
                actor=self.outsider,
                assigned_to=self.assignee,
                title="Asignación no permitida",
            )

    def test_group_creator_can_assign_inside_own_group(self):
        group = WorkspaceGroup.objects.create(
            name="Grupo de servicio",
            created_by=self.outsider,
        )
        WorkspaceMembership.objects.create(
            group=group,
            user=self.outsider,
            role="owner",
            is_active=True,
        )

        task = create_workspace_task(
            actor=self.outsider,
            assigned_to=self.assignee,
            group=group,
            title="Tarea de grupo",
        )

        self.assertEqual(task.group, group)
        self.assertEqual(task.assigned_to, self.assignee)
