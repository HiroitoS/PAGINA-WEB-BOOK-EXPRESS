from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from notifications.models import Notification

from .models import Reminder
from .reminder_alerts import (
    resolve_reminder_alert_notifications,
    sync_reminder_alerts_for_user,
)


class ReminderAlertSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="asesor_recordatorios",
            password="PruebaSegura123",
        )
        self.other_user = User.objects.create_user(
            username="otro_asesor_recordatorios",
            password="PruebaSegura123",
        )
        self.now = timezone.now().replace(microsecond=0)

    def create_reminder(
        self,
        *,
        offset,
        user=None,
        status="pending",
        title="Seguimiento de prueba",
    ):
        return Reminder.objects.create(
            created_by=self.user,
            user=user or self.user,
            title=title,
            remind_at=self.now + offset,
            status=status,
        )

    def test_upcoming_alert_is_idempotent(self):
        reminder = self.create_reminder(
            offset=timedelta(minutes=20),
        )

        sync_reminder_alerts_for_user(
            self.user,
            now=self.now,
        )
        sync_reminder_alerts_for_user(
            self.user,
            now=self.now,
        )

        notifications = Notification.objects.filter(
            recipient=self.user,
            event_type="workspace.reminder_upcoming",
            source_id=str(reminder.id),
        )

        self.assertEqual(notifications.count(), 1)
        self.assertFalse(notifications.get().is_resolved)

    def test_due_alert_replaces_upcoming_alert(self):
        reminder = self.create_reminder(
            offset=timedelta(minutes=5),
        )

        sync_reminder_alerts_for_user(
            self.user,
            now=self.now,
        )
        sync_reminder_alerts_for_user(
            self.user,
            now=self.now + timedelta(minutes=6),
        )

        upcoming = Notification.objects.get(
            recipient=self.user,
            event_type="workspace.reminder_upcoming",
            source_id=str(reminder.id),
        )
        due = Notification.objects.get(
            recipient=self.user,
            event_type="workspace.reminder_due",
            source_id=str(reminder.id),
        )

        self.assertTrue(upcoming.is_resolved)
        self.assertFalse(due.is_resolved)
        self.assertEqual(due.severity, "warning")

    def test_recent_overdue_reminder_creates_single_alert(self):
        reminder = self.create_reminder(
            offset=-timedelta(hours=2),
        )

        sync_reminder_alerts_for_user(
            self.user,
            now=self.now,
        )

        notification = Notification.objects.get(
            recipient=self.user,
            event_type="workspace.reminder_overdue",
            source_id=str(reminder.id),
        )

        self.assertEqual(notification.severity, "error")
        self.assertFalse(notification.is_resolved)

    def test_old_overdue_reminder_does_not_create_offline_flood(self):
        self.create_reminder(
            offset=-timedelta(days=2),
        )

        sync_reminder_alerts_for_user(
            self.user,
            now=self.now,
        )

        self.assertFalse(
            Notification.objects.filter(
                recipient=self.user,
                event_type__in=[
                    "workspace.reminder_upcoming",
                    "workspace.reminder_due",
                    "workspace.reminder_overdue",
                ],
            ).exists()
        )

    def test_completed_and_other_user_reminders_are_ignored(self):
        self.create_reminder(
            offset=timedelta(minutes=10),
            status="completed",
        )
        self.create_reminder(
            offset=timedelta(minutes=10),
            user=self.other_user,
        )

        sync_reminder_alerts_for_user(
            self.user,
            now=self.now,
        )

        self.assertFalse(
            Notification.objects.filter(
                recipient=self.user,
                event_type__in=[
                    "workspace.reminder_upcoming",
                    "workspace.reminder_due",
                    "workspace.reminder_overdue",
                ],
            ).exists()
        )

    def test_resolve_only_closes_temporary_alerts(self):
        reminder = self.create_reminder(
            offset=timedelta(minutes=10),
        )

        sync_reminder_alerts_for_user(
            self.user,
            now=self.now,
        )

        assignment_notification = Notification.objects.create(
            recipient=self.user,
            title="Recordatorio asignado",
            event_type="workspace.reminder_assigned",
            module="todo",
            source_app="workspaces",
            source_model="Reminder",
            source_id=str(reminder.id),
        )

        updated = resolve_reminder_alert_notifications(reminder)

        self.assertEqual(updated, 1)

        alert = Notification.objects.get(
            recipient=self.user,
            event_type="workspace.reminder_upcoming",
            source_id=str(reminder.id),
        )
        assignment_notification.refresh_from_db()

        self.assertTrue(alert.is_resolved)
        self.assertFalse(assignment_notification.is_resolved)
