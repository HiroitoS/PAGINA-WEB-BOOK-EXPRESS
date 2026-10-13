"""Registro centralizado de cambios de planificación de tareas de ToDo."""

from django.utils import timezone

from .models import Task, TaskChangeHistory


AUDITED_TASK_FIELDS = {
    "start_at": "Fecha de inicio",
    "due_at": "Fecha límite",
    "reminder_at": "Recordatorio",
    "assigned_to": "Responsable",
    "priority": "Prioridad",
}


def snapshot_task_plan(task):
    """Captura los valores originales antes de guardar la actualización."""
    return {
        field: getattr(task, field)
        for field in AUDITED_TASK_FIELDS
    }


def _display_value(field, value):
    if field == "assigned_to":
        if not value:
            return "Sin asignar"
        return value.get_full_name().strip() or value.username

    if field in {"start_at", "due_at", "reminder_at"}:
        if not value:
            return "Sin fecha"
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d/%m/%Y %H:%M")

    if field == "priority":
        return dict(Task.PRIORITY_CHOICES).get(value, str(value))

    return str(value) if value is not None else ""


def record_task_plan_change(*, task, previous, actor):
    """Crea una sola entrada por actualización real; sin entradas ficticias."""
    changes = []

    for field, label in AUDITED_TASK_FIELDS.items():
        old = previous[field]
        new = getattr(task, field)
        if old == new:
            continue

        entry = {
            "field": field,
            "label": label,
            "old": _display_value(field, old),
            "new": _display_value(field, new),
        }
        if field == "assigned_to":
            entry["old_id"] = old.pk if old else None
            entry["new_id"] = new.pk if new else None
        changes.append(entry)

    if not changes:
        return None

    return TaskChangeHistory.objects.create(
        task=task,
        changed_by=actor,
        changes=changes,
    )
