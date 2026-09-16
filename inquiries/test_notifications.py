from django.contrib.auth.models import Permission, User
from django.test import TestCase

from notifications.models import Notification

from .models import (
    ContactRequest,
    ContactRequestComment,
)
from .notification_events import (
    notify_contact_request_assigned,
    notify_contact_request_comment_added,
    notify_contact_request_status_changed,
    notify_new_contact_request,
)


class InquiryNotificationEventTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="atencion",
            password="PruebaSegura123",
        )
        self.read_only = User.objects.create_user(
            username="consulta",
            password="PruebaSegura123",
        )
        self.actor = User.objects.create_user(
            username="administrador",
            password="PruebaSegura123",
        )

        manage_permission = Permission.objects.get(
            content_type__app_label="inquiries",
            codename="manage_inquiries",
        )
        view_permission = Permission.objects.get(
            content_type__app_label="inquiries",
            codename="view_inquiries",
        )

        self.manager.user_permissions.add(manage_permission)
        self.read_only.user_permissions.add(view_permission)

    def test_new_request_notifies_managers_not_read_only_users(self):
        request = ContactRequest.objects.create(
            full_name="Cliente de prueba",
            phone="999999999",
            message="Necesito información.",
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_new_contact_request(request)

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.manager,
                event_type="inquiries.request_created",
                source_id=str(request.id),
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                recipient=self.read_only,
                event_type="inquiries.request_created",
            ).exists()
        )

    def test_assignment_notifies_new_assignee(self):
        request = ContactRequest.objects.create(
            full_name="Cliente asignado",
            phone="988888888",
            message="Consulta.",
            assigned_to=self.manager,
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_contact_request_assigned(
                request,
                actor=self.actor,
            )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.manager,
                event_type="inquiries.request_assigned",
                source_id=str(request.id),
            ).exists()
        )

    def test_self_assignment_does_not_notify(self):
        request = ContactRequest.objects.create(
            full_name="Autoasignación",
            phone="977777777",
            message="Consulta.",
            assigned_to=self.actor,
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_contact_request_assigned(
                request,
                actor=self.actor,
            )

        self.assertFalse(
            Notification.objects.filter(
                recipient=self.actor,
                event_type="inquiries.request_assigned",
            ).exists()
        )

    def test_status_change_notifies_assignee_when_changed_by_other_user(self):
        request = ContactRequest.objects.create(
            full_name="Cambio de estado",
            phone="966666666",
            message="Consulta.",
            assigned_to=self.manager,
            status="contacted",
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_contact_request_status_changed(
                request,
                actor=self.actor,
                old_status="under_review",
            )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.manager,
                event_type="inquiries.request_status_changed",
                source_id=str(request.id),
            ).exists()
        )

    def test_comment_notifies_assignee_when_written_by_other_user(self):
        request = ContactRequest.objects.create(
            full_name="Seguimiento",
            phone="955555555",
            message="Consulta.",
            assigned_to=self.manager,
        )
        comment = ContactRequestComment.objects.create(
            contact_request=request,
            user=self.actor,
            action_type="follow_up",
            comment="Se realizó seguimiento.",
        )

        with self.captureOnCommitCallbacks(execute=True):
            notify_contact_request_comment_added(
                comment,
                actor=self.actor,
            )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.manager,
                event_type="inquiries.request_comment_added",
                source_id=str(comment.id),
            ).exists()
        )
