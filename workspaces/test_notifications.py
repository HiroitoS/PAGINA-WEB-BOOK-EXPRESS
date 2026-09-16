from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from notifications.models import Notification

from .models import (
    CalendarEvent,
    Reminder,
    Task,
    TaskComment,
    WorkspaceGroup,
    WorkspaceMembership,
)
from .notification_events import (
    notify_event_assigned,
    notify_group_membership_created,
    notify_reminder_assigned,
    notify_task_assigned,
    notify_task_comment_created,
    resolve_task_notifications,
)


class WorkspaceNotificationEventTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(
            username="coordinador",
            password="PruebaSegura123",
        )
        self.assignee = User.objects.create_user(
            username="asesor",
            password="PruebaSegura123",
        )
        self.creator = User.objects.create_user(
            username="creador",
            password="PruebaSegura123",
        )
        self.group = WorkspaceGroup.objects.create(
            name="Equipo comercial",
            created_by=self.actor,
        )

    def test_task_assignment_notifies_other_user(self):
        task = Task.objects.create(
            title="Visitar colegio",
            created_by=self.actor,
            assigned_to=self.assignee,
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_task_assigned(task, actor=self.actor)

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.assignee,
                event_type="workspace.task_assigned",
                source_id=str(task.id),
            ).exists()
        )

    def test_self_assignment_does_not_notify(self):
        task = Task.objects.create(
            title="Tarea propia",
            created_by=self.actor,
            assigned_to=self.actor,
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_task_assigned(task, actor=self.actor)

        self.assertFalse(
            Notification.objects.filter(
                recipient=self.actor,
                event_type="workspace.task_assigned",
            ).exists()
        )

    def test_task_comment_notifies_creator_and_assignee(self):
        task = Task.objects.create(
            title="Seguimiento colegio",
            created_by=self.creator,
            assigned_to=self.assignee,
        )
        comment = TaskComment.objects.create(
            task=task,
            user=self.actor,
            action_type="comment",
            comment="Se realizó la llamada.",
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_task_comment_created(
                comment,
                actor=self.actor,
            )

        recipients = set(
            Notification.objects.filter(
                event_type="workspace.task_comment_added",
                source_id=str(comment.id),
            ).values_list("recipient_id", flat=True)
        )

        self.assertEqual(
            recipients,
            {self.creator.id, self.assignee.id},
        )

    def test_group_membership_notifies_new_member(self):
        membership = WorkspaceMembership.objects.create(
            group=self.group,
            user=self.assignee,
            role="member",
            is_active=True,
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_group_membership_created(
                membership,
                actor=self.actor,
            )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.assignee,
                event_type="workspace.group_member_added",
                source_id=str(membership.id),
            ).exists()
        )

    def test_event_and_reminder_assignment_notify(self):
        event = CalendarEvent.objects.create(
            title="Reunión comercial",
            created_by=self.actor,
            assigned_to=self.assignee,
            start_at=timezone.now(),
        )
        reminder = Reminder.objects.create(
            created_by=self.actor,
            user=self.assignee,
            title="Preparar propuesta",
            remind_at=timezone.now(),
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_event_assigned(
                event,
                actor=self.actor,
            )
            notify_reminder_assigned(
                reminder,
                actor=self.actor,
            )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.assignee,
                event_type="workspace.event_assigned",
                source_id=str(event.id),
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.assignee,
                event_type="workspace.reminder_assigned",
                source_id=str(reminder.id),
            ).exists()
        )


class WorkspaceNotificationLifecycleTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(
            username="jefe_lifecycle",
            password="PruebaSegura123",
        )
        self.assignee = User.objects.create_user(
            username="asesor_lifecycle",
            password="PruebaSegura123",
        )

    def test_task_assignment_uses_deep_link(self):
        task = Task.objects.create(
            title="Visita con deep link",
            created_by=self.actor,
            assigned_to=self.assignee,
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_task_assigned(task, actor=self.actor)

        notification = Notification.objects.get(
            recipient=self.assignee,
            event_type="workspace.task_assigned",
        )

        self.assertEqual(
            notification.link,
            f"/admin/workspace/tasks?task={task.id}",
        )

    def test_task_resolution_closes_related_notifications(self):
        task = Task.objects.create(
            title="Tarea que se completa",
            created_by=self.actor,
            assigned_to=self.assignee,
        )

        notification = Notification.objects.create(
            recipient=self.assignee,
            title="Nueva tarea asignada",
            event_type="workspace.task_assigned",
            module="todo",
            source_app="workspaces",
            source_model="Task",
            source_id=str(task.id),
            metadata={"task_id": task.id},
        )

        with self.captureOnCommitCallbacks(execute=True):
            resolve_task_notifications(task)

        notification.refresh_from_db()
        self.assertTrue(notification.is_resolved)
        self.assertIsNotNone(notification.resolved_at)
