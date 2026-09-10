from rest_framework.permissions import BasePermission

from accounts.permissions import usuario_es_administrador


class EsUsuarioWorkspace(BasePermission):
    """
    Permiso base para el módulo interno de ToDo.

    Permite ingresar a usuarios autenticados del panel.
    Las reglas finas se controlan en queryset, serializers y ViewSets.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


def usuario_puede_gestionar_grupo(user, group):
    if usuario_es_administrador(user):
        return True

    if not user or not user.is_authenticated or not group:
        return False

    if group.created_by_id == user.id:
        return True

    return group.memberships.filter(
        user=user,
        is_active=True,
        role__in=["owner", "coordinator"],
    ).exists()


def usuario_es_miembro_activo(user, group):
    if usuario_es_administrador(user):
        return True

    if not user or not user.is_authenticated or not group:
        return False

    if group.created_by_id == user.id:
        return True

    return group.memberships.filter(
        user=user,
        is_active=True,
    ).exists()


def usuario_puede_ver_tarea(user, task):
    if usuario_es_administrador(user):
        return True

    if not user or not user.is_authenticated or not task:
        return False

    if task.created_by_id == user.id:
        return True

    if task.assigned_to_id == user.id:
        return True

    if task.group and usuario_es_miembro_activo(user, task.group):
        return True

    return False


def usuario_puede_editar_datos_tarea(user, task):
    """
    Permite cambiar planificación de la tarea:
    título, grupo, responsable, fecha, categoría, prioridad y descripción.
    """
    if usuario_es_administrador(user):
        return True

    if not user or not user.is_authenticated or not task:
        return False

    if task.created_by_id == user.id:
        return True

    if task.group and usuario_puede_gestionar_grupo(user, task.group):
        return True

    return False


def usuario_puede_dar_seguimiento_tarea(user, task):
    """
    Permite comentar, evidenciar, cambiar estado o completar.
    """
    if usuario_puede_editar_datos_tarea(user, task):
        return True

    if not user or not user.is_authenticated or not task:
        return False

    if task.assigned_to_id == user.id:
        return True

    return False


def usuario_puede_completar_tarea(user, task):
    return usuario_puede_dar_seguimiento_tarea(user, task)


def usuario_puede_editar_tarea(user, task):
    """
    Compatibilidad con código existente.
    Desde ahora significa editar datos, no solo atender.
    """
    return usuario_puede_editar_datos_tarea(user, task)


def usuario_puede_ver_evento(user, event):
    if usuario_es_administrador(user):
        return True

    if not user or not user.is_authenticated or not event:
        return False

    if event.created_by_id == user.id:
        return True

    if event.assigned_to_id == user.id:
        return True

    if event.participants.filter(id=user.id).exists():
        return True

    if event.group and usuario_es_miembro_activo(user, event.group):
        return True

    return False


def usuario_puede_editar_datos_evento(user, event):
    """
    Permite cambiar datos del evento:
    fecha, hora, grupo, responsable, participantes y descripción.
    """
    if usuario_es_administrador(user):
        return True

    if not user or not user.is_authenticated or not event:
        return False

    if event.created_by_id == user.id:
        return True

    if event.group and usuario_puede_gestionar_grupo(user, event.group):
        return True

    return False


def usuario_puede_editar_evento(user, event):
    return usuario_puede_editar_datos_evento(user, event)


def usuario_puede_ver_recordatorio(user, reminder):
    if usuario_es_administrador(user):
        return True

    if not user or not user.is_authenticated or not reminder:
        return False

    if reminder.created_by_id == user.id:
        return True

    if reminder.user_id == user.id:
        return True

    if reminder.group and usuario_es_miembro_activo(user, reminder.group):
        return True

    if reminder.task and reminder.task.group and usuario_es_miembro_activo(user, reminder.task.group):
        return True

    if reminder.event and reminder.event.group and usuario_es_miembro_activo(user, reminder.event.group):
        return True

    return False


def usuario_puede_editar_datos_recordatorio(user, reminder):
    """
    Permite cambiar programación, responsable, grupo y texto del recordatorio.
    """
    if usuario_es_administrador(user):
        return True

    if not user or not user.is_authenticated or not reminder:
        return False

    if reminder.created_by_id == user.id:
        return True

    if reminder.group and usuario_puede_gestionar_grupo(user, reminder.group):
        return True

    return False


def usuario_puede_completar_recordatorio(user, reminder):
    """
    Permite marcar como completado o reabrir.
    """
    if usuario_puede_editar_datos_recordatorio(user, reminder):
        return True

    if not user or not user.is_authenticated or not reminder:
        return False

    if reminder.user_id == user.id:
        return True

    return False


def usuario_puede_editar_recordatorio(user, reminder):
    return usuario_puede_editar_datos_recordatorio(user, reminder)