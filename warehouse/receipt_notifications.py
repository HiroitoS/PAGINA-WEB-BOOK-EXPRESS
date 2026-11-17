"""Avisos operativos de recepción; solo tras cambios confirmados.

No se envían correos sin SMTP/remitente y activación explícita.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from notifications.models import Notification

from notifications.services import (
    create_notifications_for_users, get_active_users_with_permission,
)

logger = logging.getLogger(__name__)
RECEIPT_URL = "/admin/erp/almacen/recepciones"


def _receipt_link(receipt):
    return f"{RECEIPT_URL}?recepcion={receipt.pk}"


def _close_approval_notice(receipt):
    # Una notificación ya atendida se conserva, pero no queda como tarea pendiente.
    Notification.objects.filter(
        source_app="warehouse", source_model="GoodsReceipt",
        source_id=str(receipt.pk),
        event_type="warehouse.receipt_approval_requested",
        is_resolved=False,
    ).update(is_resolved=True, resolved_at=timezone.now())


def avisar_devolucion_recepcion(receipt, actor, reason):
    _close_approval_notice(receipt)
    create_notifications_for_users(
        recipients=[receipt.created_by],
        title="Recepción devuelta para corrección",
        event_type="warehouse.receipt_returned", module="warehouse",
        message=(
            f"{receipt.provider.name}, documento {receipt.document_number}: "
            f"la jefatura solicita una corrección. Motivo: {reason}"
        ),
        actor=actor, severity="warning", link=_receipt_link(receipt),
        source_app="warehouse", source_model="GoodsReceipt", source_id=receipt.pk,
        dedup_key_prefix=f"wh:receipt:{receipt.pk}:returned:{receipt.events.filter(action='returned').count()}",
        exclude_user=actor,
    )



def _destinatarios_administracion():
    candidates = {
        user.pk: user
        for code in (
            "warehouse.view_receiving", "purchasing.view_purchasing",
        )
        for user in get_active_users_with_permission(code)
    }
    return list(candidates.values())


def _asesores_de_pedidos(receipt):
    # Un mismo documento puede agrupar varios colegios/adopciones.
    users = {}
    for row in receipt.lines.select_related(
        "order_item__order__adoption__opportunity__owner",
    ):
        adoption = row.order_item.order.adoption
        if adoption and adoption.opportunity.owner_id:
            user = adoption.opportunity.owner
            if user.is_active:
                users[user.pk] = user
    return list(users.values())


def _correo_habilitado():
    return bool(
        getattr(settings, "ERP_WAREHOUSE_EMAIL_ALERTS_ENABLED", False)
        and getattr(settings, "DEFAULT_FROM_EMAIL", "")
        and getattr(settings, "EMAIL_HOST", "")
    )


def _programar_correo(*, destinatarios, subject, body):
    if not _correo_habilitado():
        return
    emails = sorted({user.email.strip() for user in destinatarios if user.email and "@" in user.email})
    if not emails:
        return

    def enviar():
        try:
            send_mail(
                subject, body, settings.DEFAULT_FROM_EMAIL, emails,
                fail_silently=False,
            )
        except Exception:
            logger.exception("No se pudo enviar aviso de recepción por correo")

    transaction.on_commit(enviar)


def avisar_solicitud_aprobacion(receipt, actor):
    users = list(get_active_users_with_permission("warehouse.validate_receiving"))
    create_notifications_for_users(
        recipients=users, title="Recepción pendiente de aprobación",
        event_type="warehouse.receipt_approval_requested", module="warehouse",
        message=f"{receipt.provider.name}: documento {receipt.document_number} pendiente de revisión.",
        actor=actor, severity="info", link=_receipt_link(receipt),
        source_app="warehouse", source_model="GoodsReceipt",
        source_id=receipt.pk, dedup_key_prefix=f"wh:receipt:{receipt.pk}:submitted:{receipt.events.filter(action='submitted').count()}",
        exclude_user=actor,
    )
    _programar_correo(
        destinatarios=[u for u in users if u.pk != actor.pk],
        subject=f"Book Express: recepción pendiente de aprobación #{receipt.pk}",
        body=f"Editorial: {receipt.provider.name}\nDocumento: {receipt.document_number}\nRevisar en el panel de Almacén.",
    )


def avisar_recepcion_validada(receipt, actor):
    _close_approval_notice(receipt)
    admin = _destinatarios_administracion()
    advisors = _asesores_de_pedidos(receipt)
    rows = list(receipt.lines.select_related("order_item__order"))
    accepted = sum(row.quantity_accepted + row.quantity_extra for row in rows)
    observed = sum(row.quantity_observed for row in rows)
    missing_guide = sum(max(0, (row.quantity_documented or 0) - row.quantity_arrived) for row in rows)
    message = (
        f"{receipt.provider.name}, documento {receipt.document_number}: "
        f"{accepted} unidades conformes ingresadas. "
        f"{observed} observadas y {missing_guide} faltantes frente al documento."
    )
    create_notifications_for_users(
        recipients=[*admin, *advisors], title="Nueva mercadería ingresada a Inventario",
        event_type="warehouse.receipt_validated", module="warehouse",
        message=message, actor=actor, severity="success", link=_receipt_link(receipt),
        source_app="warehouse", source_model="GoodsReceipt", source_id=receipt.pk,
        dedup_key_prefix=f"wh:receipt:{receipt.pk}:validated",
    )
    if observed or missing_guide:
        create_notifications_for_users(
            recipients=[*admin, *advisors],
            title="Diferencia de mercadería: requiere seguimiento",
            event_type="warehouse.receipt_difference", module="warehouse",
            message=message, actor=actor, severity="warning", link=_receipt_link(receipt),
            source_app="warehouse", source_model="GoodsReceipt", source_id=receipt.pk,
            dedup_key_prefix=f"wh:receipt:{receipt.pk}:difference",
        )
    _programar_correo(
        destinatarios=[*admin, *advisors],
        subject=f"Book Express: ingreso de mercadería {receipt.provider.name} ({receipt.document_number})",
        body=message + "\nConsulta las cantidades por colegio y pedido en Recepción de mercadería.",
    )
