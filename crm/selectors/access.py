from django.db.models import Q

from accounts.permissions import usuario_es_administrador

from crm.models import (
    CommercialActivity,
    CommercialTeamMembership,
    Opportunity,
    School,
    SchoolContact,
)
from crm.permissions import (
    usuario_puede_supervisar_crm,
    usuario_puede_ver_crm,
)


def supervised_team_ids(user):
    if not user or not user.is_authenticated:
        return CommercialTeamMembership.objects.none().values_list(
            "team_id",
            flat=True,
        )

    return (
        CommercialTeamMembership.objects
        .filter(
            user=user,
            is_active=True,
            team__is_active=True,
            role=CommercialTeamMembership.Role.SUPERVISOR,
        )
        .values_list("team_id", flat=True)
    )


def visible_schools_queryset(user):
    queryset = School.objects.all()

    if not user or not user.is_authenticated:
        return queryset.none()

    if usuario_es_administrador(user):
        return queryset

    if not usuario_puede_ver_crm(user):
        return queryset.none()

    base_scope = Q(owner=user) | Q(created_by=user)

    if usuario_puede_supervisar_crm(user):
        return queryset.filter(
            base_scope | Q(team_id__in=supervised_team_ids(user))
        ).distinct()

    return queryset.filter(base_scope).distinct()


def visible_school_contacts_queryset(user):
    queryset = SchoolContact.objects.all()

    if not user or not user.is_authenticated:
        return queryset.none()

    if usuario_es_administrador(user):
        return queryset

    visible_school_ids = visible_schools_queryset(user).values_list(
        "id",
        flat=True,
    )

    return queryset.filter(school_id__in=visible_school_ids)


def visible_opportunities_queryset(user):
    queryset = Opportunity.objects.all()

    if not user or not user.is_authenticated:
        return queryset.none()

    if usuario_es_administrador(user):
        return queryset

    if not usuario_puede_ver_crm(user):
        return queryset.none()

    base_scope = Q(owner=user) | Q(created_by=user)

    if usuario_puede_supervisar_crm(user):
        return queryset.filter(
            base_scope | Q(team_id__in=supervised_team_ids(user))
        ).distinct()

    return queryset.filter(base_scope).distinct()


def visible_commercial_activities_queryset(user):
    queryset = CommercialActivity.objects.all()

    if not user or not user.is_authenticated:
        return queryset.none()

    if usuario_es_administrador(user):
        return queryset

    visible_school_ids = visible_schools_queryset(user).values_list(
        "id",
        flat=True,
    )

    return queryset.filter(school_id__in=visible_school_ids)
