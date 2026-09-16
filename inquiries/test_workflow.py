from django.contrib.auth.models import Permission, User
from django.urls import reverse
from rest_framework.test import APITestCase

from notifications.models import Notification

from .models import ContactRequest, ContactRequestComment


class ContactRequestWorkflowTests(APITestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="atencion_flujo",
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
        self.manager.user_permissions.add(
            manage_permission,
            view_permission,
        )

    def test_public_request_stores_inquiry_type_separately(self):
        response = self.client.post(
            "/api/public/contact-requests/",
            {
                "full_name": "María Pérez",
                "phone": "999999999",
                "email": "",
                "inquiry_type": "reading_plan",
                "message": "Necesito información para primaria.",
                "source": "web",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        contact_request = ContactRequest.objects.get(id=response.data["id"])
        self.assertEqual(contact_request.inquiry_type, "reading_plan")
        self.assertEqual(
            contact_request.message,
            "Necesito información para primaria.",
        )

    def test_generic_patch_cannot_change_status(self):
        contact_request = ContactRequest.objects.create(
            full_name="Cliente",
            phone="988888888",
            message="Consulta",
        )
        self.client.force_authenticate(self.manager)

        response = self.client.patch(
            f"/api/admin/contact-requests/{contact_request.id}/",
            {"status": "closed"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        contact_request.refresh_from_db()
        self.assertEqual(contact_request.status, "new")

    def test_register_attention_without_status_change(self):
        contact_request = ContactRequest.objects.create(
            full_name="Cliente",
            phone="977777777",
            message="Consulta",
            status="under_review",
        )
        self.client.force_authenticate(self.manager)

        response = self.client.post(
            f"/api/admin/contact-requests/{contact_request.id}/register-attention/",
            {
                "action_type": "whatsapp",
                "comment": "Se solicitó información adicional.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        contact_request.refresh_from_db()
        self.assertEqual(contact_request.status, "under_review")
        self.assertEqual(contact_request.status_history.count(), 0)
        self.assertEqual(contact_request.comments.count(), 1)

    def test_register_attention_can_change_status_atomically(self):
        contact_request = ContactRequest.objects.create(
            full_name="Cliente",
            phone="966666666",
            message="Consulta",
            status="under_review",
        )
        self.client.force_authenticate(self.manager)

        response = self.client.post(
            f"/api/admin/contact-requests/{contact_request.id}/register-attention/",
            {
                "action_type": "phone",
                "comment": "Cliente confirmó que la consulta fue atendida.",
                "status": "closed",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        contact_request.refresh_from_db()
        self.assertEqual(contact_request.status, "closed")
        self.assertIsNotNone(contact_request.closed_at)
        self.assertEqual(contact_request.comments.count(), 1)
        history = contact_request.status_history.get()
        self.assertEqual(history.old_status, "under_review")
        self.assertEqual(history.new_status, "closed")

    def test_closing_request_resolves_previous_notifications(self):
        contact_request = ContactRequest.objects.create(
            full_name="Cliente",
            phone="955555555",
            message="Consulta",
            status="in_follow_up",
        )
        Notification.objects.create(
            recipient=self.manager,
            title="Solicitud pendiente",
            event_type="inquiries.request_created",
            module="solicitudes",
            source_app="inquiries",
            source_model="ContactRequest",
            source_id=str(contact_request.id),
            metadata={"request_id": contact_request.id},
        )
        self.client.force_authenticate(self.manager)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/admin/contact-requests/{contact_request.id}/register-attention/",
                {
                    "action_type": "follow_up",
                    "comment": "Atención finalizada.",
                    "status": "closed",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Notification.objects.get(
                event_type="inquiries.request_created",
                source_id=str(contact_request.id),
            ).is_resolved
        )

    def test_closed_request_rejects_new_attention_until_reopened(self):
        contact_request = ContactRequest.objects.create(
            full_name="Cliente cerrado",
            phone="944444444",
            message="Consulta",
            status="closed",
        )
        self.client.force_authenticate(self.manager)

        response = self.client.post(
            f"/api/admin/contact-requests/{contact_request.id}/register-attention/",
            {
                "action_type": "whatsapp",
                "comment": "Intento de nueva gestión.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(contact_request.comments.count(), 0)

    def test_reopen_requires_reason(self):
        contact_request = ContactRequest.objects.create(
            full_name="Cliente cerrado",
            phone="933333333",
            message="Consulta",
            status="closed",
        )
        self.client.force_authenticate(self.manager)

        response = self.client.post(
            f"/api/admin/contact-requests/{contact_request.id}/reopen/",
            {"reason": ""},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        contact_request.refresh_from_db()
        self.assertEqual(contact_request.status, "closed")

    def test_reopen_moves_closed_request_to_follow_up_with_history(self):
        contact_request = ContactRequest.objects.create(
            full_name="Cliente cerrado",
            phone="922222222",
            message="Consulta",
            status="closed",
        )
        contact_request.closed_at = contact_request.created_at
        contact_request.save(update_fields=["closed_at", "updated_at"])
        self.client.force_authenticate(self.manager)

        response = self.client.post(
            f"/api/admin/contact-requests/{contact_request.id}/reopen/",
            {"reason": "El cliente solicitó ampliar la cotización."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        contact_request.refresh_from_db()
        self.assertEqual(contact_request.status, "in_follow_up")
        self.assertIsNone(contact_request.closed_at)

        history = contact_request.status_history.get()
        self.assertEqual(history.old_status, "closed")
        self.assertEqual(history.new_status, "in_follow_up")
        self.assertEqual(
            history.note,
            "El cliente solicitó ampliar la cotización.",
        )

    def test_request_cannot_be_deleted_from_admin_api(self):
        contact_request = ContactRequest.objects.create(
            full_name="Cliente trazable",
            phone="911111111",
            message="Consulta",
        )
        self.client.force_authenticate(self.manager)

        response = self.client.delete(
            f"/api/admin/contact-requests/{contact_request.id}/"
        )

        self.assertEqual(response.status_code, 405)
        self.assertTrue(
            ContactRequest.objects.filter(id=contact_request.id).exists()
        )

