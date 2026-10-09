from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from .models import Task, TaskMyDaySelection


User = get_user_model()


class TaskMyDayApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="myday-admin",
            email="myday-admin@example.com",
            password="test-pass-123",
        )
        self.other_user = User.objects.create_superuser(
            username="myday-other",
            email="myday-other@example.com",
            password="test-pass-123",
        )
        self.task = Task.objects.create(
            title="Preparar propuesta Book Express",
            created_by=self.user,
            assigned_to=self.user,
        )
        self.client.force_authenticate(self.user)

    def test_my_day_is_personal_and_can_be_removed(self):
        detail_url = reverse(
            "admin-task-my-day",
            args=[self.task.pk],
        )
        list_url = reverse("admin-task-list")

        response = self.client.post(detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["in_my_day"])
        self.assertTrue(
            TaskMyDaySelection.objects.filter(
                task=self.task,
                user=self.user,
                selected_date=timezone.localdate(),
            ).exists()
        )

        response = self.client.get(
            list_url,
            {"my_day": "true"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.task.pk)

        self.client.force_authenticate(self.other_user)

        response = self.client.get(
            list_url,
            {"my_day": "true"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

        self.client.force_authenticate(self.user)
        response = self.client.delete(detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["in_my_day"])
        self.assertFalse(
            TaskMyDaySelection.objects.filter(
                task=self.task,
                user=self.user,
            ).exists()
        )

    def test_closed_task_cannot_be_added_to_my_day(self):
        self.task.status = "completed"
        self.task.completed_at = timezone.now()
        self.task.save(
            update_fields=[
                "status",
                "completed_at",
                "updated_at",
            ]
        )

        response = self.client.post(
            reverse(
                "admin-task-my-day",
                args=[self.task.pk],
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertFalse(
            TaskMyDaySelection.objects.filter(
                task=self.task,
                user=self.user,
            ).exists()
        )
