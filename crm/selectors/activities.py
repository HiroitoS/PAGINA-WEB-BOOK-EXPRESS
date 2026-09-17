from crm.models import CommercialActivity


def commercial_activities_for_opportunity(opportunity):
    return (
        CommercialActivity.objects
        .filter(opportunity=opportunity)
        .select_related(
            "contact",
            "performed_by",
            "created_by",
        )
        .order_by("-occurred_at", "-id")
    )
