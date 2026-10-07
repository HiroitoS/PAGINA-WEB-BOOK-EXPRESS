from django.contrib.auth import get_user_model
from django.db.models import Count, Sum

from crm.models import (
    Adoption,
    AdoptionItem,
    CommercialActivity,
    CommercialProjection,
    CommercialProjectionItem,
    CommercialTeamMembership,
    PipelineStage,
)
from crm.selectors import (
    visible_commercial_activities_queryset,
    visible_opportunities_queryset,
    visible_schools_queryset,
)


REPORT_ACTIVITY_TYPES = (
    CommercialActivity.ActivityType.CALL,
    CommercialActivity.ActivityType.VISIT,
    CommercialActivity.ActivityType.COLD_VISIT,
    CommercialActivity.ActivityType.PRESENTATION,
    CommercialActivity.ActivityType.MEETING,
    CommercialActivity.ActivityType.FOLLOW_UP,
)


def _conversion_rate(won, lost):
    closed = won + lost

    if closed <= 0:
        return 0

    return round((won / closed) * 100, 1)


def build_advisor_commercial_report(
    *,
    user,
    date_from,
    date_to,
    campaign_id=None,
    team_id=None,
    owner_id=None,
):
    schools = visible_schools_queryset(user)
    opportunity_scope = visible_opportunities_queryset(user)
    activities = visible_commercial_activities_queryset(user)

    if team_id is not None:
        schools = schools.filter(team_id=team_id)
        opportunity_scope = opportunity_scope.filter(team_id=team_id)
        activities = activities.filter(school__team_id=team_id)

    if campaign_id is not None:
        opportunity_scope = opportunity_scope.filter(
            campaign_id=campaign_id
        )

    current_adoptions = Adoption.objects.filter(
        opportunity__in=opportunity_scope,
        is_current=True,
    )

    opportunities = opportunity_scope

    if owner_id is not None:
        schools = schools.filter(owner_id=owner_id)
        opportunities = opportunities.filter(owner_id=owner_id)
        activities = activities.filter(performed_by_id=owner_id)
        current_adoptions = current_adoptions.filter(
            advisor_id=owner_id
        )

    activities = activities.filter(
        occurred_at__date__gte=date_from,
        occurred_at__date__lte=date_to,
    )

    current_projections = CommercialProjection.objects.filter(
        opportunity__in=opportunities,
        is_current=True,
    )

    school_counts = {
        row["owner_id"]: row["total"]
        for row in (
            schools
            .exclude(owner_id__isnull=True)
            .values("owner_id")
            .annotate(total=Count("id"))
        )
    }

    opportunity_counts = {}
    for row in (
        opportunities
        .exclude(owner_id__isnull=True)
        .values("owner_id", "stage__category")
        .annotate(total=Count("id"))
    ):
        owner_counts = opportunity_counts.setdefault(
            row["owner_id"],
            {
                PipelineStage.Category.OPEN: 0,
                PipelineStage.Category.WON: 0,
                PipelineStage.Category.LOST: 0,
            },
        )
        owner_counts[row["stage__category"]] = row["total"]

    activity_totals = {}
    activity_breakdown = {}

    for row in (
        activities
        .exclude(performed_by_id__isnull=True)
        .values("performed_by_id", "activity_type")
        .annotate(total=Count("id"))
    ):
        user_id = row["performed_by_id"]
        activity_totals[user_id] = (
            activity_totals.get(user_id, 0) + row["total"]
        )
        activity_breakdown.setdefault(user_id, {})[
            row["activity_type"]
        ] = row["total"]

    projection_counts = {
        row["opportunity__owner_id"]: row["total"]
        for row in (
            current_projections
            .exclude(opportunity__owner_id__isnull=True)
            .values("opportunity__owner_id")
            .annotate(total=Count("id"))
        )
    }
    projection_units = {
        row["projection__opportunity__owner_id"]: row["total"] or 0
        for row in (
            CommercialProjectionItem.objects
            .filter(projection__in=current_projections)
            .exclude(
                projection__opportunity__owner_id__isnull=True
            )
            .values("projection__opportunity__owner_id")
            .annotate(total=Sum("quantity"))
        )
    }

    adoption_counts = {
        row["advisor_id"]: row["total"]
        for row in (
            current_adoptions
            .exclude(advisor_id__isnull=True)
            .values("advisor_id")
            .annotate(total=Count("id"))
        )
    }
    adoption_units = {
        row["adoption__advisor_id"]: row["total"] or 0
        for row in (
            AdoptionItem.objects
            .filter(adoption__in=current_adoptions)
            .exclude(adoption__advisor_id__isnull=True)
            .values("adoption__advisor_id")
            .annotate(total=Sum("quantity"))
        )
    }

    advisor_ids = set(school_counts)
    advisor_ids.update(opportunity_counts)
    advisor_ids.update(activity_totals)
    advisor_ids.update(projection_counts)
    advisor_ids.update(adoption_counts)

    User = get_user_model()
    users = {
        advisor.id: advisor
        for advisor in (
            User.objects
            .filter(id__in=advisor_ids)
            .select_related("book_express_profile")
        )
    }

    team_names = {}

    for membership in (
        CommercialTeamMembership.objects
        .filter(
            user_id__in=advisor_ids,
            is_active=True,
            team__is_active=True,
            role=CommercialTeamMembership.Role.ADVISOR,
        )
        .select_related("team")
        .order_by("team__name")
    ):
        team_names.setdefault(membership.user_id, []).append(
            membership.team.name
        )

    advisor_rows = []

    for advisor_id in advisor_ids:
        advisor = users.get(advisor_id)

        if advisor is None:
            continue

        counts = opportunity_counts.get(
            advisor_id,
            {
                PipelineStage.Category.OPEN: 0,
                PipelineStage.Category.WON: 0,
                PipelineStage.Category.LOST: 0,
            },
        )
        won = counts.get(PipelineStage.Category.WON, 0)
        lost = counts.get(PipelineStage.Category.LOST, 0)
        full_name = advisor.get_full_name().strip()

        advisor_rows.append(
            {
                "advisor_id": advisor_id,
                "advisor_name": (
                    full_name or advisor.get_username()
                ),
                "teams": team_names.get(advisor_id, []),
                "schools": school_counts.get(advisor_id, 0),
                "activities": activity_totals.get(advisor_id, 0),
                "activity_counts": {
                    activity_type: (
                        activity_breakdown
                        .get(advisor_id, {})
                        .get(activity_type, 0)
                    )
                    for activity_type in REPORT_ACTIVITY_TYPES
                },
                "open_opportunities": counts.get(
                    PipelineStage.Category.OPEN,
                    0,
                ),
                "won_opportunities": won,
                "lost_opportunities": lost,
                "current_projections": projection_counts.get(
                    advisor_id,
                    0,
                ),
                "projected_units": projection_units.get(
                    advisor_id,
                    0,
                ),
                "current_adoptions": adoption_counts.get(
                    advisor_id,
                    0,
                ),
                "adopted_units": adoption_units.get(
                    advisor_id,
                    0,
                ),
                "conversion_rate": _conversion_rate(
                    won,
                    lost,
                ),
            }
        )

    advisor_rows.sort(
        key=lambda row: row["advisor_name"].casefold()
    )

    summary_open = opportunities.filter(
        stage__category=PipelineStage.Category.OPEN,
    ).count()
    summary_won = opportunities.filter(
        stage__category=PipelineStage.Category.WON,
    ).count()
    summary_lost = opportunities.filter(
        stage__category=PipelineStage.Category.LOST,
    ).count()

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

    return {
        "filters": {
            "campaign": campaign_id,
            "team": team_id,
            "owner": owner_id,
            "date_from": date_from,
            "date_to": date_to,
        },
        "summary": {
            "schools": schools.count(),
            "activities": activities.count(),
            "open_opportunities": summary_open,
            "won_opportunities": summary_won,
            "lost_opportunities": summary_lost,
            "current_projections": current_projections.count(),
            "projected_units": projected_units,
            "current_adoptions": current_adoptions.count(),
            "adopted_units": adopted_units,
            "conversion_rate": _conversion_rate(
                summary_won,
                summary_lost,
            ),
        },
        "unassigned": {
            "schools": schools.filter(
                owner_id__isnull=True,
            ).count(),
            "opportunities": opportunities.filter(
                owner_id__isnull=True,
            ).count(),
        },
        "advisors": advisor_rows,
    }
