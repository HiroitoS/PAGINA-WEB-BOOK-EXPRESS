from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import Notification


class NotificationApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="notificaciones_usuario",
            password="PruebaSegura123",
        )
        self.other_user = User.objects.create_user(
            username="otro_usuario",
            password="PruebaSegura123",
        )

        self.own_notification = Notification.objects.create(
            recipient=self.user,
            title="Notificación propia",
            event_type="test.created",
            module="test",
        )
        Notification.objects.create(
            recipient=self.other_user,
            title="Notificación ajena",
            event_type="test.created",
            module="test",
        )

    def test_user_only_sees_own_notifications(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/admin/notifications/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["id"],
            self.own_notification.id,
        )

    def test_mark_notification_as_read(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            f"/api/admin/notifications/{self.own_notification.id}/mark-read/"
        )

        self.assertEqual(response.status_code, 200)

        self.own_notification.refresh_from_db()
        self.assertTrue(self.own_notification.is_read)
        self.assertIsNotNone(self.own_notification.read_at)

    def test_mark_all_notifications_as_read(self):
        Notification.objects.create(
            recipient=self.user,
            title="Segunda notificación",
            event_type="test.created",
            module="test",
        )

        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/admin/notifications/mark-all-read/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated"], 2)
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.user,
                is_read=False,
            ).exists()
        )

    def test_unread_count_ignores_resolved_notifications(self):
        Notification.objects.create(
            recipient=self.user,
            title="Aviso ya resuelto",
            event_type="test.resolved",
            module="test",
            is_resolved=True,
        )

        self.client.force_authenticate(self.user)
        response = self.client.get(
            "/api/admin/notifications/unread-count/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_can_filter_resolved_notifications(self):
        resolved = Notification.objects.create(
            recipient=self.user,
            title="Aviso resuelto",
            event_type="test.resolved",
            module="test",
            is_resolved=True,
        )

        self.client.force_authenticate(self.user)
        response = self.client.get(
            "/api/admin/notifications/?is_resolved=true"
        )

        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertIn(resolved.id, ids)
        self.assertNotIn(self.own_notification.id, ids)
