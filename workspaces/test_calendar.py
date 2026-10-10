from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from .models import CalendarEvent, Reminder, Task


User = get_user_model()


class WorkspaceCalendarApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="calendar-admin",
            email="calendar-admin@example.com",
            password="PruebaSegura123",
        )
        self.client.force_authenticate(self.user)

        self.range_start = timezone.now().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        self.range_end = self.range_start + timedelta(days=2)
        self.calendar_url = reverse("admin-workspace-calendar")

    def get_calendar(self):
        return self.client.get(
            self.calendar_url,
            {
                "start": self.range_start.isoformat(),
                "end": self.range_end.isoformat(),
            },
        )

    def test_calendar_returns_single_unified_read_model(self):
        due_task = Task.objects.create(
            title="Enviar propuesta",
            created_by=self.user,
            assigned_to=self.user,
            due_at=self.range_start + timedelta(hours=10),
        )
        start_only_task = Task.objects.create(
            title="Preparar reunión",
            created_by=self.user,
            assigned_to=self.user,
            start_at=self.range_start + timedelta(hours=12),
        )
        Task.objects.create(
            title="Tarea fuera del rango",
            created_by=self.user,
            assigned_to=self.user,
            due_at=self.range_start + timedelta(days=5),
        )
        Task.objects.create(
            title="Tarea completada",
            created_by=self.user,
            assigned_to=self.user,
            due_at=self.range_start + timedelta(hours=13),
            status="completed",
            completed_at=self.range_start + timedelta(hours=9),
        )

        event = CalendarEvent.objects.create(
            title="Reunión interna",
            created_by=self.user,
            assigned_to=self.user,
            start_at=self.range_start + timedelta(hours=14),
            end_at=self.range_start + timedelta(hours=15),
        )

        manual_reminder = Reminder.objects.create(
            created_by=self.user,
            user=self.user,
            title="Confirmar entrega",
            remind_at=self.range_start + timedelta(hours=16),
        )
        task_reminder = Reminder.objects.create(
            created_by=self.user,
            user=self.user,
            task=due_task,
            source="task",
            title=due_task.title,
            remind_at=self.range_start + timedelta(hours=9),
        )

        Reminder.objects.create(
            created_by=self.user,
            user=self.user,
            title="Recordatorio descartado",
            remind_at=self.range_start + timedelta(hours=17),
            status="dismissed",
        )
        Reminder.objects.create(
            created_by=self.user,
            user=self.user,
            title="Recordatorio completado",
            remind_at=self.range_start + timedelta(hours=18),
            status="completed",
            completed_at=self.range_start + timedelta(hours=8),
        )

        response = self.get_calendar()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        item_ids = {item["id"] for item in response.data}

        self.assertEqual(
            item_ids,
            {
                f"task-{due_task.id}",
                f"task-{start_only_task.id}",
                f"event-{event.id}",
                f"reminder-{manual_reminder.id}",
                f"reminder-{task_reminder.id}",
            },
        )
        self.assertEqual(len(response.data), len(item_ids))

        start_only_item = next(
            item
            for item in response.data
            if item["id"] == f"task-{start_only_task.id}"
        )
        self.assertEqual(start_only_item["start_at"], start_only_task.start_at)
        self.assertIsNone(start_only_item["due_at"])
        self.assertEqual(start_only_item["start"], start_only_task.start_at)

    def test_calendar_items_are_sorted_by_display_time(self):
        later_task = Task.objects.create(
            title="Actividad posterior",
            created_by=self.user,
            assigned_to=self.user,
            due_at=self.range_start + timedelta(hours=15),
        )
        earlier_task = Task.objects.create(
            title="Actividad anterior",
            created_by=self.user,
            assigned_to=self.user,
            due_at=self.range_start + timedelta(hours=8),
        )

        response = self.get_calendar()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data],
            [
                f"task-{earlier_task.id}",
                f"task-{later_task.id}",
            ],
        )
