from django.contrib.auth.models import Permission, User
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from .models import (
    Task,
    WorkspaceGroup,
    WorkspaceMembership,
    WorkspaceTaskList,
)


class WorkspaceTaskListApiTests(APITestCase):
    def setUp(self):
        use_workspace = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="use_workspace",
        )

        self.owner = User.objects.create_user(
            username="todo-list-owner",
            password="PruebaSegura123",
        )
        self.member = User.objects.create_user(
            username="todo-list-member",
            password="PruebaSegura123",
        )
        self.outsider = User.objects.create_user(
            username="todo-list-outsider",
            password="PruebaSegura123",
        )

        for user in [self.owner, self.member, self.outsider]:
            user.user_permissions.add(use_workspace)

        self.group = WorkspaceGroup.objects.create(
            name="Equipo campaña escolar",
            created_by=self.owner,
        )
        WorkspaceMembership.objects.create(
            group=self.group,
            user=self.owner,
            role="owner",
        )
        WorkspaceMembership.objects.create(
            group=self.group,
            user=self.member,
            role="member",
        )

    def test_personal_list_is_only_visible_to_creator(self):
        personal_list = WorkspaceTaskList.objects.create(
            name="Pendientes personales",
            created_by=self.owner,
        )

        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse("admin-task-list-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data],
            [personal_list.id],
        )

        self.client.force_authenticate(self.member)
        response = self.client.get(reverse("admin-task-list-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_shared_list_is_visible_to_active_group_members(self):
        shared_list = WorkspaceTaskList.objects.create(
            name="Campaña escolar 2027",
            workspace_group=self.group,
            created_by=self.owner,
        )

        self.client.force_authenticate(self.member)
        response = self.client.get(reverse("admin-task-list-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], shared_list.id)
        self.assertEqual(
            response.data[0]["workspace_group"],
            self.group.id,
        )

        self.client.force_authenticate(self.outsider)
        response = self.client.get(reverse("admin-task-list-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_backend_exposes_list_and_group_management_scope(self):
        personal_list = WorkspaceTaskList.objects.create(
            name="Lista personal",
            created_by=self.owner,
        )
        shared_list = WorkspaceTaskList.objects.create(
            name="Lista compartida",
            workspace_group=self.group,
            created_by=self.owner,
        )

        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse("admin-task-list-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        owner_lists = {
            item["id"]: item
            for item in response.data
        }
        self.assertFalse(owner_lists[personal_list.id]["is_shared"])
        self.assertTrue(owner_lists[personal_list.id]["can_manage"])
        self.assertTrue(owner_lists[shared_list.id]["is_shared"])
        self.assertTrue(owner_lists[shared_list.id]["can_manage"])

        group_response = self.client.get(reverse("admin-workspace-group-list"))
        self.assertEqual(group_response.status_code, status.HTTP_200_OK)
        owner_group = next(
            item
            for item in group_response.data
            if item["id"] == self.group.id
        )
        self.assertTrue(owner_group["can_manage"])

        self.client.force_authenticate(self.member)
        response = self.client.get(reverse("admin-task-list-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], shared_list.id)
        self.assertTrue(response.data[0]["is_shared"])
        self.assertFalse(response.data[0]["can_manage"])

        group_response = self.client.get(reverse("admin-workspace-group-list"))
        self.assertEqual(group_response.status_code, status.HTTP_200_OK)
        member_group = next(
            item
            for item in group_response.data
            if item["id"] == self.group.id
        )
        self.assertFalse(member_group["can_manage"])

    def test_team_list_keeps_task_and_workspace_group_consistent(self):
        shared_list = WorkspaceTaskList.objects.create(
            name="Seguimiento colegios",
            workspace_group=self.group,
            created_by=self.owner,
        )

        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse("admin-task-list"),
            {
                "title": "Llamar al director",
                "task_list": shared_list.id,
                "assigned_to": self.member.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        task = Task.objects.get(pk=response.data["id"])
        self.assertEqual(task.task_list_id, shared_list.id)
        self.assertEqual(task.group_id, self.group.id)
        self.assertEqual(task.assigned_to_id, self.member.id)

    def test_user_cannot_attach_task_to_hidden_list(self):
        private_list = WorkspaceTaskList.objects.create(
            name="Lista privada del jefe",
            created_by=self.owner,
        )

        self.client.force_authenticate(self.outsider)
        response = self.client.post(
            reverse("admin-task-list"),
            {
                "title": "Intento fuera de alcance",
                "task_list": private_list.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            Task.objects.filter(title="Intento fuera de alcance").exists()
        )
