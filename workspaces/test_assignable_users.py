from django.contrib.auth.models import Permission, User
from rest_framework.test import APITestCase


class WorkspaceAssignableUsersTests(APITestCase):
    def setUp(self):
        self.use_workspace = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="use_workspace",
        )
        self.assign_work = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="assign_work",
        )
        self.create_group = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="create_workspace_group",
        )

        self.manager = User.objects.create_user(
            username="jefe_prueba",
            password="PruebaSegura123",
            first_name="Jefe",
            last_name="Comercial",
        )
        self.manager.user_permissions.add(
            self.use_workspace,
            self.assign_work,
            self.create_group,
        )

        self.advisor = User.objects.create_user(
            username="asesor_prueba",
            password="PruebaSegura123",
            first_name="Asesor",
            last_name="Prueba",
        )
        self.advisor.user_permissions.add(self.use_workspace)

        self.outsider = User.objects.create_user(
            username="sin_workspace",
            password="PruebaSegura123",
        )

        self.read_only_workspace = User.objects.create_user(
            username="solo_todo",
            password="PruebaSegura123",
        )
        self.read_only_workspace.user_permissions.add(self.use_workspace)

    def test_manager_can_list_assignable_workspace_users(self):
        self.client.force_authenticate(self.manager)

        response = self.client.get(
            "/api/admin/workspace/assignable-users/"
        )

        self.assertEqual(response.status_code, 200)

        usernames = {
            item["username"]
            for item in response.data
        }

        self.assertIn(self.manager.username, usernames)
        self.assertIn(self.advisor.username, usernames)
        self.assertNotIn(self.outsider.username, usernames)

    def test_endpoint_does_not_expose_sensitive_admin_fields(self):
        self.client.force_authenticate(self.manager)

        response = self.client.get(
            "/api/admin/workspace/assignable-users/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data)

        item = response.data[0]

        self.assertNotIn("email", item)
        self.assertNotIn("permissions", item)
        self.assertNotIn("groups", item)
        self.assertNotIn("is_staff", item)

    def test_workspace_user_without_assignment_capability_cannot_list_directory(self):
        self.client.force_authenticate(self.read_only_workspace)

        response = self.client.get(
            "/api/admin/workspace/assignable-users/"
        )

        self.assertEqual(response.status_code, 403)
