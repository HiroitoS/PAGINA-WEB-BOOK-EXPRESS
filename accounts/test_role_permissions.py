"""La configuración de permisos por rol se gestiona desde el panel, no desde código."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import RolePermissionAudit


class RolePermissionManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            "role-panel-admin", "admin@test.example", "PassFuerte12345!",
        )
        cls.employee = get_user_model().objects.create_user(
            "role-panel-staff", "staff@test.example", "PassFuerte12345!",
        )
        cls.warehouse = Group.objects.create(name="ALMACEN")
        cls.manager = Group.objects.create(name="JEFE_ALMACEN")
        cls.administrator_role = Group.objects.create(name="ADMINISTRADOR")
        cls.view = Permission.objects.get(
            content_type__app_label="warehouse", codename="view_receiving",
        )
        cls.validate = Permission.objects.get(
            content_type__app_label="warehouse", codename="validate_receiving",
        )
        cls.register = Permission.objects.get(
            content_type__app_label="warehouse", codename="manage_receiving",
        )
        cls.unmanaged = Permission.objects.get(
            content_type__app_label="auth", codename="view_user",
        )
        cls.warehouse.permissions.add(cls.view, cls.register, cls.unmanaged)
        cls.manager.permissions.add(cls.view, cls.validate)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def url(self, role=None):
        return f"/api/admin/roles/{role or self.warehouse.pk}/permisos/"

    def test_admin_puede_configurar_y_conservar_permisos_no_funcionales(self):
        client = self.client_for(self.admin)
        response = client.patch(self.url(), {
            "functional_permission_ids": [self.view.pk, self.validate.pk],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.warehouse.refresh_from_db()
        self.assertSetEqual(
            set(self.warehouse.permissions.values_list("pk", flat=True)),
            {self.view.pk, self.validate.pk, self.unmanaged.pk},
        )
        audit = RolePermissionAudit.objects.get()
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(audit.group, self.warehouse)
        self.assertIn("warehouse.manage_receiving", audit.previous_permissions)
        self.assertIn("warehouse.validate_receiving", audit.new_permissions)

        # Idempotencia: sin cambios, no generar otro evento.
        again = client.patch(self.url(), {
            "functional_permission_ids": [self.validate.pk, self.view.pk],
        }, format="json")
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(RolePermissionAudit.objects.count(), 1)

        history = client.get(
            f"/api/admin/roles/{self.warehouse.pk}/historial-permisos/"
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.data["results"]), 1)

    def test_requisitos_de_dependencia_y_proteccion_admin(self):
        client = self.client_for(self.admin)
        bad = client.patch(self.url(), {
            "functional_permission_ids": [self.validate.pk],
        }, format="json")
        self.assertEqual(bad.status_code, 400, bad.data)
        self.assertFalse(RolePermissionAudit.objects.exists())
        self.assertEqual(self.warehouse.permissions.count(), 3)
        protected = client.patch(self.url(self.administrator_role.pk), {
            "functional_permission_ids": [],
        }, format="json")
        self.assertEqual(protected.status_code, 403, protected.data)

    def test_usuario_no_administrador_no_puede_modificar(self):
        response = self.client_for(self.employee).patch(self.url(), {
            "functional_permission_ids": [self.view.pk],
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(RolePermissionAudit.objects.exists())

    def test_sincronizacion_normal_no_borra_cambios_de_administracion(self):
        self.warehouse.permissions.set([self.view, self.validate])
        call_command("sync_bookexpress_roles", verbosity=0)
        self.assertSetEqual(
            set(self.warehouse.permissions.values_list("pk", flat=True)),
            {self.view.pk, self.validate.pk},
        )
