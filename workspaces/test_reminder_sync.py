from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from workspaces.models import (
    Reminder,
    Task,
    WorkspaceGroup,
    WorkspaceMembership,
)


User = get_user_model()


class ReminderSynchronizationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reminder-owner",
            password="test-password",
        )
        use_workspace = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="use_workspace",
        )
        self.user.user_permissions.add(use_workspace)

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def create_task_with_reminder(self):
        remind_at = timezone.now() + timedelta(hours=2)
        response = self.client.post(
            "/api/admin/tasks/",
            {
                "title": "Llamar al colegio",
                "reminder_at": remind_at.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

        task = Task.objects.get(pk=response.data["id"])
        reminder = Reminder.objects.get(
            task=task,
            source="task",
        )
        return task, reminder

    def test_task_reminder_creates_canonical_reminder(self):
        task, reminder = self.create_task_with_reminder()

        self.assertEqual(reminder.user, self.user)
        self.assertEqual(reminder.title, task.title)
        self.assertEqual(reminder.remind_at, task.reminder_at)
        self.assertEqual(reminder.status, "pending")

    def test_updating_task_reminder_reuses_same_canonical_record(self):
        task, reminder = self.create_task_with_reminder()
        new_remind_at = timezone.now() + timedelta(days=1)

        response = self.client.patch(
            f"/api/admin/tasks/{task.id}/",
            {
                "reminder_at": new_remind_at.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)

        task.refresh_from_db()
        reminder.refresh_from_db()

        self.assertEqual(
            Reminder.objects.filter(
                task=task,
                source="task",
            ).count(),
            1,
        )
        self.assertEqual(reminder.remind_at, task.reminder_at)

    def test_editing_canonical_reminder_updates_task_compatibility_field(self):
        task, reminder = self.create_task_with_reminder()
        new_remind_at = timezone.now() + timedelta(days=2)

        response = self.client.patch(
            f"/api/admin/reminders/{reminder.id}/",
            {
                "remind_at": new_remind_at.isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)

        task.refresh_from_db()
        reminder.refresh_from_db()

        self.assertEqual(task.reminder_at, reminder.remind_at)

    def test_clearing_task_reminder_removes_only_canonical_record(self):
        task, reminder = self.create_task_with_reminder()

        manual_reminder = Reminder.objects.create(
            created_by=self.user,
            user=self.user,
            task=task,
            title="Seguimiento adicional",
            remind_at=timezone.now() + timedelta(days=3),
            source="manual",
        )

        response = self.client.patch(
            f"/api/admin/tasks/{task.id}/",
            {
                "reminder_at": None,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)

        task.refresh_from_db()

        self.assertIsNone(task.reminder_at)
        self.assertFalse(
            Reminder.objects.filter(pk=reminder.pk).exists()
        )
        self.assertTrue(
            Reminder.objects.filter(pk=manual_reminder.pk).exists()
        )

    def test_completing_task_closes_primary_reminder(self):
        task, reminder = self.create_task_with_reminder()

        response = self.client.post(
            f"/api/admin/tasks/{task.id}/change-status/",
            {
                "status": "completed",
                "note": "Gestión terminada.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)

        task.refresh_from_db()
        reminder.refresh_from_db()

        self.assertIsNone(task.reminder_at)
        self.assertEqual(reminder.status, "completed")
        self.assertIsNotNone(reminder.completed_at)


    def test_editing_task_without_rescheduling_keeps_seen_reminder(self):
        task, reminder = self.create_task_with_reminder()
        reminder.status = "seen"
        reminder.save(update_fields=["status"])

        response = self.client.patch(
            f"/api/admin/tasks/{task.id}/",
            {"title": "Llamar nuevamente al colegio"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, "seen")
        self.assertEqual(reminder.title, "Llamar nuevamente al colegio")

    def test_changing_task_reminder_date_reactivates_seen_reminder(self):
        task, reminder = self.create_task_with_reminder()
        reminder.status = "seen"
        reminder.save(update_fields=["status"])
        new_date = timezone.now() + timedelta(days=4)

        response = self.client.patch(
            f"/api/admin/tasks/{task.id}/",
            {"reminder_at": new_date.isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        reminder.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(reminder.status, "pending")
        self.assertEqual(reminder.remind_at, task.reminder_at)

    def test_dismissed_reminder_survives_unrelated_task_edit(self):
        task, reminder = self.create_task_with_reminder()
        response = self.client.patch(
            f"/api/admin/reminders/{reminder.id}/",
            {"status": "dismissed"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        response = self.client.patch(
            f"/api/admin/tasks/{task.id}/",
            {"title": "Seguimiento actualizado"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        reminder.refresh_from_db()
        self.assertIsNone(task.reminder_at)
        self.assertEqual(reminder.status, "dismissed")

    def test_primary_reminder_cannot_be_reopened_while_task_is_closed(self):
        task, reminder = self.create_task_with_reminder()
        response = self.client.post(
            f"/api/admin/tasks/{task.id}/change-status/",
            {"status": "completed", "note": "Atendido"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        response = self.client.patch(
            f"/api/admin/reminders/{reminder.id}/",
            {"is_completed": False},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        reminder.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(reminder.status, "completed")
        self.assertIsNone(task.reminder_at)

    def test_reopening_task_does_not_reschedule_until_explicitly_requested(self):
        task, reminder = self.create_task_with_reminder()
        self.client.post(
            f"/api/admin/tasks/{task.id}/change-status/",
            {"status": "completed", "note": "Atendido"},
            format="json",
        )
        response = self.client.post(
            f"/api/admin/tasks/{task.id}/reopen/",
            {"reason": "Se necesita otra visita."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        reminder.refresh_from_db()
        self.assertEqual(task.status, "pending")
        self.assertIsNone(task.reminder_at)
        self.assertEqual(reminder.status, "completed")

        next_date = timezone.now() + timedelta(days=5)
        response = self.client.patch(
            f"/api/admin/tasks/{task.id}/",
            {"reminder_at": next_date.isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, "pending")
        self.assertEqual(
            Reminder.objects.filter(task=task, source="task").count(),
            1,
        )

    def test_cannot_attach_reminder_to_another_users_private_task(self):
        outsider = User.objects.create_user(
            username="outside-task-owner",
            password="test-password",
        )
        foreign_task = Task.objects.create(
            title="Tarea de otro asesor",
            created_by=outsider,
            assigned_to=outsider,
        )
        response = self.client.post(
            "/api/admin/reminders/",
            {
                "title": "Aviso de tarea ajena",
                "task": foreign_task.id,
                "remind_at": (timezone.now() + timedelta(days=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(
            Reminder.objects.filter(task=foreign_task).exists()
        )

    def test_cannot_move_primary_reminder_to_another_task(self):
        task, reminder = self.create_task_with_reminder()
        second_task = Task.objects.create(
            title="Otra tarea",
            created_by=self.user,
            assigned_to=self.user,
        )
        response = self.client.patch(
            f"/api/admin/reminders/{reminder.id}/",
            {"task": second_task.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        reminder.refresh_from_db()
        self.assertEqual(reminder.task_id, task.id)



class ReminderVisibilityApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="reminder-team-owner",
            password="test-password",
        )
        self.member_a = User.objects.create_user(
            username="reminder-member-a",
            password="test-password",
        )
        self.member_b = User.objects.create_user(
            username="reminder-member-b",
            password="test-password",
        )

        use_workspace = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="use_workspace",
        )

        for user in [self.owner, self.member_a, self.member_b]:
            user.user_permissions.add(use_workspace)

        self.group = WorkspaceGroup.objects.create(
            name="Equipo Recordatorios",
            created_by=self.owner,
        )

        WorkspaceMembership.objects.create(
            group=self.group,
            user=self.owner,
            role="owner",
            is_active=True,
        )
        WorkspaceMembership.objects.create(
            group=self.group,
            user=self.member_a,
            role="member",
            is_active=True,
        )
        WorkspaceMembership.objects.create(
            group=self.group,
            user=self.member_b,
            role="member",
            is_active=True,
        )

        self.reminder = Reminder.objects.create(
            created_by=self.member_b,
            user=self.member_b,
            group=self.group,
            title="Recordatorio privado de ejecución",
            remind_at=timezone.now() + timedelta(hours=3),
        )

    def test_regular_member_does_not_see_peer_reminder(self):
        client = APIClient()
        client.force_authenticate(self.member_a)

        response = client.get("/api/admin/reminders/")

        self.assertEqual(response.status_code, 200)
        response_items = (
            response.data.get("results", [])
            if isinstance(response.data, dict)
            else response.data
        )
        reminder_ids = [item["id"] for item in response_items]

        self.assertNotIn(self.reminder.id, reminder_ids)

    def test_group_owner_can_supervise_group_reminder(self):
        client = APIClient()
        client.force_authenticate(self.owner)

        response = client.get("/api/admin/reminders/")

        self.assertEqual(response.status_code, 200)
        response_items = (
            response.data.get("results", [])
            if isinstance(response.data, dict)
            else response.data
        )
        reminder_ids = [item["id"] for item in response_items]

        self.assertIn(self.reminder.id, reminder_ids)
