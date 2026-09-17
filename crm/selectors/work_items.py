from crm.models import CRMWorkItemLink


def work_items_for_opportunity(opportunity):
    return (
        CRMWorkItemLink.objects
        .filter(opportunity=opportunity)
        .select_related(
            "origin_activity",
            "task",
            "event",
            "reminder",
            "created_by",
        )
        .order_by("-created_at")
    )
