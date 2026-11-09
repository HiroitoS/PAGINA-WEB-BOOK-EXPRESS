"""Campañas comerciales configurables por administrador, sin terminal."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from crm.models import Campaign, Pipeline, PipelineStage


BASE = "/api/admin/crm/campaigns/"
PIPELINE = "/api/admin/crm/pipelines/"


class CampaignManagementAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = get_user_model()
        cls.admin = user.objects.create_superuser(
            username="campaign-admin", password="test", email="campaign-admin@example.test",
        )
        cls.manager = user.objects.create_user(username="campaign-manager", password="test")
        cls.viewer = user.objects.create_user(username="campaign-viewer", password="test")
        permissions = Permission.objects.filter(
            content_type__app_label="crm",
            codename__in=("view_crm", "manage_campaigns"),
        )
        cls.manager.user_permissions.add(*permissions)
        cls.viewer.user_permissions.add(*permissions.filter(codename="view_crm"))

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_manager_creates_campaign_once_and_can_activate_it(self):
        client = self.client_as(self.manager)
        data = {"year": 2027, "campaign_type": "school", "status": "planning"}
        result = client.post(BASE, data, format="json")
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(result.data["code"], "SCHOOL-2027")
        self.assertEqual(result.data["name"], "Campaña escolar 2027")
        self.assertEqual(result.data["status"], "planning")

        duplicate = client.post(BASE, data, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(Campaign.objects.count(), 1)
        result = client.patch(
            f"{BASE}{result.data['id']}/", {"status": "active"}, format="json",
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["status"], "active")
        self.assertEqual(result.data["code"], "SCHOOL-2027")
        self.assertEqual(
            Campaign.objects.get(pk=result.data["id"]).created_by_id,
            self.manager.pk,
        )
        self.assertEqual(client.delete(f"{BASE}{result.data['id']}/").status_code, 405)

    def test_new_year_requires_closing_previous_active_school_campaign(self):
        client = self.client_as(self.admin)
        old = client.post(
            BASE, {"year": 2026, "campaign_type": "school", "status": "active"},
            format="json",
        )
        self.assertEqual(old.status_code, 201, old.data)
        cannot_activate = client.post(
            BASE, {"year": 2027, "campaign_type": "school", "status": "active"},
            format="json",
        )
        self.assertEqual(cannot_activate.status_code, 400)
        new = client.post(BASE, {"year": 2027, "campaign_type": "school"}, format="json")
        self.assertEqual(new.status_code, 201, new.data)
        attempt = client.patch(
            f"{BASE}{new.data['id']}/", {"status": "active"}, format="json",
        )
        self.assertEqual(attempt.status_code, 400)
        closed = client.patch(
            f"{BASE}{old.data['id']}/", {"status": "closed"}, format="json",
        )
        self.assertEqual(closed.status_code, 200, closed.data)
        activated = client.patch(
            f"{BASE}{new.data['id']}/", {"status": "active"}, format="json",
        )
        self.assertEqual(activated.status_code, 200, activated.data)
        self.assertEqual(activated.data["status"], "active")
        self.assertEqual(Campaign.objects.filter(campaign_type="school", status="active").count(), 1)

    def test_permissions_dates_immutable_year_and_readers(self):
        manager = self.client_as(self.manager)
        viewer = self.client_as(self.viewer)
        self.assertEqual(viewer.get(BASE).status_code, 200)
        self.assertEqual(
            viewer.post(BASE, {"year": 2028}, format="json").status_code, 403,
        )
        response = manager.post(
            BASE, {"year": 2028, "starts_on": "2028-03-10", "ends_on": "2028-02-01"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        record = manager.post(BASE, {"year": 2028}, format="json")
        self.assertEqual(record.status_code, 201, record.data)
        url = f"{BASE}{record.data['id']}/"
        self.assertEqual(viewer.patch(url, {"status": "active"}, format="json").status_code, 403)
        changed = manager.patch(url, {"year": 2040, "campaign_type": "general"}, format="json")
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["year"], 2028)
        self.assertEqual(changed.data["campaign_type"], "school")
        self.assertEqual(manager.put(url, {"status": "active"}, format="json").status_code, 405)


class PipelineSetupAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser(
            username="pipeline-admin", password="test", email="pipeline-admin@example.test",
        )
        cls.viewer = User.objects.create_user(username="pipeline-viewer", password="test")
        cls.viewer.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="crm", codename="view_crm",
            ),
        )

    def test_provisioning_only_once_with_permission_and_no_existing_data(self):
        client = APIClient()
        client.force_authenticate(user=self.viewer)
        self.assertEqual(
            client.post(f"{PIPELINE}configurar-inicial/", {}, format="json").status_code,
            403,
        )
        client.force_authenticate(user=self.admin)
        response = client.post(f"{PIPELINE}configurar-inicial/", {}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Pipeline.objects.count(), 1)
        pipeline = Pipeline.objects.get()
        self.assertTrue(pipeline.is_default)
        self.assertTrue(pipeline.is_active)
        self.assertEqual(
            PipelineStage.objects.filter(pipeline=pipeline, is_initial=True, is_active=True).count(),
            1,
        )
        again = client.post(f"{PIPELINE}configurar-inicial/", {}, format="json")
        self.assertEqual(again.status_code, 409, again.data)
        self.assertEqual(Pipeline.objects.count(), 1)

    def test_existing_pipeline_is_never_rewritten(self):
        existing = Pipeline.objects.create(
            code="SAVED-PIPELINE", name="Proceso existente", is_default=True,
        )
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.post(f"{PIPELINE}configurar-inicial/", {}, format="json")
        self.assertEqual(resp.status_code, 409, resp.data)
        existing.refresh_from_db()
        self.assertEqual(existing.name, "Proceso existente")
        self.assertEqual(Pipeline.objects.count(), 1)
