from rest_framework.permissions import BasePermission

from accounts.permissions import usuario_es_administrador, usuario_tiene_permiso


class EsUsuarioWorkspace(BasePermission):
    """
    Permiso base para el módulo interno de ToDo.

    Requiere el permiso funcional workspaces.use_workspace.
    Las reglas finas por objeto se controlan en queryset, serializers
    y ViewSets.
    """

    def has_permission(self, request, view):
        return usuario_tiene_permiso(
            request.user,
            "workspaces.use_workspace",
        )


def usuario_puede_crear_grupo(user):
    return usuario_tiene_permiso(
        user,
        "workspaces.create_workspace_group",
    )


def usuario_puede_asignar_trabajo(user):
    return usuario_tiene_permiso(
        user,
        "workspaces.assign_work",
    )


def usuario_puede_supervisar_workspace(user):
    """
    Capacidad reservada para supervisión transversal.

    Por ahora no amplía automáticamente la visibilidad a todos los grupos
    de la empresa. Ese alcance se definirá cuando exista una estructura
    formal de equipos/CRM.
    """
    return usuario_tiene_permiso(
        user,
        "workspaces.supervise_workspace",
    )


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


def tarea_esta_cerrada(task):
    return bool(
        task
        and task.status in ["completed", "cancelled"]
    )


def usuario_puede_editar_datos_tarea(user, task):
    """
    Permite cambiar planificación únicamente mientras la tarea está activa.

    Una tarea completada/cancelada se conserva como registro histórico.
    Para retomarla debe usarse la acción explícita de reapertura.
    """
    if not user or not user.is_authenticated or not task:
        return False

    if tarea_esta_cerrada(task):
        return False

    if usuario_es_administrador(user):
        return True

    if task.created_by_id == user.id:
        return True

    if task.group and usuario_puede_gestionar_grupo(user, task.group):
        return True

    return False


def usuario_puede_dar_seguimiento_tarea(user, task):
    """
    Permite registrar gestión únicamente al responsable asignado.

    Quien crea o supervisa una tarea puede consultar su avance y, si tiene
    permiso, ajustar la planificación; la gestión operativa corresponde al
    usuario asignado. Esto evita que un jefe/administrador registre trabajo
    en nombre del asesor y preserva la trazabilidad por responsable.
    """
    if not user or not user.is_authenticated or not task:
        return False

    if tarea_esta_cerrada(task):
        return False

    return task.assigned_to_id == user.id


def usuario_puede_completar_tarea(user, task):
    return usuario_puede_dar_seguimiento_tarea(user, task)


def usuario_puede_reabrir_tarea(user, task):
    """
    Reapertura controlada de tareas cerradas.

    - Administrador: cualquier tarea visible.
    - Responsable: su propia tarea asignada.
    - Creador: la tarea que creó.
    - Responsable/coordinador del grupo: tareas de ese grupo.

    Siempre se exige un motivo y se registra en TaskStatusHistory.
    """
    if not user or not user.is_authenticated or not task:
        return False

    if not tarea_esta_cerrada(task):
        return False

    if usuario_es_administrador(user):
        return True

    if task.assigned_to_id == user.id:
        return True

    if task.created_by_id == user.id:
        return True

    if task.group and usuario_puede_gestionar_grupo(user, task.group):
        return True

    return False


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