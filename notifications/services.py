from collections.abc import Iterable

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from .models import Notification


User = get_user_model()


def get_active_users_with_permission(permission_code):
    """
    Devuelve usuarios activos con un permiso efectivo de Django.

    Centraliza la selección de destinatarios por capacidad para que
    Solicitudes, CRM y ERP no dependan de nombres de roles concretos.
    """
    if not permission_code or "." not in permission_code:
        return User.objects.none()

    app_label, codename = permission_code.split(".", 1)

    return (
        User.objects
        .filter(is_active=True)
        .filter(
            models.Q(is_superuser=True)
            | models.Q(
                user_permissions__content_type__app_label=app_label,
                user_permissions__codename=codename,
            )
            | models.Q(
                groups__permissions__content_type__app_label=app_label,
                groups__permissions__codename=codename,
            )
        )
        .distinct()
    )


def create_notification(
    *,
    recipient,
    title,
    event_type,
    module,
    message="",
    actor=None,
    severity="info",
    link="",
    source_app="",
    source_model="",
    source_id="",
    metadata=None,
    dedup_key=None,
):
    """
    Punto único para crear notificaciones de Book Express.

    Los módulos de negocio deben llamar este servicio en lugar de crear
    Notification directamente. Así podremos añadir canales, auditoría,
    preferencias o colas en el futuro sin reescribir CRM/ERP.
    """
    if not recipient or not recipient.is_active:
        return None

    payload = {
        "actor": actor,
        "title": title,
        "message": message,
        "event_type": event_type,
        "module": module,
        "severity": severity,
        "link": link,
        "source_app": source_app,
        "source_model": source_model,
        "source_id": str(source_id or ""),
        "metadata": metadata or {},
    }

    if dedup_key:
        notification, _ = Notification.objects.get_or_create(
            recipient=recipient,
            dedup_key=dedup_key,
            defaults=payload,
        )
        return notification

    return Notification.objects.create(
        recipient=recipient,
        **payload,
    )


@transaction.atomic
def create_notifications_for_users(
    *,
    recipients: Iterable,
    title,
    event_type,
    module,
    message="",
    actor=None,
    severity="info",
    link="",
    source_app="",
    source_model="",
    source_id="",
    metadata=None,
    dedup_key_prefix=None,
    exclude_user=None,
):
    """
    Crea la misma notificación para varios usuarios activos.

    Se eliminan destinatarios duplicados y opcionalmente se excluye al actor
    para evitar avisos del tipo "te asignaste una tarea".
    """
    recipient_ids = {
        user.id
        for user in recipients
        if user
        and user.is_active
        and (not exclude_user or user.id != exclude_user.id)
    }

    if not recipient_ids:
        return []

    users = User.objects.filter(
        id__in=recipient_ids,
        is_active=True,
    )

    notifications = []

    for recipient in users:
        dedup_key = None

        if dedup_key_prefix:
            dedup_key = f"{dedup_key_prefix}:user:{recipient.id}"

        notification = create_notification(
            recipient=recipient,
            title=title,
            event_type=event_type,
            module=module,
            message=message,
            actor=actor,
            severity=severity,
            link=link,
            source_app=source_app,
            source_model=source_model,
            source_id=source_id,
            metadata=metadata,
            dedup_key=dedup_key,
        )

        if notification:
            notifications.append(notification)

    return notifications


def resolve_notifications_for_source(
    *,
    source_app,
    source_model=None,
    source_id=None,
    related_metadata=None,
):
    """
    Marca como resueltas las notificaciones asociadas a un objeto de negocio.

    Separa el estado operacional (resuelto) del estado de lectura. Esto permite
    conservar el historial sin mantener avisos cerrados como pendientes.
    """
    if not source_app:
        return 0

    queryset = Notification.objects.filter(
        source_app=source_app,
        is_resolved=False,
    )

    source_query = Q()
    has_source_query = False

    if source_model:
        source_query &= Q(source_model=source_model)
        has_source_query = True

    if source_id is not None:
        source_query &= Q(source_id=str(source_id))
        has_source_query = True

    metadata_query = Q()
    has_metadata_query = False

    for key, value in (related_metadata or {}).items():
        metadata_query &= Q(**{f"metadata__{key}": value})
        has_metadata_query = True

    if has_source_query and has_metadata_query:
        queryset = queryset.filter(source_query | metadata_query)
    elif has_source_query:
        queryset = queryset.filter(source_query)
    elif has_metadata_query:
        queryset = queryset.filter(metadata_query)
    else:
        return 0

    now = timezone.now()

    return queryset.update(
        is_resolved=True,
        resolved_at=now,
        updated_at=now,
    )
