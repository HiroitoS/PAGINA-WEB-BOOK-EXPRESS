from datetime import timedelta

from django.utils import timezone

from notifications.models import Notification
from notifications.services import create_notification

from .models import Reminder


UPCOMING_WINDOW = timedelta(minutes=30)
DUE_GRACE_WINDOW = timedelta(minutes=10)
OVERDUE_ALERT_WINDOW = timedelta(hours=24)

REMINDER_ALERT_EVENT_TYPES = (
    "workspace.reminder_upcoming",
    "workspace.reminder_due",
    "workspace.reminder_overdue",
)


def _get_alert_stage(reminder, now):
    delta = reminder.remind_at - now

    if timedelta(0) < delta <= UPCOMING_WINDOW:
        return "upcoming"

    if -DUE_GRACE_WINDOW <= delta <= timedelta(0):
        return "due"

    if -OVERDUE_ALERT_WINDOW <= delta < -DUE_GRACE_WINDOW:
        return "overdue"

    return None


def _get_alert_payload(reminder, stage):
    local_remind_at = timezone.localtime(reminder.remind_at)
    time_label = local_remind_at.strftime("%d/%m/%Y %H:%M")

    if stage == "upcoming":
        return {
            "title": "Recordatorio próximo",
            "message": (
                f'\"{reminder.title}\" está programado para {time_label}.'
            ),
            "severity": "info",
        }

    if stage == "due":
        return {
            "title": "Recordatorio para ahora",
            "message": (
                f'\"{reminder.title}\" corresponde atenderlo ahora.'
            ),
            "severity": "warning",
        }

    return {
        "title": "Recordatorio vencido",
        "message": (
            f'\"{reminder.title}\" sigue pendiente desde {time_label}.'
        ),
        "severity": "error",
    }


def _get_alert_dedup_key(reminder, stage):
    schedule_key = reminder.remind_at.isoformat()

    return (
        f"workspace:reminder:{reminder.id}:alert:"
        f"{stage}:{schedule_key}"
    )


def _resolve_stale_alerts(reminder, *, recipient, current_dedup_key, now):
    return (
        Notification.objects
        .filter(
            recipient=recipient,
            source_app="workspaces",
            source_model="Reminder",
            source_id=str(reminder.id),
            event_type__in=REMINDER_ALERT_EVENT_TYPES,
            is_resolved=False,
        )
        .exclude(dedup_key=current_dedup_key)
        .update(
            is_resolved=True,
            resolved_at=now,
            updated_at=now,
        )
    )


def resolve_reminder_alert_notifications(reminder):
    """
    Cierra únicamente las alertas temporales de un recordatorio.

    La notificación de asignación se conserva como historial; completar,
    reprogramar, reasignar o eliminar el recordatorio no debe borrarla.
    """
    if not reminder or not reminder.pk:
        return 0

    now = timezone.now()

    return Notification.objects.filter(
        source_app="workspaces",
        source_model="Reminder",
        source_id=str(reminder.id),
        event_type__in=REMINDER_ALERT_EVENT_TYPES,
        is_resolved=False,
    ).update(
        is_resolved=True,
        resolved_at=now,
        updated_at=now,
    )


def sync_reminder_alerts_for_user(user, *, now=None):
    """
    Materializa en la campana las alertas de recordatorios del usuario.

    Se ejecuta bajo demanda desde el polling ya existente del panel. Esto
    evita introducir un scheduler prematuro y mantiene el proceso idempotente
    mediante dedup_key.

    Reglas de ruido:
    - próximo: dentro de los siguientes 30 minutos;
    - para ahora: desde la hora programada hasta 10 minutos después;
    - vencido: desde 10 minutos hasta 24 horas después;
    - recordatorios más antiguos siguen visibles en ToDo, pero no generan
      una avalancha de avisos cuando el usuario vuelve a conectarse.
    """
    if (
        not user
        or not user.is_authenticated
        or not user.is_active
    ):
        return {
            "evaluated": 0,
            "active_alerts": 0,
        }

    now = now or timezone.now()
    window_start = now - OVERDUE_ALERT_WINDOW
    window_end = now + UPCOMING_WINDOW

    reminders = list(
        Reminder.objects
        .select_related("group", "task", "event")
        .filter(
            user=user,
            status__in=["pending", "seen"],
            remind_at__gte=window_start,
            remind_at__lte=window_end,
        )
        .order_by("remind_at", "id")
    )

    active_alerts = 0

    for reminder in reminders:
        stage = _get_alert_stage(reminder, now)

        if not stage:
            continue

        dedup_key = _get_alert_dedup_key(reminder, stage)

        _resolve_stale_alerts(
            reminder,
            recipient=user,
            current_dedup_key=dedup_key,
            now=now,
        )

        payload = _get_alert_payload(reminder, stage)
        notification = create_notification(
            recipient=user,
            title=payload["title"],
            message=payload["message"],
            event_type=f"workspace.reminder_{stage}",
            module="todo",
            severity=payload["severity"],
            link="/admin/workspace/reminders",
            source_app="workspaces",
            source_model="Reminder",
            source_id=reminder.id,
            metadata={
                "reminder_id": reminder.id,
                "reminder_title": reminder.title,
                "remind_at": reminder.remind_at.isoformat(),
                "alert_stage": stage,
                "group_id": reminder.group_id,
                "task_id": reminder.task_id,
                "event_id": reminder.event_id,
            },
            dedup_key=dedup_key,
        )

        if notification.is_resolved:
            notification.is_resolved = False
            notification.resolved_at = None
            notification.is_read = False
            notification.read_at = None
            notification.save(
                update_fields=[
                    "is_resolved",
                    "resolved_at",
                    "is_read",
                    "read_at",
                    "updated_at",
                ]
            )

        active_alerts += 1

    return {
        "evaluated": len(reminders),
        "active_alerts": active_alerts,
    }
