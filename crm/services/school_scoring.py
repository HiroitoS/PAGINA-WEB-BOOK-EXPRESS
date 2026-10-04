from decimal import Decimal

from django.utils import timezone

from crm.models import (
    Adoption,
    Campaign,
    CommercialQuotation,
    Opportunity,
    SchoolCommercialProfile,
)


SCORE_VERSION = "v1"


def _population_score(population_total):
    total = int(population_total or 0)

    if total >= 700:
        return 30, "Muy alto"
    if total >= 500:
        return 26, "Alto"
    if total >= 400:
        return 22, "Medio-alto"
    if total >= 250:
        return 18, "Medio"
    if total >= 101:
        return 10, "Medio-bajo"
    if total > 0:
        return 4, "Bajo"

    return 0, "Sin población evaluable"


def _tuition_score(monthly_tuition):
    if monthly_tuition is None:
        return None, "Sin información"

    amount = Decimal(monthly_tuition)

    if amount >= Decimal("700"):
        return 20, "Alta"
    if amount >= Decimal("550"):
        return 16, "Media-alta"
    if amount >= Decimal("400"):
        return 12, "Media"
    if amount >= Decimal("300"):
        return 8, "Media-baja"

    return 4, "Baja"


def _relationship_score(primary_contact):
    if primary_contact is None:
        return None, "Sin contacto principal"

    if primary_contact.relationship_level is None:
        return None, "Relacionamiento sin evaluar"

    if not primary_contact.decision_role:
        return None, "Rol en la decisión sin clasificar"

    relationship_scores = {
        1: (0, "Contacto inicial"),
        2: (2, "Relación en desarrollo"),
        3: (4, "Buena relación"),
        4: (6, "Relación sólida"),
        5: (8, "Relación estratégica"),
    }
    relationship_data = relationship_scores.get(
        primary_contact.relationship_level
    )

    if relationship_data is None:
        return None, "Relacionamiento fuera de rango"

    relationship_points, relationship_label = relationship_data

    role_points = {
        primary_contact.DecisionRole.DECISION_MAKER: 12,
        primary_contact.DecisionRole.INFLUENCER: 8,
        primary_contact.DecisionRole.OTHER: 4,
    }.get(primary_contact.decision_role)

    if role_points is None:
        return None, "Rol en la decisión sin clasificar"

    return (
        relationship_points + role_points,
        f"{relationship_label} · {primary_contact.get_decision_role_display()}",
    )


def _affinity_score(commercial_affinity):
    scores = {
        SchoolCommercialProfile.CommercialAffinity.PEDAGOGICAL: (
            15,
            "Pedagógica",
        ),
        SchoolCommercialProfile.CommercialAffinity.MIXED: (
            10,
            "Mixta",
        ),
        SchoolCommercialProfile.CommercialAffinity.COMMERCIAL: (
            5,
            "Comercial",
        ),
    }

    return scores.get(commercial_affinity, (None, "Sin evaluar"))


def _history_score(school, campaign):
    previous_opportunities = Opportunity.objects.filter(
        school=school,
        campaign__campaign_type=Campaign.CampaignType.SCHOOL,
        campaign__year__lt=campaign.year,
    )

    if Adoption.objects.filter(
        school=school,
        campaign__campaign_type=Campaign.CampaignType.SCHOOL,
        campaign__year__lt=campaign.year,
    ).exists():
        return 15, "Cliente con adopción previa"

    if CommercialQuotation.objects.filter(
        opportunity__in=previous_opportunities,
        accepted_at__isnull=False,
    ).exists():
        return 12, "Cotización aceptada en campaña anterior"

    if CommercialQuotation.objects.filter(
        opportunity__in=previous_opportunities,
        sent_at__isnull=False,
    ).exists():
        return 8, "Cotización enviada en campaña anterior"

    if previous_opportunities.exists():
        return 4, "Tuvo gestión comercial previa"

    return 0, "Sin historial comercial previo"


