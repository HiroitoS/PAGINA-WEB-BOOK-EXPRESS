from rest_framework.permissions import BasePermission

from accounts.permissions import (
    usuario_es_administrador,
    usuario_tiene_permiso,
)


CRM_VIEW_PERMISSION = "crm.view_crm"
CRM_SUPERVISE_PERMISSION = "crm.supervise_crm"
CRM_MANAGE_SCHOOLS_PERMISSION = "crm.manage_schools"
CRM_ASSIGN_SCHOOLS_PERMISSION = "crm.assign_schools"
CRM_MANAGE_OWN_OPPORTUNITIES_PERMISSION = "crm.manage_own_opportunities"
CRM_ASSIGN_OPPORTUNITIES_PERMISSION = "crm.assign_opportunities"


def usuario_puede_ver_crm(user):
    return usuario_tiene_permiso(user, CRM_VIEW_PERMISSION)


def usuario_puede_supervisar_crm(user):
    return usuario_tiene_permiso(user, CRM_SUPERVISE_PERMISSION)


def usuario_puede_gestionar_colegios(user):
    return usuario_tiene_permiso(user, CRM_MANAGE_SCHOOLS_PERMISSION)


def usuario_puede_asignar_colegios(user):
    return usuario_tiene_permiso(user, CRM_ASSIGN_SCHOOLS_PERMISSION)


def usuario_puede_gestionar_oportunidades_propias(user):
    return usuario_tiene_permiso(
        user,
        CRM_MANAGE_OWN_OPPORTUNITIES_PERMISSION,
    )


def usuario_puede_asignar_oportunidades(user):
    return usuario_tiene_permiso(user, CRM_ASSIGN_OPPORTUNITIES_PERMISSION)


class EsUsuarioCRM(BasePermission):
    message = "No tienes permiso para acceder al CRM."

    def has_permission(self, request, view):
        return usuario_puede_ver_crm(request.user)


class EsSupervisorCRM(BasePermission):
    message = "No tienes permiso para supervisar el CRM."

    def has_permission(self, request, view):
        if usuario_es_administrador(request.user):
            return True

        return (
            usuario_puede_ver_crm(request.user)
            and usuario_puede_supervisar_crm(request.user)
        )
