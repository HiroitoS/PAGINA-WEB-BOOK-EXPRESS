from crm.models import CommercialActivity


def _activity_queryset():
    return (
        CommercialActivity.objects
        .select_related(
            "school",
            "opportunity",
            "contact",
            "performed_by",
            "created_by",
        )
        .order_by("-occurred_at", "-id")
    )


def commercial_activities_for_school(school):
    return _activity_queryset().filter(school=school)


def commercial_activities_for_opportunity(opportunity):
    return _activity_queryset().filter(opportunity=opportunity)