def _priority_for_score(score):
    if score >= 75:
        return SchoolCommercialProfile.Priority.HIGH
    if score >= 50:
        return SchoolCommercialProfile.Priority.MEDIUM
    return SchoolCommercialProfile.Priority.LOW


def recalculate_school_commercial_profile(profile):
    school = profile.school
    primary_contact = (
        school.contacts.filter(
            is_active=True,
            is_primary=True,
        )
        .order_by("id")
        .first()
    )

    population_points, population_label = _population_score(
        profile.population_total
    )
    tuition_points, tuition_label = _tuition_score(
        profile.monthly_tuition
    )
    relationship_points, relationship_label = _relationship_score(
        primary_contact
    )
    history_points, history_label = _history_score(
        school,
        profile.campaign,
    )
    affinity_points, affinity_label = _affinity_score(
        profile.commercial_affinity
    )

    missing = []

    if profile.population_total <= 0:
        missing.append("Población")
    if tuition_points is None:
        missing.append("Pensión")
    if relationship_points is None:
        missing.append("Relacionamiento")
    if affinity_points is None:
        missing.append("Afinidad")

    reasons = [
        {
            "key": "population",
            "label": "Población",
            "points": population_points,
            "max_points": 30,
            "detail": population_label,
        },
        {
            "key": "tuition",
            "label": "Pensión",
            "points": tuition_points,
            "max_points": 20,
            "detail": tuition_label,
        },
        {
            "key": "relationship",
            "label": "Relacionamiento",
            "points": relationship_points,
            "max_points": 20,
            "detail": relationship_label,
        },
        {
            "key": "history",
            "label": "Historial comercial",
            "points": history_points,
            "max_points": 15,
            "detail": history_label,
        },
        {
            "key": "affinity",
            "label": "Afinidad",
            "points": affinity_points,
            "max_points": 15,
            "detail": affinity_label,
        },
    ]

    if missing:
        profile.priority_score = 0
        profile.priority = SchoolCommercialProfile.Priority.UNDEFINED
        profile.score_reasons = {
            "status": "pending",
            "missing": missing,
            "components": reasons,
        }
        profile.score_version = SCORE_VERSION
        profile.scored_at = None
        profile.save(
            update_fields=[
                "priority_score",
                "priority",
                "score_reasons",
                "score_version",
                "scored_at",
                "updated_at",
            ]
        )
        return profile

    score = (
        population_points
        + tuition_points
        + relationship_points
        + history_points
        + affinity_points
    )

    profile.priority_score = score
    profile.priority = _priority_for_score(score)
    profile.score_reasons = {
        "status": "scored",
        "missing": [],
        "components": reasons,
    }
    profile.score_version = SCORE_VERSION
    profile.scored_at = timezone.now()
    profile.save(
        update_fields=[
            "priority_score",
            "priority",
            "score_reasons",
            "score_version",
            "scored_at",
            "updated_at",
        ]
    )

    return profile


def recalculate_active_school_profile(school):
    profiles = list(
        SchoolCommercialProfile.objects.filter(
            school=school,
            campaign__campaign_type=Campaign.CampaignType.SCHOOL,
            campaign__status=Campaign.Status.ACTIVE,
        )
        .select_related("school", "campaign")
        .order_by("-campaign__year", "-id")
    )

    if len(profiles) != 1:
        return None

    profile = profiles[0]
    institutional_records = (
        school.educational_services.filter(
            campus__isnull=True,
            is_active=True,
            population_records__is_current=True,
        )
        .values_list("population_records__student_count", flat=True)
    )
    institutional_total = sum(institutional_records)

    if institutional_total != profile.population_total:
        profile.population_total = institutional_total
        profile.segment = SchoolCommercialProfile.segment_for_population(
            institutional_total
        )
        profile.save(
            update_fields=[
                "population_total",
                "segment",
                "updated_at",
            ]
        )

    return recalculate_school_commercial_profile(profile)
