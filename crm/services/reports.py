from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Sum

from accounts.permissions import usuario_es_administrador
from crm.models import (
    Adoption,
    AdoptionItem,
    CommercialActivity,
    CommercialProjection,
    CommercialProjectionItem,
    CommercialQuotation,
    CommercialTeamMembership,
    PipelineStage,
    SchoolCampus,
    SchoolCommercialProfile,
)
from crm.selectors import (
    supervised_team_ids,
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
    advisor_ids.update(projection_counts)
    advisor_ids.update(adoption_counts)

    is_admin = usuario_es_administrador(user)
    supervised_ids = set()

    if not is_admin:
        supervised_ids = set(
            supervised_team_ids(user)
        )

    advisor_memberships = CommercialTeamMembership.objects.filter(
        is_active=True,
        user__is_active=True,
        team__is_active=True,
        role=CommercialTeamMembership.Role.ADVISOR,
    )

    if team_id is not None:
        if is_admin or team_id in supervised_ids:
            advisor_memberships = advisor_memberships.filter(
                team_id=team_id
            )
        else:
            advisor_memberships = advisor_memberships.none()
    elif not is_admin:
        advisor_memberships = advisor_memberships.filter(
            team_id__in=supervised_ids
        )

    if owner_id is not None:
        advisor_memberships = advisor_memberships.filter(
            user_id=owner_id
        )

    advisor_ids.update(
        advisor_memberships.values_list("user_id", flat=True)
    )

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

    visible_memberships = CommercialTeamMembership.objects.filter(
        user_id__in=advisor_ids,
        is_active=True,
        team__is_active=True,
        role=CommercialTeamMembership.Role.ADVISOR,
    )

    if team_id is not None:
        if is_admin or team_id in supervised_ids:
            visible_memberships = visible_memberships.filter(
                team_id=team_id
            )
        else:
            visible_memberships = visible_memberships.none()
    elif not is_admin:
        visible_memberships = visible_memberships.filter(
            team_id__in=supervised_ids
        )

    for membership in (
        visible_memberships
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


def _money_string(value):
    amount = Decimal(value or 0).quantize(Decimal("0.01"))
    return format(amount, "f")


def _report_opportunities(
    *,
    user,
    campaign_id=None,
    team_id=None,
    owner_id=None,
):
    opportunities = visible_opportunities_queryset(user)

    if campaign_id is not None:
        opportunities = opportunities.filter(campaign_id=campaign_id)

    if team_id is not None:
        opportunities = opportunities.filter(team_id=team_id)

    if owner_id is not None:
        opportunities = opportunities.filter(owner_id=owner_id)

    return opportunities


def build_editorial_commercial_report(
    *,
    user,
    campaign_id=None,
    team_id=None,
    owner_id=None,
):
    opportunity_scope = _report_opportunities(
        user=user,
        campaign_id=campaign_id,
        team_id=team_id,
        owner_id=None,
    )
    projection_opportunities = opportunity_scope

    if owner_id is not None:
        projection_opportunities = projection_opportunities.filter(
            owner_id=owner_id
        )

    current_projections = CommercialProjection.objects.filter(
        opportunity__in=projection_opportunities,
        is_current=True,
    )
    current_adoptions = Adoption.objects.filter(
        opportunity__in=opportunity_scope,
        is_current=True,
    )

    if owner_id is not None:
        current_adoptions = current_adoptions.filter(
            advisor_id=owner_id
        )

    editorials = {}

    def get_row(name):
        key = (name or "Sin editorial").strip() or "Sin editorial"

        if key not in editorials:
            editorials[key] = {
                "editorial": key,
                "projected_product_ids": set(),
                "projected_school_ids": set(),
                "projected_units": 0,
                "projected_reference_value": Decimal("0.00"),
                "adopted_product_ids": set(),
                "adopted_school_ids": set(),
                "adopted_units": 0,
                "adopted_value": Decimal("0.00"),
                "supplier_cost_total": Decimal("0.00"),
                "incentive_total": Decimal("0.00"),
                "contribution_total": Decimal("0.00"),
            }

        return editorials[key]

    projection_items = (
        CommercialProjectionItem.objects
        .filter(projection__in=current_projections)
        .values(
            "provider_name_snapshot",
            "product_id",
            "quantity",
            "unit_price",
            "projection__opportunity__school_id",
        )
    )

    for item in projection_items.iterator():
        row = get_row(item["provider_name_snapshot"])
        quantity = int(item["quantity"] or 0)
        unit_price = Decimal(item["unit_price"] or 0)

        row["projected_product_ids"].add(item["product_id"])
        row["projected_school_ids"].add(
            item["projection__opportunity__school_id"]
        )
        row["projected_units"] += quantity
        row["projected_reference_value"] += (
            unit_price * Decimal(quantity)
        )

    adoption_items = (
        AdoptionItem.objects
        .filter(adoption__in=current_adoptions)
        .values(
            "provider_name_snapshot",
            "product_id",
            "quantity",
            "school_price",
            "supplier_cost",
            "school_commission",
            "adoption__opportunity__school_id",
        )
    )

    for item in adoption_items.iterator():
        row = get_row(item["provider_name_snapshot"])
        quantity = int(item["quantity"] or 0)
        quantity_decimal = Decimal(quantity)
        school_price = Decimal(item["school_price"] or 0)
        supplier_cost = Decimal(item["supplier_cost"] or 0)
        incentive = Decimal(item["school_commission"] or 0)

        adopted_value = school_price * quantity_decimal
        supplier_total = supplier_cost * quantity_decimal
        incentive_total = incentive * quantity_decimal
        contribution = (
            adopted_value
            - supplier_total
            - incentive_total
        )

        row["adopted_product_ids"].add(item["product_id"])
        row["adopted_school_ids"].add(
            item["adoption__opportunity__school_id"]
        )
        row["adopted_units"] += quantity
        row["adopted_value"] += adopted_value
        row["supplier_cost_total"] += supplier_total
        row["incentive_total"] += incentive_total
        row["contribution_total"] += contribution

    rows = []

    for row in editorials.values():
        projected_units = row["projected_units"]
        adopted_units = row["adopted_units"]
        adopted_value = row["adopted_value"]
        contribution_total = row["contribution_total"]

        unit_conversion = (
            round((adopted_units / projected_units) * 100, 1)
            if projected_units > 0
            else 0
        )
        margin_percent = (
            (contribution_total / adopted_value * Decimal("100.00"))
            if adopted_value > 0
            else Decimal("0.00")
        )
        contribution_unit = (
            contribution_total / Decimal(adopted_units)
            if adopted_units > 0
            else Decimal("0.00")
        )

        rows.append(
            {
                "editorial": row["editorial"],
                "projected_products": len(
                    row["projected_product_ids"]
                ),
                "projected_schools": len(
                    row["projected_school_ids"]
                ),
                "projected_units": projected_units,
                "projected_reference_value": _money_string(
                    row["projected_reference_value"]
                ),
                "adopted_products": len(
                    row["adopted_product_ids"]
                ),
                "adopted_schools": len(
                    row["adopted_school_ids"]
                ),
                "adopted_units": adopted_units,
                "adopted_value": _money_string(adopted_value),
                "unit_conversion_rate": unit_conversion,
                "supplier_cost_total": _money_string(
                    row["supplier_cost_total"]
                ),
                "incentive_total": _money_string(
                    row["incentive_total"]
                ),
                "contribution_total": _money_string(
                    contribution_total
                ),
                "margin_percent": float(
                    margin_percent.quantize(Decimal("0.01"))
                ),
                "contribution_per_unit": _money_string(
                    contribution_unit
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -Decimal(row["contribution_total"]),
            row["editorial"].casefold(),
        )
    )

    total_projected_units = sum(
        row["projected_units"] for row in rows
    )
    total_adopted_units = sum(
        row["adopted_units"] for row in rows
    )
    total_projected_value = sum(
        Decimal(row["projected_reference_value"])
        for row in rows
    )
    total_adopted_value = sum(
        Decimal(row["adopted_value"])
        for row in rows
    )
    total_supplier_cost = sum(
        Decimal(row["supplier_cost_total"])
        for row in rows
    )
    total_incentive = sum(
        Decimal(row["incentive_total"])
        for row in rows
    )
    total_contribution = sum(
        Decimal(row["contribution_total"])
        for row in rows
    )
    total_margin = (
        total_contribution
        / total_adopted_value
        * Decimal("100.00")
        if total_adopted_value > 0
        else Decimal("0.00")
    )

    return {
        "filters": {
            "campaign": campaign_id,
            "team": team_id,
            "owner": owner_id,
        },
        "summary": {
            "editorials": len(rows),
            "projected_units": total_projected_units,
            "adopted_units": total_adopted_units,
            "projected_reference_value": _money_string(
                total_projected_value
            ),
            "adopted_value": _money_string(
                total_adopted_value
            ),
            "supplier_cost_total": _money_string(
                total_supplier_cost
            ),
            "incentive_total": _money_string(
                total_incentive
            ),
            "contribution_total": _money_string(
                total_contribution
            ),
            "margin_percent": float(
                total_margin.quantize(Decimal("0.01"))
            ),
        },
        "editorials": rows,
    }


def build_opportunity_commercial_report(
    *,
    user,
    campaign_id=None,
    team_id=None,
    owner_id=None,
):
    opportunities = (
        _report_opportunities(
            user=user,
            campaign_id=campaign_id,
            team_id=team_id,
            owner_id=owner_id,
        )
        .select_related(
            "school",
            "campaign",
            "team",
            "owner",
            "stage",
        )
        .order_by("school__name", "id")
    )
    opportunity_ids = list(
        opportunities.values_list("id", flat=True)
    )

    current_projections = CommercialProjection.objects.filter(
        opportunity_id__in=opportunity_ids,
        is_current=True,
    )
    current_adoptions = Adoption.objects.filter(
        opportunity_id__in=opportunity_ids,
        is_current=True,
    )

    projection_by_opportunity = {
        projection.opportunity_id: projection
        for projection in current_projections
    }
    projection_units = {
        row["projection__opportunity_id"]: row["total"] or 0
        for row in (
            CommercialProjectionItem.objects
            .filter(projection__in=current_projections)
            .values("projection__opportunity_id")
            .annotate(total=Sum("quantity"))
        )
    }
    adoption_units = {
        row["adoption__opportunity_id"]: row["total"] or 0
        for row in (
            AdoptionItem.objects
            .filter(adoption__in=current_adoptions)
            .values("adoption__opportunity_id")
            .annotate(total=Sum("quantity"))
        )
    }
    adoption_by_opportunity = {
        adoption.opportunity_id: adoption
        for adoption in current_adoptions
    }

    quotation_by_opportunity = {}

    for quotation in (
        CommercialQuotation.objects
        .filter(opportunity_id__in=opportunity_ids)
        .exclude(
            status=CommercialQuotation.Status.SUPERSEDED
        )
        .order_by("opportunity_id", "-version")
    ):
        quotation_by_opportunity.setdefault(
            quotation.opportunity_id,
            quotation,
        )

    rows = []

    for opportunity in opportunities:
        projection = projection_by_opportunity.get(opportunity.id)
        adoption = adoption_by_opportunity.get(opportunity.id)
        quotation = quotation_by_opportunity.get(opportunity.id)
        owner_name = ""

        if opportunity.owner_id:
            owner_name = (
                opportunity.owner.get_full_name().strip()
                or opportunity.owner.get_username()
            )

        rows.append(
            {
                "opportunity_id": opportunity.id,
                "school_id": opportunity.school_id,
                "school_name": opportunity.school.name,
                "campaign": opportunity.campaign.name,
                "team": (
                    opportunity.team.name
                    if opportunity.team_id
                    else ""
                ),
                "advisor": owner_name,
                "stage": opportunity.stage.name,
                "stage_category": opportunity.stage.category,
                "commercial_line": (
                    projection.get_commercial_line_display()
                    if projection
                    else ""
                ),
                "projected_units": projection_units.get(
                    opportunity.id,
                    0,
                ),
                "quotation_status": (
                    quotation.get_status_display()
                    if quotation
                    else ""
                ),
                "quotation_version": (
                    quotation.version if quotation else None
                ),
                "adoption_status": (
                    "Confirmada" if adoption else ""
                ),
                "adopted_units": adoption_units.get(
                    opportunity.id,
                    0,
                ),
                "last_activity_at": (
                    opportunity.last_activity_at
                    if opportunity.last_activity_at
                    else None
                ),
                "closed_at": (
                    opportunity.closed_at
                    if opportunity.closed_at
                    else None
                ),
            }
        )

    summary = {
        "opportunities": len(rows),
        "open": sum(
            1
            for row in rows
            if row["stage_category"]
            == PipelineStage.Category.OPEN
        ),
        "won": sum(
            1
            for row in rows
            if row["stage_category"]
            == PipelineStage.Category.WON
        ),
        "lost": sum(
            1
            for row in rows
            if row["stage_category"]
            == PipelineStage.Category.LOST
        ),
        "projected_units": sum(
            row["projected_units"] for row in rows
        ),
        "adopted_units": sum(
            row["adopted_units"] for row in rows
        ),
    }

    return {
        "filters": {
            "campaign": campaign_id,
            "team": team_id,
            "owner": owner_id,
        },
        "summary": summary,
        "opportunities": rows,
    }


def build_school_commercial_report(
    *,
    user,
    campaign_id=None,
    team_id=None,
    owner_id=None,
):
    schools = visible_schools_queryset(user)

    if team_id is not None:
        schools = schools.filter(team_id=team_id)

    if owner_id is not None:
        schools = schools.filter(owner_id=owner_id)

    school_objects = list(
        schools
        .select_related("team", "owner")
        .annotate(
            report_last_activity_at=Max(
                "commercial_activities__occurred_at"
            )
        )
        .order_by("name")
    )
    school_ids = [school.id for school in school_objects]

    campuses = {}
    for campus in (
        SchoolCampus.objects
        .filter(
            school_id__in=school_ids,
            is_active=True,
        )
        .order_by(
            "school_id",
            "-is_main",
            "sequence",
            "id",
        )
    ):
        campuses.setdefault(campus.school_id, campus)

    profiles = {}
    profile_queryset = (
        SchoolCommercialProfile.objects
        .filter(school_id__in=school_ids)
        .select_related("campaign")
        .order_by(
            "school_id",
            "-campaign__year",
            "-id",
        )
    )

    if campaign_id is not None:
        profile_queryset = profile_queryset.filter(
            campaign_id=campaign_id
        )

    for profile in profile_queryset:
        profiles.setdefault(profile.school_id, profile)

    school_rows = {}

    for school in school_objects:
        owner_name = ""

        if school.owner_id:
            owner_name = (
                school.owner.get_full_name().strip()
                or school.owner.get_username()
            )

        campus = campuses.get(school.id)
        profile = profiles.get(school.id)

        school_rows[school.id] = {
            "school_id": school.id,
            "school_name": school.name,
            "department": (
                campus.department
                if campus and campus.department
                else school.department
            ),
            "province": (
                campus.province
                if campus and campus.province
                else school.province
            ),
            "district": (
                campus.district
                if campus and campus.district
                else school.district
            ),
            "team": (
                school.team.name if school.team_id else ""
            ),
            "advisor": owner_name,
            "population_total": (
                profile.population_total if profile else 0
            ),
            "segment": (
                profile.segment if profile else ""
            ),
            "priority_score": (
                profile.priority_score if profile else 0
            ),
            "priority": (
                profile.get_priority_display() if profile else ""
            ),
            "open_opportunities": 0,
            "won_opportunities": 0,
            "lost_opportunities": 0,
            "projected_units": 0,
            "adopted_units": 0,
            "last_activity_at": (
                school.report_last_activity_at
            ),
        }

    opportunity_report = build_opportunity_commercial_report(
        user=user,
        campaign_id=campaign_id,
        team_id=team_id,
        owner_id=owner_id,
    )

    for opportunity in opportunity_report["opportunities"]:
        row = school_rows.get(opportunity["school_id"])

        if row is None:
            continue

        category = opportunity["stage_category"]

        if category == PipelineStage.Category.OPEN:
            row["open_opportunities"] += 1
        elif category == PipelineStage.Category.WON:
            row["won_opportunities"] += 1
        elif category == PipelineStage.Category.LOST:
            row["lost_opportunities"] += 1

        row["projected_units"] += opportunity["projected_units"]
        row["adopted_units"] += opportunity["adopted_units"]

    rows = list(school_rows.values())

    return {
        "filters": {
            "campaign": campaign_id,
            "team": team_id,
            "owner": owner_id,
        },
        "summary": {
            "schools": len(rows),
            "schools_without_opportunity": sum(
                1
                for row in rows
                if (
                    row["open_opportunities"]
                    + row["won_opportunities"]
                    + row["lost_opportunities"]
                )
                == 0
            ),
            "population_total": sum(
                row["population_total"] for row in rows
            ),
            "projected_units": sum(
                row["projected_units"] for row in rows
            ),
            "adopted_units": sum(
                row["adopted_units"] for row in rows
            ),
        },
        "schools": rows,
    }


def build_activity_commercial_report(
    *,
    user,
    date_from,
    date_to,
    campaign_id=None,
    team_id=None,
    owner_id=None,
):
    activities = visible_commercial_activities_queryset(user)

    if team_id is not None:
        activities = activities.filter(
            school__team_id=team_id
        )

    if owner_id is not None:
        activities = activities.filter(
            performed_by_id=owner_id
        )

    if campaign_id is not None:
        activities = activities.filter(
            opportunity__campaign_id=campaign_id
        )

    activities = (
        activities
        .filter(
            occurred_at__date__gte=date_from,
            occurred_at__date__lte=date_to,
        )
        .select_related(
            "school",
            "contact",
            "opportunity",
            "performed_by",
        )
        .order_by("-occurred_at", "-id")
    )

    rows = []

    for activity in activities:
        performer = ""

        if activity.performed_by_id:
            performer = (
                activity.performed_by.get_full_name().strip()
                or activity.performed_by.get_username()
            )

        rows.append(
            {
                "activity_id": activity.id,
                "occurred_at": activity.occurred_at,
                "advisor": performer,
                "school": activity.school.name,
                "contact": (
                    activity.contact.full_name
                    if activity.contact_id
                    else ""
                ),
                "activity_type": activity.get_activity_type_display(),
                "summary": activity.summary,
                "result": activity.result,
                "opportunity": (
                    activity.opportunity.title
                    if activity.opportunity_id
                    else ""
                ),
                "has_location": bool(
                    activity.latitude is not None
                    and activity.longitude is not None
                ),
                "is_important": activity.is_important,
            }
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
            "activities": len(rows),
        },
        "activities": rows,
    }
