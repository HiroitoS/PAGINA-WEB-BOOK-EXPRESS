import logging
from functools import partial

from django.db import transaction

from notifications.services import (
    create_notification,
    create_notifications_for_users,
    get_active_users_with_permission,
    resolve_notifications_for_source,
)


logger = logging.getLogger(__name__)


def _run_notification_callback(callback):
    try:
        callback()
    except Exception:
        logger.exception(
            "No se pudo crear una notificación de solicitudes."
        )


def _schedule(callback):
    transaction.on_commit(
        partial(_run_notification_callback, callback)
    )


def _display_name(user):
    if not user:
        return ""

    full_name = user.get_full_name().strip()
    return full_name or user.username


def notify_new_contact_request(contact_request):
    """
    Una solicitud nueva se avisa a quienes realmente pueden gestionarla,
    no a todos los usuarios con acceso de solo lectura.
    """
    recipients = get_active_users_with_permission(
        "inquiries.manage_inquiries"
    )

    def callback():
        create_notifications_for_users(
            recipients=recipients,
            title="Nueva solicitud web",
            message=(
                f"{contact_request.full_name} envió una nueva solicitud "
                f"de información."
            ),
            event_type="inquiries.request_created",
            module="solicitudes",
            severity=(
                "warning"
                if contact_request.priority in ["high", "urgent"]
                else "info"
            ),
            link="/admin/solicitudes",
            source_app="inquiries",
            source_model="ContactRequest",
            source_id=contact_request.id,
            metadata={
                "request_id": contact_request.id,
                "source": contact_request.source,
                "priority": contact_request.priority,
                "product_id": contact_request.product_id,
                "provider_id": contact_request.provider_id,
            },
            dedup_key_prefix=(
                f"inquiries:request:{contact_request.id}:created"
            ),
        )

    _schedule(callback)


def notify_contact_request_assigned(
    contact_request,
    actor,
    previous_assignee=None,
):
    recipient = contact_request.assigned_to

    if not recipient:
        return

    if recipient.id == getattr(actor, "id", None):
        return

    if (
        previous_assignee
        and previous_assignee.id == recipient.id
    ):
        return

    actor_name = _display_name(actor)
    is_reassignment = previous_assignee is not None

    def callback():
        create_notification(
            recipient=recipient,
            actor=actor,
            title=(
                "Solicitud reasignada"
                if is_reassignment
                else "Solicitud asignada"
            ),
            message=(
                f"{actor_name} te asignó la solicitud de "
                f"{contact_request.full_name}."
            ),
            event_type="inquiries.request_assigned",
            module="solicitudes",
            severity="info",
            link="/admin/solicitudes",
            source_app="inquiries",
            source_model="ContactRequest",
            source_id=contact_request.id,
            metadata={
                "request_id": contact_request.id,
                "priority": contact_request.priority,
                "status": contact_request.status,
            },
            dedup_key=(
                f"inquiries:request:{contact_request.id}:assigned:"
                f"{recipient.id}:{contact_request.updated_at.isoformat()}"
            ),
        )

    _schedule(callback)


def notify_contact_request_status_changed(
    contact_request,
    actor,
    old_status,
):
    recipient = contact_request.assigned_to

    if not recipient:
        return

    if recipient.id == getattr(actor, "id", None):
        return

    actor_name = _display_name(actor)

    def callback():
        create_notification(
            recipient=recipient,
            actor=actor,
            title="Estado de solicitud actualizado",
            message=(
                f"{actor_name} cambió el estado de la solicitud de "
                f"{contact_request.full_name}."
            ),
            event_type="inquiries.request_status_changed",
            module="solicitudes",
            severity="info",
            link="/admin/solicitudes",
            source_app="inquiries",
            source_model="ContactRequest",
            source_id=contact_request.id,
            metadata={
                "request_id": contact_request.id,
                "old_status": old_status,
                "new_status": contact_request.status,
            },
            dedup_key=(
                f"inquiries:request:{contact_request.id}:status:"
                f"{contact_request.status}:"
                f"{contact_request.updated_at.isoformat()}"
            ),
        )

    _schedule(callback)


def notify_contact_request_comment_added(comment, actor):
    contact_request = comment.contact_request
    recipient = contact_request.assigned_to

    if not recipient:
        return

    if recipient.id == getattr(actor, "id", None):
        return

    actor_name = _display_name(actor)

    def callback():
        create_notification(
            recipient=recipient,
            actor=actor,
            title="Nuevo seguimiento en una solicitud",
            message=(
                f"{actor_name} registró seguimiento en la solicitud de "
                f"{contact_request.full_name}."
            ),
            event_type="inquiries.request_comment_added",
            module="solicitudes",
            severity="info",
            link="/admin/solicitudes",
            source_app="inquiries",
            source_model="ContactRequestComment",
            source_id=comment.id,
            metadata={
                "request_id": contact_request.id,
                "comment_id": comment.id,
                "action_type": comment.action_type,
            },
            dedup_key=(
                f"inquiries:comment:{comment.id}:"
                f"recipient:{recipient.id}"
            ),
        )

    _schedule(callback)


def resolve_contact_request_notifications(contact_request):
    def callback():
        resolve_notifications_for_source(
            source_app="inquiries",
            source_model="ContactRequest",
            source_id=contact_request.id,
            related_metadata={
                "request_id": contact_request.id,
            },
        )

    _schedule(callback)
