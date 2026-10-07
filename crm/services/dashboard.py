from datetime import timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from crm.models import (
    Adoption,
    AdoptionItem,
    CommercialActivity,
    CommercialProjection,
    CommercialProjectionItem,
    PipelineStage,
)
from crm.selectors import (
    visible_commercial_activities_queryset,
    visible_opportunities_queryset,
    visible_schools_queryset,
)


DASHBOARD_ACTIVITY_TYPES = (
    CommercialActivity.ActivityType.CALL,
    CommercialActivity.ActivityType.VISIT,
    CommercialActivity.ActivityType.COLD_VISIT,
    CommercialActivity.ActivityType.PRESENTATION,
    CommercialActivity.ActivityType.MEETING,
    CommercialActivity.ActivityType.FOLLOW_UP,
)


def _percentage(numerator, denominator):
    if not denominator:
        return 0

    return round((numerator / denominator) * 100, 1)


def build_crm_dashboard_summary(*, user):
    schools = visible_schools_queryset(user)
    opportunities = visible_opportunities_queryset(user)
    activities = visible_commercial_activities_queryset(user)

    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    trend_start = today - timedelta(days=6)

    open_opportunities = opportunities.filter(
        stage__category=PipelineStage.Category.OPEN,
    )
    won_opportunities = opportunities.filter(
        stage__category=PipelineStage.Category.WON,
    )
    lost_opportunities = opportunities.filter(
        stage__category=PipelineStage.Category.LOST,
    )

    open_count = open_opportunities.count()
    won_count = won_opportunities.count()
    lost_count = lost_opportunities.count()

    opportunities_without_activity = open_opportunities.filter(
        last_activity_at__isnull=True,
    ).count()

    week_activities = activities.filter(
        occurred_at__date__gte=week_start,
        occurred_at__date__lte=today,
    )
    activity_counts = {
        activity_type: week_activities.filter(
            activity_type=activity_type,
        ).count()
        for activity_type in DASHBOARD_ACTIVITY_TYPES
    }

    trend_totals = {
        item["day"]: item["total"]
        for item in (
            activities
            .filter(
                occurred_at__date__gte=trend_start,
                occurred_at__date__lte=today,
            )
            .annotate(day=TruncDate("occurred_at"))
            .values("day")
            .annotate(total=Count("id"))
            .order_by("day")
        )
    }
    activity_trend = [
        {
            "date": current_date.isoformat(),
            "total": trend_totals.get(current_date, 0),
        }
        for current_date in (
            trend_start + timedelta(days=offset)
            for offset in range(7)
        )
    ]

    stages = list(
        opportunities
        .values(
            "stage_id",
            "stage__code",
            "stage__name",
            "stage__order",
            "stage__category",
        )
        .annotate(total=Count("id"))
        .order_by("stage__order", "stage__name")
    )

    current_projections = CommercialProjection.objects.filter(
        opportunity__in=opportunities,
        is_current=True,
    )
    current_adoptions = Adoption.objects.filter(
        opportunity__in=opportunities,
        is_current=True,
    )

    projected_units = (
        CommercialProjectionItem.objects
        .filter(projection__in=current_projections)
        .aggregate(total=Sum("quantity"))
        .get("total")
        or 0
    )
    adopted_units = (
        AdoptionItem.objects
        .filter(adoption__in=current_adoptions)
        .aggregate(total=Sum("quantity"))
        .get("total")
        or 0
    )

    closed_count = won_count + lost_count

    return {
        "schools": schools.filter(is_active=True).count(),
        "open_opportunities": open_count,
        "won_opportunities": won_count,
        "lost_opportunities": lost_count,
        "opportunities_without_activity": (
            opportunities_without_activity
        ),
        "activities_today": activities.filter(
            occurred_at__date=today,
        ).count(),
        "activities_week": sum(activity_counts.values()),
        "activity_week_start": week_start,
        "activity_week_end": today,
        "activity_counts": activity_counts,
        "activity_trend": activity_trend,
        "stages": stages,
        "current_projections": current_projections.count(),
        "current_adoptions": current_adoptions.count(),
        "projected_units": projected_units,
        "adopted_units": adopted_units,
        "unit_conversion_rate": _percentage(
            adopted_units,
            projected_units,
        ),
        "closure_conversion_rate": _percentage(
            won_count,
            closed_count,
        ),
        "follow_up_coverage": _percentage(
            open_count - opportunities_without_activity,
            open_count,
        ),
    }
