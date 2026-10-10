from django.contrib.auth.models import Permission, User
from django.utils import timezone
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from .models import (
    Reminder,
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

    def test_private_group_task_is_hidden_from_other_members(self):
        task = Task.objects.create(
            title="Gestión reservada",
            created_by=self.owner,
            assigned_to=self.owner,
            group=self.group,
            is_private=True,
        )

        self.client.force_authenticate(self.member)
        listed = self.client.get(reverse("admin-task-list"))
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertNotIn(task.id, [item["id"] for item in listed.data])

        detail = self.client.get(
            reverse("admin-task-detail", args=[task.id]),
        )
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(self.owner)
        detail = self.client.get(
            reverse("admin-task-detail", args=[task.id]),
        )
        self.assertEqual(detail.status_code, status.HTTP_200_OK)

    def test_private_task_reminder_is_not_visible_to_group_coordinator(self):
        self.group.memberships.filter(user=self.member).update(
            role="coordinator",
        )
        task = Task.objects.create(
            title="Seguimiento confidencial",
            created_by=self.owner,
            assigned_to=self.owner,
            group=self.group,
            is_private=True,
        )
        reminder = Reminder.objects.create(
            title="Aviso reservado",
            task=task,
            group=self.group,
            created_by=self.owner,
            user=self.owner,
            remind_at=timezone.now(),
            source="manual",
        )

        self.client.force_authenticate(self.member)
        listed = self.client.get("/api/admin/reminders/")
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        items = (
            listed.data["results"]
            if isinstance(listed.data, dict)
            else listed.data
        )
        self.assertNotIn(reminder.id, [item["id"] for item in items])

        detail = self.client.get(
            f"/api/admin/reminders/{reminder.id}/",
        )
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_private_task_is_visible_to_its_assignee(self):
        task = Task.objects.create(
            title="Tarea privada asignada",
            created_by=self.owner,
            assigned_to=self.member,
            group=self.group,
            is_private=True,
        )

        self.client.force_authenticate(self.member)
        detail = self.client.get(
            reverse("admin-task-detail", args=[task.id]),
        )
        self.assertEqual(detail.status_code, status.HTTP_200_OK)

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
        owner_group_items = (
            group_response.data["results"]
            if isinstance(group_response.data, dict)
            else group_response.data
        )
        owner_group = next(
            item
            for item in owner_group_items
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
        member_group_items = (
            group_response.data["results"]
            if isinstance(group_response.data, dict)
            else group_response.data
        )
        member_group = next(
            item
            for item in member_group_items
            if item["id"] == self.group.id
        )
        self.assertFalse(member_group["can_manage"])

    def test_group_member_can_view_but_cannot_manage_another_members_task(self):
        second_member = User.objects.create_user(
            username="todo-list-second-member",
            password="PruebaSegura123",
        )
        use_workspace = Permission.objects.get(
            content_type__app_label="workspaces",
            codename="use_workspace",
        )
        second_member.user_permissions.add(use_workspace)
        WorkspaceMembership.objects.create(
            group=self.group,
            user=second_member,
            role="member",
        )

        shared_list = WorkspaceTaskList.objects.create(
            name="Trabajo compartido",
            workspace_group=self.group,
            created_by=self.owner,
        )
        task = Task.objects.create(
            title="Tarea asignada a otra persona",
            task_list=shared_list,
            group=self.group,
            created_by=self.owner,
            assigned_to=second_member,
        )

        self.client.force_authenticate(self.member)

        detail_response = self.client.get(
            reverse("admin-task-detail", args=[task.id]),
        )

        self.assertEqual(
            detail_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertFalse(detail_response.data["can_edit_details"])
        self.assertFalse(detail_response.data["can_follow_up"])
        self.assertFalse(detail_response.data["can_complete"])
        self.assertTrue(detail_response.data["is_read_only"])

        update_response = self.client.patch(
            reverse("admin-task-detail", args=[task.id]),
            {"priority": "urgent"},
            format="json",
        )
        self.assertEqual(
            update_response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        management_response = self.client.post(
            reverse("admin-task-register-management", args=[task.id]),
            {
                "action_type": "comment",
                "comment": "Intento de gestión no autorizado.",
            },
            format="json",
        )
        self.assertEqual(
            management_response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        status_response = self.client.post(
            reverse("admin-task-change-status", args=[task.id]),
            {
                "status": "in_progress",
                "note": "Intento de cambio no autorizado.",
            },
            format="json",
        )
        self.assertEqual(
            status_response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        comment_response = self.client.post(
            reverse("admin-task-add-comment", args=[task.id]),
            {
                "action_type": "comment",
                "comment": "Intento de comentario no autorizado.",
            },
            format="json",
        )
        self.assertEqual(
            comment_response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        task.refresh_from_db()
        self.assertEqual(task.priority, "medium")
        self.assertEqual(task.status, "pending")

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

    def test_team_list_task_can_stay_unassigned(self):
        shared_list = WorkspaceTaskList.objects.create(
            name="Pendientes del equipo",
            workspace_group=self.group,
            created_by=self.owner,
        )

        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse("admin-task-list"),
            {
                "title": "Preparar material de campaña",
                "task_list": shared_list.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        task = Task.objects.get(pk=response.data["id"])
        self.assertEqual(task.group_id, self.group.id)
        self.assertIsNone(task.assigned_to_id)

    def test_team_list_rejects_assignee_outside_group(self):
        shared_list = WorkspaceTaskList.objects.create(
            name="Seguimiento del equipo",
            workspace_group=self.group,
            created_by=self.owner,
        )

        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse("admin-task-list"),
            {
                "title": "Tarea inválida",
                "task_list": shared_list.id,
                "assigned_to": self.outsider.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            Task.objects.filter(title="Tarea inválida").exists()
        )

    def test_team_list_rejects_inactive_member_as_assignee(self):
        shared_list = WorkspaceTaskList.objects.create(
            name="Campaña activa",
            workspace_group=self.group,
            created_by=self.owner,
        )
        membership = WorkspaceMembership.objects.get(
            group=self.group,
            user=self.member,
        )
        membership.is_active = False
        membership.save(update_fields=["is_active", "updated_at"])

        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse("admin-task-list"),
            {
                "title": "Tarea para miembro inactivo",
                "task_list": shared_list.id,
                "assigned_to": self.member.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            Task.objects.filter(
                title="Tarea para miembro inactivo",
            ).exists()
        )

    def test_team_list_rejects_reassignment_outside_group(self):
        shared_list = WorkspaceTaskList.objects.create(
            name="Lista con responsable",
            workspace_group=self.group,
            created_by=self.owner,
        )
        task = Task.objects.create(
            title="Tarea existente",
            task_list=shared_list,
            group=self.group,
            created_by=self.owner,
            assigned_to=self.member,
        )

        self.client.force_authenticate(self.owner)
        response = self.client.patch(
            reverse("admin-task-detail", args=[task.id]),
            {
                "assigned_to": self.outsider.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        task.refresh_from_db()
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
