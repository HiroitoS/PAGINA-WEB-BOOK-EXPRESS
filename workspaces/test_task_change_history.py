from datetime import timedelta

from django.contrib.auth.models import Permission, User
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Task, TaskChangeHistory


class TaskChangeHistoryApiTests(APITestCase):
    def setUp(self):
        self.supervisor = User.objects.create_superuser(
            username="supervisor_audit",
            email="supervisor@example.com",
            password="PruebaSegura123",
        )
        self.advisor = User.objects.create_user(
            username="asesor_audit",
            password="PruebaSegura123",
        )
        self.replacement = User.objects.create_user(
            username="asesor_reemplazo_audit",
            password="PruebaSegura123",
        )
        self.outsider = User.objects.create_user(
            username="sin_acceso_audit",
            password="PruebaSegura123",
        )
        use_workspace = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="use_workspace",
        )
        self.outsider.user_permissions.add(use_workspace)
        self.original_due = timezone.now().replace(microsecond=0)
        self.task = Task.objects.create(
            title="Confirmar reunión con colegio",
            created_by=self.supervisor,
            assigned_to=self.advisor,
            due_at=self.original_due,
            priority="medium",
        )

    def test_supervisor_change_is_audited_once_with_actor_and_values(self):
        self.client.force_authenticate(self.supervisor)
        new_due = self.original_due + timedelta(days=3)

        response = self.client.patch(
            f"/api/admin/tasks/{self.task.pk}/",
            {
                "due_at": new_due.isoformat(),
                "assigned_to": self.replacement.pk,
                "priority": "high",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assigned_to_id, self.replacement.pk)
        self.assertEqual(self.task.due_at, new_due)
        self.assertEqual(TaskChangeHistory.objects.filter(task=self.task).count(), 1)

        entry = TaskChangeHistory.objects.get(task=self.task)
        self.assertEqual(entry.changed_by_id, self.supervisor.pk)
        self.assertIsNotNone(entry.created_at)

        by_field = {change["field"]: change for change in entry.changes}
        self.assertEqual(
            set(by_field),
            {"due_at", "assigned_to", "priority"},
        )
        self.assertEqual(
            by_field["assigned_to"]["old_id"],
            self.advisor.pk,
        )
        self.assertEqual(
            by_field["assigned_to"]["new_id"],
            self.replacement.pk,
        )
        self.assertEqual(by_field["priority"]["old"], "Media")
        self.assertEqual(by_field["priority"]["new"], "Alta")

        detail = self.client.get(f"/api/admin/tasks/{self.task.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.data["change_history"]), 1)
        self.assertEqual(
            detail.data["change_history"][0]["changed_by"],
            self.supervisor.pk,
        )

        tasks_response = self.client.get("/api/admin/tasks/")
        self.assertEqual(tasks_response.status_code, 200)
        listed = next(
            item for item in tasks_response.data
            if item["id"] == self.task.pk
        )
        self.assertNotIn("change_history", listed)

        with self.assertRaises(ProtectedError):
            self.task.delete()

    def test_patch_without_real_plan_change_does_not_create_history(self):
        self.client.force_authenticate(self.supervisor)

        response = self.client.patch(
            f"/api/admin/tasks/{self.task.pk}/",
            {"priority": "medium"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            TaskChangeHistory.objects.filter(task=self.task).exists()
        )

    def test_user_outside_task_scope_cannot_edit_or_see_audit(self):
        self.client.force_authenticate(self.outsider)

        patch_response = self.client.patch(
            f"/api/admin/tasks/{self.task.pk}/",
            {"priority": "high"},
            format="json",
        )
        detail_response = self.client.get(
            f"/api/admin/tasks/{self.task.pk}/"
        )
        self.assertIn(patch_response.status_code, [403, 404])
        self.assertIn(detail_response.status_code, [403, 404])
        self.assertFalse(
            TaskChangeHistory.objects.filter(task=self.task).exists()
        )
