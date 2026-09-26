from crm.models import CRMWorkItemLink


def _work_item_queryset():
    return (
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


def work_items_for_school(school):
    return _work_item_queryset().filter(school=school)


def work_items_for_contact(contact):
    return _work_item_queryset().filter(contact=contact)


def work_items_for_opportunity(opportunity):
    return _work_item_queryset().filter(opportunity=opportunity)
