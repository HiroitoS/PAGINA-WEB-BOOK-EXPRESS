from django.contrib.auth.models import Permission, User
from django.test import TestCase

from notifications.models import Notification

from .models import Task, TaskComment, TaskStatusHistory


class TaskManagementLifecycleTests(TestCase):

    def test_task_list_preserves_assignee_operational_permissions(self):
        task = self.create_task()
        self.client.force_login(self.assignee)

        response = self.client.get("/api/admin/tasks/")

        self.assertEqual(response.status_code, 200)

        listed_task = next(
            item for item in response.data
            if item["id"] == task.id
        )

        self.assertTrue(listed_task["can_follow_up"])
        self.assertTrue(listed_task["can_complete"])
        self.assertFalse(listed_task["can_reopen"])
        self.assertFalse(listed_task["is_read_only"])

    def test_task_list_is_lightweight_and_detail_keeps_history(self):
        task = self.create_task()

        TaskComment.objects.create(
            task=task,
            user=self.assignee,
            action_type="call",
            comment="Se realizó el seguimiento.",
        )

        TaskStatusHistory.objects.create(
            task=task,
            changed_by=self.assignee,
            old_status="pending",
            new_status="in_progress",
            note="Se inició la gestión.",
        )

        self.client.force_login(self.creator)

        list_response = self.client.get("/api/admin/tasks/")
        self.assertEqual(list_response.status_code, 200)

        listed_task = next(
            item for item in list_response.data
            if item["id"] == task.id
        )

        self.assertNotIn("comments", listed_task)
        self.assertNotIn("status_history", listed_task)

        detail_response = self.client.get(
            f"/api/admin/tasks/{task.id}/"
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("comments", detail_response.data)
        self.assertIn("status_history", detail_response.data)

        self.assertEqual(
            len(detail_response.data["comments"]),
            1,
        )

        self.assertEqual(
            len(detail_response.data["status_history"]),
            1,
        )

    def setUp(self):
        self.use_workspace = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="use_workspace",
        )

        self.creator = User.objects.create_user(
            username="jefe_gestion",
            password="PruebaSegura123",
        )
        self.creator.user_permissions.add(self.use_workspace)

        self.assignee = User.objects.create_user(
            username="asesor_gestion",
            password="PruebaSegura123",
        )
        self.assignee.user_permissions.add(self.use_workspace)

    def create_task(self, status="pending"):
        return Task.objects.create(
            title="Seguimiento de colegio",
            created_by=self.creator,
            assigned_to=self.assignee,
            status=status,
        )

    def test_management_without_status_change_only_creates_comment(self):
        task = self.create_task()
        self.client.force_login(self.assignee)

        response = self.client.post(
            f"/api/admin/tasks/{task.id}/register-management/",
            {
                "action_type": "call",
                "comment": "Se conversó con la directora.",
                "status": None,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)

        task.refresh_from_db()
        self.assertEqual(task.status, "pending")
        self.assertEqual(TaskComment.objects.filter(task=task).count(), 1)
        self.assertEqual(TaskStatusHistory.objects.filter(task=task).count(), 0)

    def test_management_can_change_status_in_same_operation(self):
        task = self.create_task()
        self.client.force_login(self.assignee)

        response = self.client.post(
            f"/api/admin/tasks/{task.id}/register-management/",
            {
                "action_type": "visit",
                "comment": "La visita fue realizada.",
                "status": "completed",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)

        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIsNotNone(task.completed_at)
        self.assertTrue(
            TaskStatusHistory.objects.filter(
                task=task,
                old_status="pending",
                new_status="completed",
                note="",
            ).exists()
        )

    def test_closed_task_cannot_receive_normal_management(self):
        task = self.create_task(status="completed")
        self.client.force_login(self.assignee)

        response = self.client.post(
            f"/api/admin/tasks/{task.id}/register-management/",
            {
                "action_type": "comment",
                "comment": "Intento de seguimiento.",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_assignee_can_reopen_own_closed_task_with_reason(self):
        task = self.create_task(status="completed")
        self.client.force_login(self.assignee)

        response = self.client.post(
            f"/api/admin/tasks/{task.id}/reopen/",
            {
                "reason": "El colegio solicitó una nueva coordinación.",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        task.refresh_from_db()
        self.assertEqual(task.status, "pending")
        self.assertIsNone(task.completed_at)
        self.assertTrue(
            TaskStatusHistory.objects.filter(
                task=task,
                old_status="completed",
                new_status="pending",
                note="El colegio solicitó una nueva coordinación.",
            ).exists()
        )

    def test_closed_task_cannot_be_edited_with_generic_patch(self):
        task = self.create_task(status="completed")
        self.client.force_login(self.creator)

        response = self.client.patch(
            f"/api/admin/tasks/{task.id}/",
            {"title": "Título alterado"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

        task.refresh_from_db()
        self.assertEqual(task.title, "Seguimiento de colegio")
    def test_creator_can_supervise_but_cannot_register_management_for_assignee(self):
        task = self.create_task()
        self.client.force_login(self.creator)

        response = self.client.post(
            f"/api/admin/tasks/{task.id}/register-management/",
            {
                "action_type": "comment",
                "comment": "Intento de registrar gestión del asesor.",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(TaskComment.objects.filter(task=task).exists())

    def test_task_list_is_not_truncated_by_global_twenty_item_pagination(self):
        for index in range(25):
            Task.objects.create(
                title=f"Tarea visible {index}",
                created_by=self.creator,
                assigned_to=self.assignee,
            )

        self.client.force_login(self.creator)
        response = self.client.get("/api/admin/tasks/")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        self.assertGreaterEqual(len(response.data), 25)
    def test_completed_management_notification_is_visible_but_resolved(self):
        task = self.create_task()
        self.client.force_login(self.assignee)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/admin/tasks/{task.id}/register-management/",
                {
                    "action_type": "evidence",
                    "comment": "Trabajo terminado y validado.",
                    "status": "completed",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)

        notification = Notification.objects.filter(
            recipient=self.creator,
            event_type="workspace.task_comment_added",
            metadata__task_id=task.id,
        ).first()

        self.assertIsNotNone(notification)
        self.assertTrue(notification.is_resolved)
        self.assertFalse(notification.is_read)

