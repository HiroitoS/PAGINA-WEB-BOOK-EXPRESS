from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from accounts.permission_registry import get_functional_permissions_queryset
from accounts.permissions import (
    ROL_ADMINISTRADOR,
    ROL_ALMACEN,
    ROL_ASESOR_COMERCIAL,
    ROL_ATENCION,
    ROL_CATALOGO,
    ROL_JEFE_COMERCIAL,
)


ROLE_PERMISSIONS = {
    ROL_ADMINISTRADOR: [
        "catalog.view_catalog",
        "catalog.manage_catalog",
        "catalog.view_prices",
        "catalog.manage_prices",
        "catalog.manage_imports",
        "inquiries.view_inquiries",
        "inquiries.manage_inquiries",
        "inquiries.assign_inquiries",
        "workspaces.use_workspace",
        "workspaces.create_workspace_group",
        "workspaces.assign_work",
        "workspaces.supervise_workspace",
        "crm.view_crm",
        "crm.manage_campaigns",
        "crm.manage_commercial_teams",
        "crm.manage_schools",
        "crm.assign_schools",
        "crm.manage_own_opportunities",
        "crm.assign_opportunities",
        "crm.supervise_crm",
        "crm.manage_quotations",
        "crm.manage_adoptions",
        "crm.export_crm_reports",
    ],
    ROL_CATALOGO: [
        "catalog.view_catalog",
        "catalog.manage_catalog",
        "catalog.view_prices",
        "catalog.manage_prices",
        "catalog.manage_imports",
        "workspaces.use_workspace",
    ],
    ROL_ATENCION: [
        "inquiries.view_inquiries",
        "inquiries.manage_inquiries",
        "workspaces.use_workspace",
    ],
    ROL_ASESOR_COMERCIAL: [
        "catalog.view_catalog",
        "workspaces.use_workspace",
        "crm.view_crm",
        "crm.manage_schools",
        "crm.manage_own_opportunities",
    ],
    ROL_JEFE_COMERCIAL: [
        "catalog.view_catalog",
        "workspaces.use_workspace",
        "workspaces.create_workspace_group",
        "workspaces.assign_work",
        "workspaces.supervise_workspace",
        "crm.view_crm",
        "crm.manage_schools",
        "crm.assign_schools",
        "crm.manage_own_opportunities",
        "crm.assign_opportunities",
        "crm.supervise_crm",
        "crm.export_crm_reports",
    ],
    ROL_ALMACEN: [],
}


class Command(BaseCommand):
    help = (
        "Crea los roles base de Book Express y agrega sus permisos funcionales "
        "sin eliminar permisos existentes."
    )

    def handle(self, *args, **options):
        for role_name, permission_names in ROLE_PERMISSIONS.items():
            group, created = Group.objects.get_or_create(name=role_name)

            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"Rol creado: {role_name}")
                )

            permissions = []

            for permission_name in permission_names:
                app_label, codename = permission_name.split(".", 1)

                try:
                    permission = Permission.objects.get(
                        content_type__app_label=app_label,
                        codename=codename,
                    )
                except Permission.DoesNotExist:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Permiso no encontrado: {permission_name}"
                        )
                    )
                    continue

                permissions.append(permission)

            managed_permission_ids = set(
                get_functional_permissions_queryset()
                .values_list("id", flat=True)
            )

            preserved_permissions = list(
                group.permissions
                .exclude(id__in=managed_permission_ids)
            )

            group.permissions.set([
                *preserved_permissions,
                *permissions,
            ])

            self.stdout.write(
                self.style.SUCCESS(
                    f"{role_name}: {len(permissions)} permiso(s) funcional(es) sincronizado(s)."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Sincronización de roles y permisos finalizada."
            )
        )
