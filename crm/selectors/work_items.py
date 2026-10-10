from django.db.models import Q

from accounts.permissions import usuario_es_administrador
from crm.models import CRMWorkItemLink


def _work_item_queryset(*, user):
    queryset = (
        CRMWorkItemLink.objects
        .select_related(
            "school",
            "contact",
            "opportunity",
            "origin_activity",
            "task",
            "event",
            "reminder",
            "created_by",
        )
        .order_by("-created_at")
    )

    if usuario_es_administrador(user):
        return queryset

    # El acceso al CRM no permite exponer una tarea privada de otro asesor,
    # ni un recordatorio asociado a esa tarea.
    return queryset.filter(
        Q(task__isnull=True)
        | Q(task__is_private=False)
        | Q(task__created_by=user)
        | Q(task__assigned_to=user)
    ).filter(
        Q(reminder__task__isnull=True)
        | Q(reminder__task__is_private=False)
        | Q(reminder__task__created_by=user)
        | Q(reminder__task__assigned_to=user)
    )


def work_items_for_school(school, *, user):
    return _work_item_queryset(user=user).filter(school=school)


def work_items_for_contact(contact, *, user):
    return _work_item_queryset(user=user).filter(contact=contact)


def work_items_for_opportunity(opportunity, *, user):
    return _work_item_queryset(user=user).filter(opportunity=opportunity)
