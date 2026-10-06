import unicodedata

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import usuario_es_administrador
from catalog.models import Grade, Product
from crm.models import (
    Adoption,
    Campaign,
    CommercialQuotation,
    CommercialTeam,
    CommercialTeamMembership,
    CRMHistoryEvent,
    CRMWorkItemLink,
    MarketEditorial,
    Pipeline,
    PipelineStage,
    School,
    SchoolCampus,
    SchoolCommercialProfile,
    SchoolEducationalService,
    SchoolImportBatch,
    SchoolPopulationDetail,
    SchoolPopulationRecord,
)
from crm.permissions import (
    EsUsuarioCRM,
    usuario_puede_asignar_colegios,
    usuario_puede_asignar_oportunidades,
    usuario_puede_gestionar_colegios,
    usuario_puede_gestionar_oportunidades_propias,
    usuario_puede_supervisar_crm,
)
from crm.selectors import (
    visible_commercial_activities_queryset,
    visible_opportunities_queryset,
    visible_school_contacts_queryset,
    visible_schools_queryset,
    work_items_for_contact,
    work_items_for_opportunity,
    work_items_for_school,
)
from crm.services import (
    AdoptionError,
    CRMPlanningError,
    build_opportunity_commercial_history,
    build_school_commercial_history,
    CommercialActivityError,
    CommercialProjectionError,
    CommercialQuotationError,
    OpportunityTransitionError,
    accept_commercial_quotation,
    approve_commercial_quotation_discount,
    confirm_adoption,
    create_commercial_projection_revision,
    create_commercial_quotation,
    create_commercial_quotation_from_projection,
    preview_commercial_quotation_financials,
    create_opportunity,
    create_opportunity_event,
    create_opportunity_reminder,
    create_opportunity_task,
    create_school_event,
    create_school_reminder,
    create_school_task,
    record_commercial_activity,
    record_history_event,
    recalculate_active_school_profile,
    recalculate_school_commercial_profile,
    reopen_commercial_quotation_negotiation,
    send_commercial_quotation,
    update_commercial_quotation_from_projection,
    reopen_opportunity,
    resolve_projection_price,
    transition_opportunity_stage,
)

from crm.services.commercial_lines import VALID_PROJECTION_LINES
from crm.services.education import grade_matches_level
from crm.services.school_imports import (
    confirm_school_import,
    create_school_import_preview,
)

from .pagination import CRMPageNumberPagination
from .serializers import (
    AdoptionConfirmSerializer,
    AdoptionSerializer,
    CampaignSerializer,
    CommercialActivityCreateSerializer,
    CommercialActivityEvidenceCreateSerializer,
    CommercialActivityEvidenceSerializer,
    CommercialActivitySerializer,
    CRMCommercialHistoryEventSerializer,
    CommercialProjectionCreateSerializer,
    CommercialProjectionSerializer,
    CommercialQuotationCreateSerializer,
    CommercialQuotationDiscountApprovalSerializer,
    CommercialQuotationFromProjectionSerializer,
    CommercialQuotationProjectionItemAdjustmentSerializer,
    CommercialQuotationReopenSerializer,
    CommercialQuotationSerializer,
    CommercialTeamDetailSerializer,
    CommercialTeamWriteSerializer,
    OpportunityCreateSerializer,
    OpportunityDetailSerializer,
    OpportunityEventCreateSerializer,
    OpportunityListSerializer,
    OpportunityReminderCreateSerializer,
    OpportunityReopenSerializer,
    OpportunityStageChangeSerializer,
    OpportunityStageHistorySerializer,
    OpportunityTaskCreateSerializer,
    OpportunityUpdateSerializer,
    PipelineSerializer,
    SchoolCommercialActivityCreateSerializer,
    SchoolContactCRMSerializer,
    SchoolContactSerializer,
    SchoolCommercialProfileSerializer,
    SchoolCommercialProfileWriteSerializer,
    SchoolDetailSerializer,
    SchoolEducationalServiceSerializer,
    SchoolEducationalServiceWriteSerializer,
    SchoolEventCreateSerializer,
    SchoolListSerializer,
    SchoolAssignmentSerializer,
    SchoolImportBatchListSerializer,
    SchoolImportBatchSerializer,
    SchoolImportPreviewSerializer,
    SchoolInstitutionalPopulationWriteSerializer,
    SchoolPopulationRecordSerializer,
    SchoolPopulationRecordWriteSerializer,
    SchoolReminderCreateSerializer,
    SchoolTaskCreateSerializer,
    SchoolWriteSerializer,
    UserSummarySerializer,
    WorkItemLinkSerializer,
    SchoolEditorialUsageSerializer,
    SchoolEditorialUsageWriteSerializer,
    MarketEditorialCreateSerializer,
    MarketEditorialSerializer,
    build_school_institutional_population,
)


def _raise_service_validation_error(exc):
    if hasattr(exc, "message_dict"):
        raise serializers.ValidationError(exc.message_dict)
    messages = getattr(exc, "messages", None)
    if messages:
        raise serializers.ValidationError({"detail": messages})
    raise serializers.ValidationError({"detail": str(exc)})


def _normalize_location_token(value):
    normalized = unicodedata.normalize(
        "NFKD",
        str(value or "").strip(),
    )
    without_accents = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(without_accents.casefold().split())


def _location_values(queryset, field_name):
    raw_values = (
        queryset.exclude(**{field_name: ""})
        .values_list(field_name, flat=True)
        .distinct()
    )
    values_by_key = {}

    for raw_value in raw_values:
        clean_value = " ".join(str(raw_value or "").split())
        key = _normalize_location_token(clean_value)

        if key and key not in values_by_key:
            values_by_key[key] = clean_value

    return sorted(
        values_by_key.values(),
        key=_normalize_location_token,
    )


def _matching_location_values(queryset, field_name, requested_value):
    requested_key = _normalize_location_token(requested_value)

    if not requested_key:
        return []

    return [
        value
        for value in _location_values(queryset, field_name)
        if _normalize_location_token(value) == requested_key
    ]


def _user_can_manage_visible_opportunity(user, opportunity):
    if usuario_es_administrador(user):
        return True
    if opportunity.owner_id == user.id:
        return usuario_puede_gestionar_oportunidades_propias(user)
    if opportunity.team_id and usuario_puede_supervisar_crm(user):
        return CommercialTeamMembership.objects.filter(
            team_id=opportunity.team_id,
            user=user,
            is_active=True,
            role=CommercialTeamMembership.Role.SUPERVISOR,
        ).exists()
    return False


def _single_visible_open_opportunity_for_school(user, school):
    opportunities = list(
        visible_opportunities_queryset(user)
        .filter(
            school=school,
            stage__category=PipelineStage.Category.OPEN,
        )
        .select_related("stage")
        .order_by("-updated_at", "-id")[:2]
    )

    if len(opportunities) == 1:
        return opportunities[0]

    return None


def _fill_empty_primary_contact_on_open_opportunities(*, school, contact):
    if not contact.is_active or not contact.is_primary:
        return

    school.opportunities.filter(
        stage__category=PipelineStage.Category.OPEN,
        primary_contact__isnull=True,
    ).update(
        primary_contact=contact,
        updated_at=timezone.now(),
    )


class CRMSummaryAPIView(APIView):
    permission_classes = [EsUsuarioCRM]

    def get(self, request):
        schools = visible_schools_queryset(request.user)
        opportunities = visible_opportunities_queryset(request.user)
        activities = visible_commercial_activities_queryset(request.user)
        today = timezone.localdate()
        stages = list(
            opportunities.values(
                "stage_id", "stage__code", "stage__name", "stage__order", "stage__category"
            ).annotate(total=Count("id")).order_by("stage__order", "stage__name")
        )
        return Response({
            "schools": schools.filter(is_active=True).count(),
            "open_opportunities": opportunities.filter(stage__category=PipelineStage.Category.OPEN).count(),
            "won_opportunities": opportunities.filter(stage__category=PipelineStage.Category.WON).count(),
            "lost_opportunities": opportunities.filter(stage__category=PipelineStage.Category.LOST).count(),
            "opportunities_without_activity": opportunities.filter(
                stage__category=PipelineStage.Category.OPEN,
                last_activity_at__isnull=True,
            ).count(),
            "activities_today": activities.filter(occurred_at__date=today).count(),
            "stages": stages,
        })


class CampaignViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [EsUsuarioCRM]
    pagination_class = None
    serializer_class = CampaignSerializer

    def get_queryset(self):
        return Campaign.objects.all().order_by("-year", "name")


class PipelineViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [EsUsuarioCRM]
    pagination_class = None
    serializer_class = PipelineSerializer

    def get_queryset(self):
        return Pipeline.objects.filter(is_active=True).prefetch_related("stages").order_by("-is_default", "name")


class CommercialTeamViewSet(viewsets.ModelViewSet):
    permission_classes = [EsUsuarioCRM]
    pagination_class = None
    http_method_names = [
        "get",
        "post",
        "patch",
        "head",
        "options",
    ]

    def get_serializer_class(self):
        if self.action in {
            "create",
            "partial_update",
            "update",
        }:
            return CommercialTeamWriteSerializer

        return CommercialTeamDetailSerializer

    def get_queryset(self):
        user = self.request.user
        include_inactive = (
            self.request.query_params.get("include_inactive")
            == "true"
        )

        queryset = (
            CommercialTeam.objects
            .all()
            .prefetch_related(
                "memberships__user",
                "memberships__user__book_express_profile",
            )
            .annotate(
                active_school_count=Count(
                    "schools",
                    filter=Q(schools__is_active=True),
                    distinct=True,
                ),
                active_advisor_count=Count(
                    "memberships",
                    filter=Q(
                        memberships__is_active=True,
                        memberships__user__is_active=True,
                        memberships__role=(
                            CommercialTeamMembership.Role.ADVISOR
                        ),
                    ),
                    distinct=True,
                ),
                active_supervisor_count=Count(
                    "memberships",
                    filter=Q(
                        memberships__is_active=True,
                        memberships__user__is_active=True,
                        memberships__role=(
                            CommercialTeamMembership.Role.SUPERVISOR
                        ),
                    ),
                    distinct=True,
                ),
            )
        )

        can_manage = (
            usuario_es_administrador(user)
            or usuario_puede_asignar_colegios(user)
        )

        if not include_inactive or not can_manage:
            queryset = queryset.filter(is_active=True)

        if usuario_es_administrador(user):
            return queryset.order_by("name")

        if usuario_puede_asignar_colegios(user):
            return (
                queryset
                .filter(
                    memberships__user=user,
                    memberships__is_active=True,
                    memberships__role=(
                        CommercialTeamMembership.Role.SUPERVISOR
                    ),
                )
                .distinct()
                .order_by("name")
            )

        return (
            queryset
            .filter(
                memberships__user=user,
                memberships__is_active=True,
            )
            .distinct()
            .order_by("name")
        )

    def _ensure_can_manage_teams(self):
        user = self.request.user
        if (
            usuario_es_administrador(user)
            or usuario_puede_asignar_colegios(user)
        ):
            return

        raise PermissionDenied(
            "No tienes permiso para gestionar equipos comerciales."
        )

    def create(self, request, *args, **kwargs):
        self._ensure_can_manage_teams()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not usuario_es_administrador(request.user):
            supervisors = serializer.validated_data.setdefault(
                "_supervisor_users",
                [],
            )
            if request.user not in supervisors:
                supervisors.append(request.user)

        with transaction.atomic():
            team = serializer.save()

        return Response(
            CommercialTeamDetailSerializer(
                team,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        self._ensure_can_manage_teams()
        team = self.get_object()

        serializer = self.get_serializer(
            team,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        if (
            not usuario_es_administrador(request.user)
            and "_supervisor_users" in serializer.validated_data
        ):
            supervisors = serializer.validated_data[
                "_supervisor_users"
            ]
            if request.user not in supervisors:
                supervisors.append(request.user)

        with transaction.atomic():
            team = serializer.save()

        return Response(
            CommercialTeamDetailSerializer(
                team,
                context={"request": request},
            ).data
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="eligible-members",
        url_name="eligible-members",
    )
    def eligible_members(self, request):
        self._ensure_can_manage_teams()

        User = get_user_model()
        supervisors = []
        advisors = []

        for user in (
            User.objects
            .filter(is_active=True)
            .select_related("book_express_profile")
            .prefetch_related("groups", "user_permissions")
            .order_by(
                "first_name",
                "last_name",
                "username",
            )
        ):
            can_supervise = (
                usuario_es_administrador(user)
                or usuario_puede_supervisar_crm(user)
            )
            can_advise = (
                usuario_puede_gestionar_oportunidades_propias(user)
            )

            if can_supervise:
                supervisors.append(user)

            if can_advise and not can_supervise:
                advisors.append(user)

        serializer_context = {"request": request}
        return Response(
            {
                "supervisors": UserSummarySerializer(
                    supervisors,
                    many=True,
                    context=serializer_context,
                ).data,
                "advisors": UserSummarySerializer(
                    advisors,
                    many=True,
                    context=serializer_context,
                ).data,
            }
        )


class SchoolContactViewSet(viewsets.ModelViewSet):
    permission_classes = [EsUsuarioCRM]
    pagination_class = CRMPageNumberPagination
    serializer_class = SchoolContactCRMSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        queryset = (
            visible_school_contacts_queryset(self.request.user)
            .select_related("school")
        )

        search = self.request.query_params.get("search", "").strip()
        school = self.request.query_params.get("school")
        decision_role = self.request.query_params.get(
            "decision_role",
            "",
        ).strip()
        is_active = self.request.query_params.get("is_active")

        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search)
                | Q(position__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
                | Q(whatsapp__icontains=search)
                | Q(school__name__icontains=search)
            )

        if school:
            queryset = queryset.filter(school_id=school)

        if decision_role:
            queryset = queryset.filter(decision_role=decision_role)

        if is_active == "true":
            queryset = queryset.filter(is_active=True)
        elif is_active == "false":
            queryset = queryset.filter(is_active=False)

        return queryset.order_by(
            "school__name",
            "-is_primary",
            "full_name",
            "id",
        )

    def partial_update(self, request, *args, **kwargs):
        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para modificar contactos."
            )

        contact = self.get_object()
        serializer = self.get_serializer(
            contact,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        is_active = serializer.validated_data.get(
            "is_active",
            contact.is_active,
        )
        is_primary = (
            serializer.validated_data.get(
                "is_primary",
                contact.is_primary,
            )
            if is_active
            else False
        )

        with transaction.atomic():
            if is_primary:
                contact.school.contacts.exclude(
                    pk=contact.pk,
                ).filter(
                    is_primary=True,
                ).update(
                    is_primary=False,
                )

            contact = serializer.save(
                is_primary=is_primary,
            )

            _fill_empty_primary_contact_on_open_opportunities(
                school=contact.school,
                contact=contact,
            )

            record_history_event(
                school=contact.school,
                contact=contact,
                actor=request.user,
                category="contact",
                event_type="contact_updated",
                title=f"Contacto actualizado: {contact.full_name}",
                description=contact.position or "",
                metadata={"contact_id": contact.id},
            )

        recalculate_active_school_profile(contact.school)

        return Response(
            self.get_serializer(contact).data
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="activities",
        url_name="activities",
    )
    def activities(self, request, pk=None):
        contact = self.get_object()

        queryset = (
            visible_commercial_activities_queryset(request.user)
            .filter(contact=contact)
            .select_related(
                "contact",
                "opportunity",
                "performed_by",
                "created_by",
            )
            .prefetch_related("evidences__uploaded_by")
            .order_by("-occurred_at", "-id")
        )

        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(
                CommercialActivitySerializer(
                    page,
                    many=True,
                    context={"request": request},
                ).data
            )

        return Response(
            CommercialActivitySerializer(
                queryset,
                many=True,
                context={"request": request},
            ).data
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="work-items",
        url_name="work-items",
    )
    def work_items(self, request, pk=None):
        contact = self.get_object()
        queryset = work_items_for_contact(contact)

        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(
                WorkItemLinkSerializer(
                    page,
                    many=True,
                ).data
            )

        return Response(
            WorkItemLinkSerializer(
                queryset,
                many=True,
            ).data
        )


class MarketEditorialViewSet(viewsets.ModelViewSet):
    permission_classes = [EsUsuarioCRM]
    pagination_class = None
    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self):
        queryset = (
            MarketEditorial.objects
            .filter(is_active=True)
            .select_related("catalog_provider")
        )

        search = self.request.query_params.get(
            "search",
            "",
        ).strip()

        if search:
            queryset = queryset.filter(
                name__icontains=search,
            )

        return queryset.order_by("name", "id")

    def get_serializer_class(self):
        if self.action == "create":
            return MarketEditorialCreateSerializer

        return MarketEditorialSerializer

    def create(self, request, *args, **kwargs):
        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para registrar editoriales."
            )

        serializer = self.get_serializer(
            data=request.data,
        )
        serializer.is_valid(
            raise_exception=True,
        )

        editorial = serializer.save(
            created_by=request.user,
            verification_status=(
                MarketEditorial.VerificationStatus.PENDING
            ),
            is_active=True,
        )

        return Response(
            MarketEditorialSerializer(editorial).data,
            status=status.HTTP_201_CREATED,
        )

class SchoolImportViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [EsUsuarioCRM]
    pagination_class = None

    def get_queryset(self):
        self._ensure_can_import()
        return (
            SchoolImportBatch.objects
            .select_related("created_by")
            .prefetch_related("rows")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return SchoolImportBatchListSerializer

        return SchoolImportBatchSerializer

    def _ensure_can_import(self):
        user = self.request.user

        if (
            usuario_es_administrador(user)
            or usuario_puede_supervisar_crm(user)
        ):
            return

        raise PermissionDenied(
            "No tienes permiso para importar colegios."
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="preview",
        url_name="preview",
    )
    def preview(self, request):
        self._ensure_can_import()

        serializer = SchoolImportPreviewSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        batch = create_school_import_preview(
            file=serializer.validated_data["file"],
            population_year=serializer.validated_data[
                "population_year"
            ],
            actor=request.user,
        )

        return Response(
            SchoolImportBatchSerializer(
                batch,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="confirm",
        url_name="confirm",
    )
    def confirm(self, request, pk=None):
        self._ensure_can_import()

        try:
            batch = confirm_school_import(
                batch_id=pk,
                actor=request.user,
            )
        except SchoolImportBatch.DoesNotExist:
            return Response(
                {"detail": "La importación no existe."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            SchoolImportBatchSerializer(
                batch,
                context={"request": request},
            ).data
        )


def _sync_main_campus_from_school(*, school, actor):
    campus = (
        school.campuses
        .filter(is_main=True)
        .order_by("sequence", "id")
        .first()
    )

    if campus is None:
        campus = SchoolCampus(
            school=school,
            sequence=1,
            name="Sede principal",
            is_main=True,
            created_by=actor,
        )

    campus.address = school.address or ""
    campus.reference = school.reference or ""
    campus.department = school.department or ""
    campus.province = school.province or ""
    campus.district = school.district or ""
    campus.is_active = True
    campus.full_clean()
    campus.save()

    return campus


class SchoolViewSet(viewsets.ModelViewSet):
    permission_classes = [EsUsuarioCRM]
    pagination_class = CRMPageNumberPagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = (
            visible_schools_queryset(self.request.user)
            .select_related(
                "team",
                "owner",
                "owner__book_express_profile",
            )
            .prefetch_related(
                "levels",
                "campuses",
                "educational_services__campus",
                "educational_services__level",
                "educational_services__population_records",
                "educational_services__population_records__details__grade",
            )
        )
        if self.action == "retrieve":
            queryset = queryset.prefetch_related(
                "contacts",
                "editorial_usages__editorial",
                "editorial_usages__provider",
                "editorial_usages__area",
                "editorial_usages__service__level",
                "commercial_profiles__campaign",
            )
        search = self.request.query_params.get("search", "").strip()
        team = self.request.query_params.get("team")
        owner = self.request.query_params.get("owner")
        department = self.request.query_params.get("department", "").strip()
        province = self.request.query_params.get("province", "").strip()
        district = self.request.query_params.get("district", "").strip()
        assignment = self.request.query_params.get("assignment", "").strip()
        is_active = self.request.query_params.get("is_active")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(book_express_code__icontains=search)
                | Q(institution_code__icontains=search)
                | Q(modular_code__icontains=search)
                | Q(educational_services__modular_code__icontains=search)
                | Q(ruc__icontains=search)
                | Q(phone__icontains=search) | Q(whatsapp__icontains=search) | Q(email__icontains=search)
                | Q(owner__username__icontains=search) | Q(owner__first_name__icontains=search)
                | Q(owner__last_name__icontains=search)
                | Q(campuses__address__icontains=search)
                | Q(campuses__district__icontains=search)
            )
        if team:
            queryset = queryset.filter(team_id=team)
        if owner:
            queryset = queryset.filter(owner_id=owner)
        location_campuses = SchoolCampus.objects.filter(
            school__in=queryset,
            is_active=True,
        )

        if department:
            department_values = _matching_location_values(
                location_campuses,
                "department",
                department,
            )
            if not department_values:
                return queryset.none()
            queryset = queryset.filter(
                campuses__department__in=department_values
            )
            location_campuses = location_campuses.filter(
                department__in=department_values
            )

        if province:
            province_values = _matching_location_values(
                location_campuses,
                "province",
                province,
            )
            if not province_values:
                return queryset.none()
            queryset = queryset.filter(
                campuses__province__in=province_values
            )
            location_campuses = location_campuses.filter(
                province__in=province_values
            )

        if district:
            district_values = _matching_location_values(
                location_campuses,
                "district",
                district,
            )
            if not district_values:
                return queryset.none()
            queryset = queryset.filter(
                campuses__district__in=district_values
            )
        if assignment == "unassigned":
            queryset = queryset.filter(owner__isnull=True)
        elif assignment == "assigned":
            queryset = queryset.filter(owner__isnull=False)
        if is_active == "true":
            queryset = queryset.filter(is_active=True)
        elif is_active == "false":
            queryset = queryset.filter(is_active=False)
        return queryset.distinct().order_by("name", "id")

    def get_serializer_class(self):
        if self.action == "list":
            return SchoolListSerializer
        if self.action == "retrieve":
            return SchoolDetailSerializer
        return SchoolWriteSerializer

    @action(
        detail=False,
        methods=["get"],
        url_path="location-options",
        url_name="location-options",
    )
    def location_options(self, request):
        schools = visible_schools_queryset(request.user)
        is_active = request.query_params.get("is_active")

        if is_active == "true":
            schools = schools.filter(is_active=True)
        elif is_active == "false":
            schools = schools.filter(is_active=False)

        campuses = SchoolCampus.objects.filter(
            school__in=schools,
            is_active=True,
        )
        departments = _location_values(campuses, "department")

        department = request.query_params.get(
            "department",
            "",
        ).strip()
        province = request.query_params.get(
            "province",
            "",
        ).strip()

        if department:
            department_values = _matching_location_values(
                campuses,
                "department",
                department,
            )
            campuses = (
                campuses.filter(department__in=department_values)
                if department_values
                else campuses.none()
            )

        provinces = _location_values(campuses, "province")

        if province:
            province_values = _matching_location_values(
                campuses,
                "province",
                province,
            )
            campuses = (
                campuses.filter(province__in=province_values)
                if province_values
                else campuses.none()
            )

        districts = _location_values(campuses, "district")

        return Response(
            {
                "departments": departments,
                "provinces": provinces,
                "districts": districts,
            }
        )

    def create(self, request, *args, **kwargs):
        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied("No tienes permiso para registrar colegios.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        requested_owner = data.get("owner")
        requested_team = data.get("team")
        can_assign = usuario_es_administrador(request.user) or usuario_puede_asignar_colegios(request.user)
        if not can_assign:
            if requested_owner is not None and requested_owner.id != request.user.id:
                raise PermissionDenied("No puedes asignar el colegio a otro usuario.")
            if requested_team is not None and not CommercialTeamMembership.objects.filter(
                team=requested_team, user=request.user, is_active=True
            ).exists():
                raise PermissionDenied("No perteneces al equipo comercial seleccionado.")
            data["owner"] = request.user
        levels = data.pop("levels", [])
        school = School(**data, created_by=request.user)
        school.full_clean()
        school.save()

        record_history_event(
            school=school,
            actor=request.user,
            category="school",
            event_type="school_created",
            title="Colegio incorporado a la cartera CRM",
            description=school.name,
            source_type="school",
            source_id=school.id,
            metadata={"school_id": school.id},
            occurred_at=school.created_at,
        )

        _sync_main_campus_from_school(
            school=school,
            actor=request.user,
        )
        if levels:
            school.levels.set(levels)
        return Response(
            SchoolDetailSerializer(
                school,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied("No tienes permiso para modificar colegios.")
        school = self.get_object()
        serializer = self.get_serializer(school, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        can_assign = (
            usuario_es_administrador(request.user)
            or usuario_puede_asignar_colegios(request.user)
        )
        if not can_assign:
            if "owner" in data and data["owner"] != school.owner:
                raise PermissionDenied("No puedes reasignar el colegio.")
            if "team" in data and data["team"] != school.team:
                raise PermissionDenied(
                    "No puedes cambiar el equipo comercial del colegio."
                )
        else:
            target_team = data.get("team", school.team)
            target_owner = data.get("owner", school.owner)

            if target_owner is not None and target_team is None:
                raise serializers.ValidationError(
                    {
                        "team": (
                            "Selecciona un equipo comercial antes de elegir "
                            "un asesor."
                        )
                    }
                )

            if target_owner is not None and not (
                CommercialTeamMembership.objects.filter(
                    team=target_team,
                    user=target_owner,
                    is_active=True,
                    role=CommercialTeamMembership.Role.ADVISOR,
                ).exists()
            ):
                raise serializers.ValidationError(
                    {
                        "owner": (
                            "El asesor seleccionado no pertenece al equipo "
                            "comercial elegido."
                        )
                    }
                )

            if (
                target_team is not None
                and not usuario_es_administrador(request.user)
                and not CommercialTeamMembership.objects.filter(
                    team=target_team,
                    user=request.user,
                    is_active=True,
                    role=CommercialTeamMembership.Role.SUPERVISOR,
                ).exists()
            ):
                raise PermissionDenied(
                    "Solo puedes asignar colegios dentro de tus equipos."
                )

        levels = data.pop("levels", None)
        for field, value in data.items():
            setattr(school, field, value)
        school.full_clean()
        school.save()
        _sync_main_campus_from_school(
            school=school,
            actor=request.user,
        )
        if levels is not None:
            school.levels.set(levels)
        return Response(
            SchoolDetailSerializer(
                school,
                context={"request": request},
            ).data
        )

    @action(
        detail=True,
        methods=["patch"],
        url_path="commercial-profile",
        url_name="commercial-profile",
    )
    def commercial_profile(self, request, pk=None):
        school = self.get_object()

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para modificar el perfil comercial."
            )

        serializer = SchoolCommercialProfileWriteSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        campaign = serializer.validated_data["campaign"]
        population_rows = build_school_institutional_population(school)
        known_population = [
            item["student_count"]
            for item in population_rows
            if item["status"] == "known"
            and item["student_count"] is not None
        ]
        population_total = (
            sum(known_population)
            if known_population
            else None
        )

        profile, _created = SchoolCommercialProfile.objects.get_or_create(
            school=school,
            campaign=campaign,
            defaults={
                "population_total": population_total or 0,
            },
        )

        changed_fields = []

        if "monthly_tuition" in serializer.validated_data:
            profile.monthly_tuition = serializer.validated_data[
                "monthly_tuition"
            ]
            changed_fields.append("monthly_tuition")

        if "textbook_usage" in serializer.validated_data:
            profile.textbook_usage = serializer.validated_data[
                "textbook_usage"
            ]
            changed_fields.append("textbook_usage")

        if population_total is not None:
            profile.population_total = population_total
            changed_fields.append("population_total")

        if "commercial_affinity" in serializer.validated_data:
            profile.commercial_affinity = serializer.validated_data[
                "commercial_affinity"
            ]
            changed_fields.append("commercial_affinity")

        if population_total is not None:
            profile.segment = SchoolCommercialProfile.segment_for_population(
                population_total
            )
            changed_fields.append("segment")

        if changed_fields:
            changed_fields.append("updated_at")
            profile.save(update_fields=list(dict.fromkeys(changed_fields)))

        profile = recalculate_school_commercial_profile(profile)

        return Response(
            SchoolCommercialProfileSerializer(profile).data
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="assign-portfolio",
        url_name="assign-portfolio",
    )
    def assign_portfolio(self, request):
        if not (
            usuario_es_administrador(request.user)
            or usuario_puede_asignar_colegios(request.user)
        ):
            raise PermissionDenied(
                "No tienes permiso para asignar la cartera de colegios."
            )

        serializer = SchoolAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        school_ids = serializer.validated_data["school_ids"]
        team = serializer.validated_data["team"]
        owner = serializer.validated_data["owner"]

        if (
            team is not None
            and not usuario_es_administrador(request.user)
            and not CommercialTeamMembership.objects.filter(
                team=team,
                user=request.user,
                is_active=True,
                role=CommercialTeamMembership.Role.SUPERVISOR,
            ).exists()
        ):
            raise PermissionDenied(
                "Solo puedes asignar colegios dentro de tus equipos."
            )

        visible_ids = set(
            visible_schools_queryset(request.user)
            .filter(id__in=school_ids)
            .values_list("id", flat=True)
        )

        if visible_ids != set(school_ids):
            raise PermissionDenied(
                "Uno o más colegios seleccionados no están disponibles para tu gestión."
            )

        with transaction.atomic():
            schools = list(
                School.objects
                .select_for_update()
                .filter(id__in=school_ids)
                .order_by("name", "id")
            )

            for school in schools:
                previous_team_id = school.team_id
                previous_owner_id = school.owner_id

                school.team = team
                school.owner = owner
                school.save(
                    update_fields=[
                        "team",
                        "owner",
                        "updated_at",
                    ]
                )

                if (
                    previous_team_id != school.team_id
                    or previous_owner_id != school.owner_id
                ):
                    owner_name = (
                        owner.get_full_name().strip()
                        or owner.get_username()
                        if owner is not None
                        else "Sin asesor asignado"
                    )
                    team_name = (
                        team.name
                        if team is not None
                        else "Sin equipo comercial"
                    )

                    record_history_event(
                        school=school,
                        actor=request.user,
                        category="assignment",
                        event_type="assignment_updated",
                        title="Responsable comercial actualizado",
                        description=(
                            f"Equipo: {team_name}. "
                            f"Asesor: {owner_name}."
                        ),
                        metadata={
                            "previous_team_id": previous_team_id,
                            "team_id": school.team_id,
                            "previous_owner_id": previous_owner_id,
                            "owner_id": school.owner_id,
                        },
                    )

        refreshed = (
            School.objects
            .filter(id__in=school_ids)
            .select_related(
                "team",
                "owner",
                "owner__book_express_profile",
            )
            .prefetch_related(
                "levels",
                "campuses",
                "educational_services__campus",
                "educational_services__level",
                "educational_services__population_records",
                "educational_services__population_records__details__grade",
            )
            .order_by("name", "id")
        )

        return Response(
            {
                "updated": len(schools),
                "schools": SchoolListSerializer(
                    refreshed,
                    many=True,
                ).data,
            }
        )

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="educational-services",
        url_name="educational-services",
    )
    def educational_services(self, request, pk=None):
        school = self.get_object()

        if request.method == "GET":
            services = (
                school.educational_services
                .select_related("campus", "level")
                .prefetch_related(
                    "population_records",
                    "population_records__details__grade",
                )
                .order_by(
                    "campus__sequence",
                    "level__name",
                    "id",
                )
            )

            return Response(
                SchoolEducationalServiceSerializer(
                    services,
                    many=True,
                ).data
            )

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para registrar niveles educativos."
            )

        serializer = SchoolEducationalServiceWriteSerializer(
            data=request.data,
            context={"school": school},
        )
        serializer.is_valid(raise_exception=True)

        service = serializer.save(
            school=school,
            created_by=request.user,
        )

        return Response(
            SchoolEducationalServiceSerializer(service).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["patch"],
        url_path=r"educational-services/(?P<service_id>[^/.]+)",
        url_name="educational-service-detail",
    )
    def educational_service_detail(
        self,
        request,
        pk=None,
        service_id=None,
    ):
        school = self.get_object()

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para modificar niveles educativos."
            )

        service = (
            school.educational_services
            .select_related("campus", "level")
            .filter(pk=service_id)
            .first()
        )

        if service is None:
            return Response(
                {
                    "detail": (
                        "El nivel educativo no pertenece "
                        "a este colegio."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = SchoolEducationalServiceWriteSerializer(
            service,
            data=request.data,
            partial=True,
            context={"school": school},
        )
        serializer.is_valid(raise_exception=True)

        service = serializer.save()

        return Response(
            SchoolEducationalServiceSerializer(service).data
        )

    @action(
        detail=True,
        methods=["get", "post"],
        url_path=r"educational-services/(?P<service_id>[^/.]+)/population",
        url_name="educational-service-population",
    )
    def educational_service_population(
        self,
        request,
        pk=None,
        service_id=None,
    ):
        school = self.get_object()

        service = (
            school.educational_services
            .select_related("level")
            .filter(pk=service_id)
            .first()
        )

        if service is None:
            return Response(
                {
                    "detail": (
                        "El nivel educativo no pertenece "
                        "a este colegio."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if request.method == "GET":
            records = (
                service.population_records
                .prefetch_related("details__grade")
                .order_by(
                    "-is_current",
                    "-year",
                    "-created_at",
                )
            )

            return Response(
                SchoolPopulationRecordSerializer(
                    records,
                    many=True,
                ).data
            )

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para registrar población."
            )

        serializer = SchoolPopulationRecordWriteSerializer(
            data=request.data,
            context={"level": service.level},
        )
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            service.population_records.filter(
                is_current=True,
            ).update(
                is_current=False,
            )

            population = serializer.save(
                service=service,
                is_current=True,
                recorded_by=request.user,
            )

        return Response(
            SchoolPopulationRecordSerializer(population).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="commercial-history",
        url_name="commercial-history",
    )
    def commercial_history(self, request, pk=None):
        school = self.get_object()

        visible_opportunities = visible_opportunities_queryset(
            request.user
        ).filter(school=school)
        visible_activities = visible_commercial_activities_queryset(
            request.user
        ).filter(school=school)
        visible_contacts = visible_school_contacts_queryset(
            request.user
        ).filter(school=school)

        visible_opportunity_ids = visible_opportunities.values_list(
            "id",
            flat=True,
        )
        history_events = CRMHistoryEvent.objects.filter(
            school=school,
        ).filter(
            Q(opportunity__isnull=True)
            | Q(opportunity_id__in=visible_opportunity_ids)
        )

        events = build_school_commercial_history(
            school=school,
            opportunities_queryset=visible_opportunities,
            activities_queryset=visible_activities,
            contacts_queryset=visible_contacts,
            events_queryset=history_events,
        )

        return Response(
            CRMCommercialHistoryEventSerializer(
                events,
                many=True,
            ).data
        )

    @action(
        detail=True,
        methods=["get", "patch"],
        url_path="institutional-population",
        url_name="institutional-population",
    )
    def institutional_population(self, request, pk=None):
        school = self.get_object()

        if request.method == "GET":
            return Response(
                build_school_institutional_population(school)
            )

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para gestionar la población del colegio."
            )

        serializer = SchoolInstitutionalPopulationWriteSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        population_changes = []

        with transaction.atomic():
            for item in serializer.validated_data["levels"]:
                level = item["level"]
                year = item["year"]
                is_active = item.get("is_active", True)
                student_count = item.get("student_count")
                details = item.get("details", [])

                service, _created = (
                    SchoolEducationalService.objects
                    .select_for_update()
                    .get_or_create(
                        school=school,
                        campus=None,
                        level=level,
                        defaults={
                            "is_active": is_active,
                            "created_by": request.user,
                        },
                    )
                )

                if service.is_active != is_active:
                    service.is_active = is_active
                    service.save()

                current_records = service.population_records.filter(
                    is_current=True,
                ).prefetch_related("details__grade")

                current_population = (
                    current_records
                    .order_by("-year", "-created_at", "-id")
                    .first()
                )

                if not is_active or student_count is None:
                    deactivated = current_records.update(
                        is_current=False,
                    )
                    if deactivated or (
                        current_population is not None
                        and current_population.student_count is not None
                    ):
                        population_changes.append(
                            {
                                "level": level.name,
                                "year": year,
                                "student_count": None,
                                "status": "pending",
                            }
                        )
                    continue

                desired_details = sorted(
                    (
                        detail["grade"].id,
                        detail["section_count"],
                        detail["students_per_section"],
                    )
                    for detail in details
                )

                current_details = (
                    sorted(
                        (
                            detail.grade_id,
                            detail.section_count,
                            detail.students_per_section,
                        )
                        for detail in current_population.details.all()
                    )
                    if current_population is not None
                    else []
                )

                if (
                    current_population is not None
                    and current_population.year == year
                    and current_population.student_count == student_count
                    and current_details == desired_details
                ):
                    continue

                current_records.update(
                    is_current=False,
                )

                population = SchoolPopulationRecord.objects.create(
                    service=service,
                    year=year,
                    student_count=student_count,
                    source="manual",
                    source_detail="Población institucional",
                    is_current=True,
                    recorded_by=request.user,
                )

                SchoolPopulationDetail.objects.bulk_create(
                    [
                        SchoolPopulationDetail(
                            population=population,
                            grade=detail["grade"],
                            section_count=detail["section_count"],
                            students_per_section=detail[
                                "students_per_section"
                            ],
                        )
                        for detail in details
                    ]
                )

                population_changes.append(
                    {
                        "level": level.name,
                        "year": year,
                        "student_count": student_count,
                        "status": "known",
                    }
                )

            if population_changes:
                change_description = "; ".join(
                    (
                        f"{item['level']} {item['year']}: "
                        + (
                            str(item["student_count"])
                            if item["student_count"] is not None
                            else "Pendiente"
                        )
                    )
                    for item in population_changes
                )

                record_history_event(
                    school=school,
                    actor=request.user,
                    category="population",
                    event_type="population_updated",
                    title="Población institucional actualizada",
                    description=change_description,
                    metadata={"levels": population_changes},
                )

        refreshed_school = (
            School.objects
            .prefetch_related(
                "educational_services__level",
                "educational_services__population_records",
                "educational_services__population_records__details__grade",
            )
            .get(pk=school.pk)
        )

        recalculate_active_school_profile(refreshed_school)

        return Response(
            build_school_institutional_population(refreshed_school)
        )

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="contacts",
    )
    def contacts(self, request, pk=None):
        school = self.get_object()

        if request.method == "GET":
            contacts = (
                visible_school_contacts_queryset(request.user)
                .filter(school=school)
                .order_by("-is_primary", "-is_active", "full_name")
            )

            return Response(
                SchoolContactSerializer(
                    contacts,
                    many=True,
                ).data
            )

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para registrar contactos."
            )

        serializer = SchoolContactSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        is_active = serializer.validated_data.get(
            "is_active",
            True,
        )
        is_primary = (
            serializer.validated_data.get(
                "is_primary",
                False,
            )
            if is_active
            else False
        )

        with transaction.atomic():
            if is_primary:
                school.contacts.filter(
                    is_primary=True,
                ).update(
                    is_primary=False,
                )

            contact = serializer.save(
                school=school,
                created_by=request.user,
                is_primary=is_primary,
            )

            _fill_empty_primary_contact_on_open_opportunities(
                school=school,
                contact=contact,
            )

            record_history_event(
                school=school,
                contact=contact,
                actor=request.user,
                category="contact",
                event_type="contact_created",
                title=f"Contacto registrado: {contact.full_name}",
                description=contact.position or "",
                source_type="school_contact",
                source_id=contact.id,
                metadata={
                    "contact_id": contact.id,
                    "is_primary": contact.is_primary,
                },
                occurred_at=contact.created_at,
            )

        recalculate_active_school_profile(school)

        return Response(
            SchoolContactSerializer(contact).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["patch"],
        url_path=r"contacts/(?P<contact_id>[^/.]+)",
        url_name="contact-detail",
    )
    def contact_detail(
        self,
        request,
        pk=None,
        contact_id=None,
    ):
        school = self.get_object()

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para modificar contactos."
            )

        contact = (
            visible_school_contacts_queryset(request.user)
            .filter(
                school=school,
                pk=contact_id,
            )
            .first()
        )

        if contact is None:
            return Response(
                {
                    "detail": (
                        "El contacto no pertenece "
                        "a este colegio."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = SchoolContactSerializer(
            contact,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        is_active = serializer.validated_data.get(
            "is_active",
            contact.is_active,
        )

        is_primary = (
            serializer.validated_data.get(
                "is_primary",
                contact.is_primary,
            )
            if is_active
            else False
        )

        with transaction.atomic():
            if is_primary:
                school.contacts.exclude(
                    pk=contact.pk,
                ).filter(
                    is_primary=True,
                ).update(
                    is_primary=False,
                )

            contact = serializer.save(
                is_primary=is_primary,
            )

            _fill_empty_primary_contact_on_open_opportunities(
                school=school,
                contact=contact,
            )

            record_history_event(
                school=school,
                contact=contact,
                actor=request.user,
                category="contact",
                event_type="contact_updated",
                title=f"Contacto actualizado: {contact.full_name}",
                description=contact.position or "",
                metadata={"contact_id": contact.id},
            )

        recalculate_active_school_profile(school)

        return Response(
            SchoolContactSerializer(contact).data
        )

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="activities",
        url_name="activities",
    )
    def school_activities(self, request, pk=None):
        school = self.get_object()

        if request.method == "GET":
            queryset = (
                visible_commercial_activities_queryset(request.user)
                .filter(school=school)
                .select_related(
                    "contact",
                    "opportunity",
                    "performed_by",
                    "created_by",
                )
                .prefetch_related("evidences__uploaded_by")
                .order_by("-occurred_at", "-id")
            )

            page = self.paginate_queryset(queryset)

            if page is not None:
                return self.get_paginated_response(
                    CommercialActivitySerializer(
                        page,
                        many=True,
                        context={"request": request},
                    ).data
                )

            return Response(
                CommercialActivitySerializer(
                    queryset,
                    many=True,
                    context={"request": request},
                ).data
            )

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para registrar actividad comercial."
            )

        serializer = SchoolCommercialActivityCreateSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        data = dict(serializer.validated_data)
        has_explicit_opportunity = "opportunity" in data
        opportunity = data.pop("opportunity", None)

        if opportunity is None and not has_explicit_opportunity:
            opportunity = _single_visible_open_opportunity_for_school(
                request.user,
                school,
            )

        if (
            opportunity is not None
            and not visible_opportunities_queryset(request.user)
            .filter(
                pk=opportunity.pk,
                school=school,
            )
            .exists()
        ):
            raise serializers.ValidationError(
                {
                    "opportunity": (
                        "La oportunidad no pertenece al colegio "
                        "o no está dentro de tu alcance comercial."
                    )
                }
            )

        try:
            activity = record_commercial_activity(
                school=school,
                opportunity=opportunity,
                performed_by=request.user,
                created_by=request.user,
                **data,
            )
        except CommercialActivityError as exc:
            _raise_service_validation_error(exc)

        return Response(
            CommercialActivitySerializer(
                activity,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"activities/(?P<activity_id>[^/.]+)/evidence",
        url_name="activity-evidence",
    )
    def school_activity_evidence(
        self,
        request,
        pk=None,
        activity_id=None,
    ):
        school = self.get_object()

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para adjuntar evidencias."
            )

        activity = (
            visible_commercial_activities_queryset(request.user)
            .filter(
                pk=activity_id,
                school=school,
            )
            .select_related(
                "school",
                "opportunity",
                "contact",
            )
            .first()
        )

        if activity is None:
            return Response(
                {"detail": "La actividad no pertenece a este colegio."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CommercialActivityEvidenceCreateSerializer(
            data=request.data,
            context={
                "activity": activity,
                "uploaded_by": request.user,
            },
        )
        serializer.is_valid(raise_exception=True)
        evidence = serializer.save()

        record_history_event(
            school=school,
            opportunity=activity.opportunity,
            contact=activity.contact,
            actor=request.user,
            category="evidence",
            event_type="activity_evidence_added",
            title="Evidencia adjuntada",
            description=evidence.original_name,
            source_type="commercial_activity_evidence",
            source_id=evidence.id,
            metadata={
                "activity_id": activity.id,
                "evidence_id": evidence.id,
                "evidence_type": evidence.evidence_type,
            },
        )

        return Response(
            CommercialActivityEvidenceSerializer(
                evidence,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="work-items",
        url_name="work-items",
    )
    def school_work_items(self, request, pk=None):
        school = self.get_object()
        queryset = work_items_for_school(school)

        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(
                WorkItemLinkSerializer(
                    page,
                    many=True,
                ).data
            )

        return Response(
            WorkItemLinkSerializer(
                queryset,
                many=True,
            ).data
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="tasks",
        url_name="create-task",
    )
    def create_school_task(self, request, pk=None):
        school = self.get_object()

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para programar tareas comerciales."
            )

        serializer = SchoolTaskCreateSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        data = dict(serializer.validated_data)
        has_explicit_opportunity = "opportunity" in data
        opportunity = data.get("opportunity")

        if opportunity is None and not has_explicit_opportunity:
            opportunity = _single_visible_open_opportunity_for_school(
                request.user,
                school,
            )
            if opportunity is not None:
                data["opportunity"] = opportunity

        if (
            opportunity is not None
            and not visible_opportunities_queryset(request.user)
            .filter(
                pk=opportunity.pk,
                school=school,
            )
            .exists()
        ):
            raise serializers.ValidationError(
                {
                    "opportunity": (
                        "La oportunidad no pertenece al colegio "
                        "o no está dentro de tu alcance comercial."
                    )
                }
            )

        try:
            task = create_school_task(
                school=school,
                actor=request.user,
                **data,
            )
        except CRMPlanningError as exc:
            _raise_service_validation_error(exc)

        return Response(
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "priority": task.priority,
                "assigned_to_id": task.assigned_to_id,
                "due_at": task.due_at,
                "reminder_at": task.reminder_at,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="events",
        url_name="create-event",
    )
    def create_school_event(self, request, pk=None):
        school = self.get_object()

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para programar eventos comerciales."
            )

        serializer = SchoolEventCreateSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        data = dict(serializer.validated_data)
        has_explicit_opportunity = "opportunity" in data
        opportunity = data.get("opportunity")

        if opportunity is None and not has_explicit_opportunity:
            opportunity = _single_visible_open_opportunity_for_school(
                request.user,
                school,
            )
            if opportunity is not None:
                data["opportunity"] = opportunity

        if (
            opportunity is not None
            and not visible_opportunities_queryset(request.user)
            .filter(
                pk=opportunity.pk,
                school=school,
            )
            .exists()
        ):
            raise serializers.ValidationError(
                {
                    "opportunity": (
                        "La oportunidad no pertenece al colegio "
                        "o no está dentro de tu alcance comercial."
                    )
                }
            )

        try:
            event = create_school_event(
                school=school,
                actor=request.user,
                **data,
            )
        except CRMPlanningError as exc:
            _raise_service_validation_error(exc)

        return Response(
            {
                "id": event.id,
                "title": event.title,
                "event_type": event.event_type,
                "assigned_to_id": event.assigned_to_id,
                "start_at": event.start_at,
                "end_at": event.end_at,
                "location": event.location,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="reminders",
        url_name="create-reminder",
    )
    def create_school_reminder(self, request, pk=None):
        school = self.get_object()

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para programar recordatorios comerciales."
            )

        serializer = SchoolReminderCreateSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        data = dict(serializer.validated_data)
        has_explicit_opportunity = "opportunity" in data
        opportunity = data.get("opportunity")

        if opportunity is None and not has_explicit_opportunity:
            opportunity = _single_visible_open_opportunity_for_school(
                request.user,
                school,
            )
            if opportunity is not None:
                data["opportunity"] = opportunity

        if (
            opportunity is not None
            and not visible_opportunities_queryset(request.user)
            .filter(
                pk=opportunity.pk,
                school=school,
            )
            .exists()
        ):
            raise serializers.ValidationError(
                {
                    "opportunity": (
                        "La oportunidad no pertenece al colegio "
                        "o no está dentro de tu alcance comercial."
                    )
                }
            )

        try:
            reminder = create_school_reminder(
                school=school,
                actor=request.user,
                **data,
            )
        except CRMPlanningError as exc:
            _raise_service_validation_error(exc)

        return Response(
            {
                "id": reminder.id,
                "title": reminder.title,
                "status": reminder.status,
                "user_id": reminder.user_id,
                "remind_at": reminder.remind_at,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="editorial-usages",
        url_name="editorial-usages",
    )
    def editorial_usages(self, request, pk=None):
        school = self.get_object()

        if request.method == "GET":
            usages = (
                school.editorial_usages
                .select_related(
                    "editorial",
                    "editorial__catalog_provider",
                    "provider",
                    "area",
                    "service__level",
                )
                .order_by(
                    "-year",
                    "editorial__name",
                    "area__name",
                )
            )

            return Response(
                SchoolEditorialUsageSerializer(
                    usages,
                    many=True,
                ).data
            )

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para registrar editoriales."
            )

        serializer = SchoolEditorialUsageWriteSerializer(
            data=request.data,
            context={"school": school},
        )
        serializer.is_valid(raise_exception=True)

        usage = serializer.save(
            school=school,
            recorded_by=request.user,
        )

        return Response(
            SchoolEditorialUsageSerializer(usage).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["patch"],
        url_path=r"editorial-usages/(?P<usage_id>[^/.]+)",
        url_name="editorial-usage-detail",
    )
    def editorial_usage_detail(
        self,
        request,
        pk=None,
        usage_id=None,
    ):
        school = self.get_object()

        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied(
                "No tienes permiso para modificar editoriales."
            )

        usage = (
            school.editorial_usages
            .select_related(
                "editorial",
                "editorial__catalog_provider",
                "provider",
                "area",
                "service__level",
            )
            .filter(pk=usage_id)
            .first()
        )

        if usage is None:
            return Response(
                {
                    "detail": (
                        "La información editorial "
                        "no pertenece a este colegio."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = SchoolEditorialUsageWriteSerializer(
            usage,
            data=request.data,
            partial=True,
            context={"school": school},
        )
        serializer.is_valid(raise_exception=True)

        usage = serializer.save(
            recorded_by=request.user,
        )

        return Response(
            SchoolEditorialUsageSerializer(usage).data
        )
    
class OpportunityViewSet(viewsets.ModelViewSet):
    permission_classes = [EsUsuarioCRM]
    pagination_class = CRMPageNumberPagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        now = timezone.now()

        next_activity_links = (
            CRMWorkItemLink.objects
            .filter(
                (
                    Q(
                        task__isnull=False,
                        task__status__in=[
                            "pending",
                            "in_progress",
                            "waiting",
                        ],
                    )
                    & (
                        Q(task__start_at__gte=now)
                        | Q(task__due_at__gte=now)
                        | Q(task__reminder_at__gte=now)
                    )
                )
                | Q(
                    event__isnull=False,
                    event__start_at__gte=now,
                )
                | Q(
                    reminder__isnull=False,
                    reminder__status__in=["pending", "seen"],
                    reminder__remind_at__gte=now,
                )
            )
            .select_related("task", "event", "reminder")
        )

        queryset = (
            visible_opportunities_queryset(self.request.user)
            .select_related(
                "school",
                "campaign",
                "pipeline",
                "stage",
                "primary_contact",
                "team",
                "owner",
                "owner__book_express_profile",
                "created_by",
                "closed_by",
            )
            .prefetch_related(
                Prefetch(
                    "work_item_links",
                    queryset=next_activity_links,
                    to_attr="prefetched_next_activity_links",
                )
            )
        )
        search = self.request.query_params.get("search", "").strip()
        school = self.request.query_params.get("school")
        campaign = self.request.query_params.get("campaign")
        pipeline = self.request.query_params.get("pipeline")
        stage = self.request.query_params.get("stage")
        team = self.request.query_params.get("team")
        owner = self.request.query_params.get("owner")
        category = self.request.query_params.get("category")
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(school__name__icontains=search)
                | Q(school__modular_code__icontains=search) | Q(owner__username__icontains=search)
                | Q(owner__first_name__icontains=search) | Q(owner__last_name__icontains=search)
            )
        if school:
            queryset = queryset.filter(school_id=school)
        if campaign:
            queryset = queryset.filter(campaign_id=campaign)
        if pipeline:
            queryset = queryset.filter(pipeline_id=pipeline)
        if stage:
            queryset = queryset.filter(stage_id=stage)
        if team:
            queryset = queryset.filter(team_id=team)
        if owner:
            queryset = queryset.filter(owner_id=owner)
        if category in {PipelineStage.Category.OPEN, PipelineStage.Category.WON, PipelineStage.Category.LOST}:
            queryset = queryset.filter(stage__category=category)
        return queryset.order_by("-updated_at", "-id")

    def get_serializer_class(self):
        if self.action == "list":
            return OpportunityListSerializer
        if self.action == "retrieve":
            return OpportunityDetailSerializer
        if self.action == "create":
            return OpportunityCreateSerializer
        if self.action in {"partial_update", "update"}:
            return OpportunityUpdateSerializer
        return OpportunityDetailSerializer

    def create(self, request, *args, **kwargs):
        if not usuario_puede_gestionar_oportunidades_propias(request.user):
            raise PermissionDenied("No tienes permiso para crear oportunidades.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        school = data["school"]
        if not visible_schools_queryset(request.user).filter(pk=school.pk).exists():
            raise PermissionDenied("No tienes acceso al colegio seleccionado.")
        can_assign = (
            usuario_es_administrador(request.user)
            or usuario_puede_asignar_oportunidades(request.user)
        )
        if not can_assign:
            data.pop("owner", None)
            data.pop("team", None)

        try:
            opportunity = create_opportunity(
                created_by=request.user,
                **data,
            )
        except OpportunityTransitionError as exc:
            _raise_service_validation_error(exc)
        return Response(OpportunityDetailSerializer(opportunity).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        opportunity = self.get_object()
        if not _user_can_manage_visible_opportunity(request.user, opportunity):
            raise PermissionDenied("No tienes permiso para modificar esta oportunidad.")
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "primary_contact" in data:
            contact = data["primary_contact"]
            if contact is not None and contact.school_id != opportunity.school_id:
                raise serializers.ValidationError({"primary_contact": "El contacto no pertenece al colegio de la oportunidad."})
        for field, value in data.items():
            setattr(opportunity, field, value)
        opportunity.full_clean()
        opportunity.save()
        return Response(OpportunityDetailSerializer(opportunity).data)

    @action(detail=True, methods=["post"], url_path="change-stage")
    def change_stage(self, request, pk=None):
        opportunity = self.get_object()
        if not _user_can_manage_visible_opportunity(request.user, opportunity):
            raise PermissionDenied("No tienes permiso para mover esta oportunidad.")
        serializer = OpportunityStageChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            opportunity = transition_opportunity_stage(
                opportunity=opportunity,
                to_stage=serializer.validated_data["stage"],
                changed_by=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except OpportunityTransitionError as exc:
            _raise_service_validation_error(exc)
        return Response(OpportunityDetailSerializer(opportunity).data)

    @action(detail=True, methods=["post"], url_path="reopen")
    def reopen(self, request, pk=None):
        opportunity = self.get_object()
        if not _user_can_manage_visible_opportunity(request.user, opportunity):
            raise PermissionDenied("No tienes permiso para reabrir esta oportunidad.")
        serializer = OpportunityReopenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            opportunity = reopen_opportunity(
                opportunity=opportunity,
                to_stage=serializer.validated_data["stage"],
                changed_by=request.user,
                reason=serializer.validated_data["reason"],
            )
        except OpportunityTransitionError as exc:
            _raise_service_validation_error(exc)
        return Response(OpportunityDetailSerializer(opportunity).data)

    @action(
        detail=True,
        methods=["get"],
        url_path="projection-base",
    )
    def projection_base(self, request, pk=None):
        opportunity = self.get_object()

        services = (
            opportunity.school.educational_services
            .filter(is_active=True)
            .select_related("campus", "level")
            .prefetch_related(
                "population_records__details__grade",
            )
            .order_by(
                "campus__sequence",
                "level__name",
                "id",
            )
        )

        return Response(
            {
                "campaign": CampaignSerializer(
                    opportunity.campaign
                ).data,
                "services": SchoolEducationalServiceSerializer(
                    services,
                    many=True,
                ).data,
            }
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="projection-products",
    )
    def projection_products(self, request, pk=None):
        opportunity = self.get_object()

        service_id = request.query_params.get("service")
        grade_id = request.query_params.get("grade")
        product_search = (
            request.query_params.get("product_search") or ""
        ).strip()
        editorial_id = request.query_params.get("editorial")
        commercial_line = (
            request.query_params.get("commercial_line") or ""
        ).strip()

        if commercial_line and commercial_line not in VALID_PROJECTION_LINES:
            raise serializers.ValidationError(
                {
                    "commercial_line": (
                        "La línea comercial debe ser Texto escolar "
                        "o Plan lector."
                    )
                }
            )

        if not service_id or not grade_id:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Debes indicar el nivel educativo y el grado "
                        "para consultar productos."
                    )
                }
            )

        service = (
            opportunity.school.educational_services
            .filter(pk=service_id, is_active=True)
            .select_related("campus", "level")
            .first()
        )

        if service is None:
            raise serializers.ValidationError(
                {
                    "service": (
                        "El nivel educativo no pertenece al colegio "
                        "de esta oportunidad."
                    )
                }
            )

        grade = Grade.objects.filter(
            pk=grade_id,
            is_active=True,
        ).first()

        if grade is None:
            raise serializers.ValidationError(
                {"grade": "El grado seleccionado no está disponible."}
            )

        if not grade_matches_level(
            grade=grade,
            level=service.level,
        ):
            raise serializers.ValidationError(
                {
                    "grade": (
                        f"{grade.name} no corresponde al nivel "
                        f"{service.level.name}."
                    )
                }
            )

        base_products = (
            Product.objects
            .filter(
                is_active=True,
                provider__is_active=True,
            )
            .filter(
                Q(level_id=service.level_id)
                | Q(level__isnull=True),
                Q(grade_id=grade.id)
                | Q(grade__isnull=True),
            )
        )

        if commercial_line:
            base_products = base_products.filter(
                commercial_line=commercial_line,
            )

        products = list(
            base_products
            .select_related(
                "provider",
                "level",
                "grade",
                "area",
                "series",
                "product_type",
            )
            .order_by("provider__name", "name", "id")
        )

        editorial_map = {
            product.provider_id: product.provider.name
            for product in products
        }
        editorial_options = [
            {"id": provider_id, "name": name}
            for provider_id, name in sorted(
                editorial_map.items(),
                key=lambda item: item[1].lower(),
            )
        ]

        if editorial_id:
            try:
                editorial_id = int(editorial_id)
            except (TypeError, ValueError) as exc:
                raise serializers.ValidationError(
                    {"editorial": "La editorial seleccionada no es válida."}
                ) from exc

            products = [
                product
                for product in products
                if product.provider_id == editorial_id
            ]

        if product_search:
            search_value = product_search.casefold()

            def matches_search(product):
                values = (
                    product.name,
                    product.provider.name,
                    product.area.name if product.area_id else "",
                    product.series.name if product.series_id else "",
                    product.level.name if product.level_id else "",
                    product.grade.name if product.grade_id else "",
                )
                return any(
                    search_value in str(value or "").casefold()
                    for value in values
                )

            products = [
                product
                for product in products
                if matches_search(product)
            ]

        choices = []

        for product in products[:150]:
            try:
                price = resolve_projection_price(
                    product=product,
                    campaign=opportunity.campaign,
                )
                price_available = True
                price_message = ""
            except CommercialProjectionError:
                price = None
                price_available = False
                price_message = (
                    "Falta un precio numérico activo para esta campaña "
                    "o un año anterior."
                )

            choices.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "commercial_line": product.commercial_line,
                    "editorial": {
                        "id": product.provider_id,
                        "name": product.provider.name,
                    },
                    "level": (
                        {
                            "id": product.level_id,
                            "name": product.level.name,
                        }
                        if product.level_id
                        else None
                    ),
                    "grade": (
                        {
                            "id": product.grade_id,
                            "name": product.grade.name,
                        }
                        if product.grade_id
                        else None
                    ),
                    "area": (
                        {
                            "id": product.area_id,
                            "name": product.area.name,
                        }
                        if product.area_id
                        else None
                    ),
                    "series": (
                        {
                            "id": product.series_id,
                            "name": product.series.name,
                        }
                        if product.series_id
                        else None
                    ),
                    "unit_price": (
                        str(price.price)
                        if price is not None
                        else None
                    ),
                    "price_year": (
                        price.year
                        if price is not None
                        else None
                    ),
                    "price_campaign": (
                        price.campaign
                        if price is not None
                        else ""
                    ),
                    "price_is_reference": (
                        price is not None
                        and price.year != opportunity.campaign.year
                    ),
                    "price_available": price_available,
                    "price_message": price_message,
                }
            )

        return Response(
            {
                "service": {
                    "id": service.id,
                    "level": {
                        "id": service.level_id,
                        "name": service.level.name,
                    },
                },
                "grade": {
                    "id": grade.id,
                    "name": grade.name,
                },
                "campaign": {
                    "id": opportunity.campaign_id,
                    "name": opportunity.campaign.name,
                    "year": opportunity.campaign.year,
                },
                "commercial_line": commercial_line or None,
                "editorials": editorial_options,
                "results": choices,
            }
        )

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="projection",
    )
    def projection(self, request, pk=None):
        opportunity = self.get_object()

        if request.method == "GET":
            projection = (
                opportunity.projections
                .filter(is_current=True)
                .select_related("created_by")
                .prefetch_related(
                    "grades__service__level",
                    "grades__grade",
                    "items__grade_line",
                    "items__product__provider",
                    "items__product__level",
                    "items__product__grade",
                    "items__product__area",
                    "items__product__product_type",
                )
                .first()
            )

            if projection is None:
                return Response(None)

            return Response(
                CommercialProjectionSerializer(
                    projection
                ).data
            )

        if not _user_can_manage_visible_opportunity(
            request.user,
            opportunity,
        ):
            raise PermissionDenied(
                "No tienes permiso para modificar la "
                "proyección de esta oportunidad."
            )

        serializer = CommercialProjectionCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            projection = create_commercial_projection_revision(
                opportunity=opportunity,
                actor=request.user,
                commercial_line=serializer.validated_data[
                    "commercial_line"
                ],
                grade_lines=serializer.validated_data["grades"],
                items=serializer.validated_data.get("items", []),
                notes=serializer.validated_data.get("notes", ""),
            )
        except CommercialProjectionError as exc:
            _raise_service_validation_error(exc)

        return Response(
            CommercialProjectionSerializer(projection).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="projection-history",
    )
    def projection_history(self, request, pk=None):
        opportunity = self.get_object()

        queryset = (
            opportunity.projections
            .select_related("created_by")
            .prefetch_related(
                "grades__service__level",
                "grades__grade",
                "items__grade_line",
                "items__product__provider",
                "items__product__level",
                "items__product__grade",
                "items__product__area",
                "items__product__product_type",
            )
            .order_by("-version")
        )

        return Response(
            CommercialProjectionSerializer(
                queryset,
                many=True,
            ).data
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="quotations/financial-preview",
    )
    def quotation_financial_preview(self, request, pk=None):
        opportunity = self.get_object()

        if not (
            usuario_es_administrador(request.user)
            or usuario_puede_supervisar_crm(request.user)
        ):
            raise PermissionDenied(
                "Solo supervisión comercial puede revisar "
                "costos y rentabilidad."
            )

        serializer = CommercialQuotationProjectionItemAdjustmentSerializer(
            data=request.data.get("items", []),
            many=True,
        )
        serializer.is_valid(raise_exception=True)

        try:
            previews = preview_commercial_quotation_financials(
                opportunity=opportunity,
                actor=request.user,
                item_adjustments=serializer.validated_data,
            )
        except CommercialQuotationError as exc:
            _raise_service_validation_error(exc)

        return Response({"items": previews})


    @action(
        detail=True,
        methods=["post"],
        url_path="quotations/from-projection",
    )
    def quotation_from_projection(self, request, pk=None):
        opportunity = self.get_object()

        if not _user_can_manage_visible_opportunity(
            request.user,
            opportunity,
        ):
            raise PermissionDenied(
                "No tienes permiso para crear cotizaciones "
                "en esta oportunidad."
            )

        serializer = CommercialQuotationFromProjectionSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            quotation = create_commercial_quotation_from_projection(
                opportunity=opportunity,
                actor=request.user,
                item_adjustments=serializer.validated_data.get(
                    "items",
                    [],
                ),
                sale_mode=serializer.validated_data.get("sale_mode", ""),
                service_date=serializer.validated_data.get(
                    "service_date"
                ),
                service_end_date=serializer.validated_data.get(
                    "service_end_date"
                ),
                fair_start_time=serializer.validated_data.get(
                    "fair_start_time"
                ),
                fair_end_time=serializer.validated_data.get(
                    "fair_end_time"
                ),
                notes=serializer.validated_data.get("notes", ""),
            )
        except CommercialQuotationError as exc:
            _raise_service_validation_error(exc)

        quotation = (
            CommercialQuotation.objects
            .select_related(
                "source_projection",
                "created_by",
                "sent_by",
                "accepted_by",
                "reopened_by",
                "discount_approved_by",
            )
            .prefetch_related("items__product")
            .get(pk=quotation.pk)
        )

        return Response(
            CommercialQuotationSerializer(
                quotation,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"], url_path="quotations")
    def quotations(self, request, pk=None):
        opportunity = self.get_object()

        if request.method == "GET":
            queryset = (
                opportunity.quotations
                .select_related(
                    "source_projection",
                    "created_by",
                    "sent_by",
                    "accepted_by",
                    "discount_approved_by",
                )
                .prefetch_related("items__product")
                .order_by("-version")
            )
            return Response(
                CommercialQuotationSerializer(
                    queryset,
                    many=True,
                    context={"request": request},
                ).data
            )

        if not _user_can_manage_visible_opportunity(
            request.user,
            opportunity,
        ):
            raise PermissionDenied(
                "No tienes permiso para crear cotizaciones "
                "en esta oportunidad."
            )

        serializer = CommercialQuotationCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            quotation = create_commercial_quotation(
                opportunity=opportunity,
                actor=request.user,
                items=serializer.validated_data["items"],
                sale_mode=serializer.validated_data.get("sale_mode", ""),
                service_date=serializer.validated_data.get(
                    "service_date"
                ),
                service_end_date=serializer.validated_data.get(
                    "service_end_date"
                ),
                fair_start_time=serializer.validated_data.get(
                    "fair_start_time"
                ),
                fair_end_time=serializer.validated_data.get(
                    "fair_end_time"
                ),
                notes=serializer.validated_data.get("notes", ""),
            )
        except CommercialQuotationError as exc:
            _raise_service_validation_error(exc)

        quotation = (
            CommercialQuotation.objects
            .select_related(
                "source_projection",
                "created_by",
                "sent_by",
                "accepted_by",
                "reopened_by",
                "discount_approved_by",
            )
            .prefetch_related("items__product")
            .get(pk=quotation.pk)
        )

        return Response(
            CommercialQuotationSerializer(
                quotation,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["patch"],
        url_path=r"quotations/(?P<quotation_id>[^/.]+)/draft",
    )
    def update_quotation_draft(
        self,
        request,
        pk=None,
        quotation_id=None,
    ):
        opportunity = self.get_object()

        if not _user_can_manage_visible_opportunity(
            request.user,
            opportunity,
        ):
            raise PermissionDenied(
                "No tienes permiso para editar cotizaciones "
                "en esta oportunidad."
            )

        quotation = opportunity.quotations.filter(
            pk=quotation_id
        ).first()

        if quotation is None:
            raise serializers.ValidationError(
                {
                    "quotation": (
                        "La cotización no pertenece a esta oportunidad."
                    )
                }
            )

        serializer = CommercialQuotationFromProjectionSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            quotation = update_commercial_quotation_from_projection(
                quotation=quotation,
                actor=request.user,
                item_adjustments=serializer.validated_data.get(
                    "items",
                    [],
                ),
                sale_mode=serializer.validated_data.get(
                    "sale_mode",
                    quotation.sale_mode,
                ),
                service_date=serializer.validated_data.get(
                    "service_date",
                    quotation.service_date,
                ),
                service_end_date=serializer.validated_data.get(
                    "service_end_date",
                    quotation.service_end_date,
                ),
                fair_start_time=serializer.validated_data.get(
                    "fair_start_time",
                    quotation.fair_start_time,
                ),
                fair_end_time=serializer.validated_data.get(
                    "fair_end_time",
                    quotation.fair_end_time,
                ),
                notes=serializer.validated_data.get(
                    "notes",
                    quotation.notes,
                ),
            )
        except CommercialQuotationError as exc:
            _raise_service_validation_error(exc)

        quotation = (
            CommercialQuotation.objects
            .select_related(
                "source_projection",
                "created_by",
                "sent_by",
                "accepted_by",
                "reopened_by",
                "discount_approved_by",
            )
            .prefetch_related("items__product")
            .get(pk=quotation.pk)
        )

        return Response(
            CommercialQuotationSerializer(
                quotation,
                context={"request": request},
            ).data
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"quotations/(?P<quotation_id>[^/.]+)/send",
    )
    def send_quotation(self, request, pk=None, quotation_id=None):
        opportunity = self.get_object()

        if not _user_can_manage_visible_opportunity(
            request.user,
            opportunity,
        ):
            raise PermissionDenied(
                "No tienes permiso para enviar cotizaciones "
                "en esta oportunidad."
            )

        quotation = opportunity.quotations.filter(
            pk=quotation_id
        ).first()

        if quotation is None:
            raise serializers.ValidationError(
                {
                    "quotation": (
                        "La cotización no pertenece a esta oportunidad."
                    )
                }
            )

        try:
            quotation = send_commercial_quotation(
                quotation=quotation,
                actor=request.user,
            )
        except CommercialQuotationError as exc:
            _raise_service_validation_error(exc)

        quotation = (
            CommercialQuotation.objects
            .select_related(
                "source_projection",
                "created_by",
                "sent_by",
                "accepted_by",
                "reopened_by",
                "discount_approved_by",
            )
            .prefetch_related("items__product")
            .get(pk=quotation.pk)
        )

        return Response(
            CommercialQuotationSerializer(
                quotation,
                context={"request": request},
            ).data
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"quotations/(?P<quotation_id>[^/.]+)/approve-discount",
    )
    def approve_quotation_discount(
        self,
        request,
        pk=None,
        quotation_id=None,
    ):
        opportunity = self.get_object()

        if not (
            usuario_es_administrador(request.user)
            or usuario_puede_supervisar_crm(request.user)
        ):
            raise PermissionDenied(
                "Solo un supervisor comercial puede aprobar "
                "descuentos superiores al estándar."
            )

        quotation = opportunity.quotations.filter(
            pk=quotation_id
        ).first()

        if quotation is None:
            raise serializers.ValidationError(
                {
                    "quotation": (
                        "La cotización no pertenece a esta oportunidad."
                    )
                }
            )

        serializer = CommercialQuotationDiscountApprovalSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            quotation = approve_commercial_quotation_discount(
                quotation=quotation,
                actor=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except CommercialQuotationError as exc:
            _raise_service_validation_error(exc)

        quotation = (
            CommercialQuotation.objects
            .select_related(
                "source_projection",
                "created_by",
                "sent_by",
                "accepted_by",
                "reopened_by",
                "discount_approved_by",
            )
            .prefetch_related("items__product")
            .get(pk=quotation.pk)
        )

        return Response(
            CommercialQuotationSerializer(
                quotation,
                context={"request": request},
            ).data
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"quotations/(?P<quotation_id>[^/.]+)/accept",
    )
    def accept_quotation(self, request, pk=None, quotation_id=None):
        opportunity = self.get_object()

        if not _user_can_manage_visible_opportunity(
            request.user,
            opportunity,
        ):
            raise PermissionDenied(
                "No tienes permiso para aceptar cotizaciones "
                "en esta oportunidad."
            )

        quotation = opportunity.quotations.filter(
            pk=quotation_id
        ).first()

        if quotation is None:
            raise serializers.ValidationError(
                {
                    "quotation": (
                        "La cotización no pertenece a esta oportunidad."
                    )
                }
            )

        try:
            quotation = accept_commercial_quotation(
                quotation=quotation,
                actor=request.user,
            )
        except CommercialQuotationError as exc:
            _raise_service_validation_error(exc)

        quotation = (
            CommercialQuotation.objects
            .select_related(
                "source_projection",
                "created_by",
                "sent_by",
                "accepted_by",
                "reopened_by",
                "discount_approved_by",
            )
            .prefetch_related("items__product")
            .get(pk=quotation.pk)
        )

        return Response(
            CommercialQuotationSerializer(
                quotation,
                context={"request": request},
            ).data
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"quotations/(?P<quotation_id>[^/.]+)/reopen-negotiation",
    )
    def reopen_quotation_negotiation(
        self,
        request,
        pk=None,
        quotation_id=None,
    ):
        opportunity = self.get_object()

        if not _user_can_manage_visible_opportunity(
            request.user,
            opportunity,
        ):
            raise PermissionDenied(
                "No tienes permiso para reabrir esta negociación."
            )

        quotation = opportunity.quotations.filter(
            pk=quotation_id
        ).first()

        if quotation is None:
            raise serializers.ValidationError(
                {
                    "quotation": (
                        "La cotización no pertenece a esta oportunidad."
                    )
                }
            )

        serializer = CommercialQuotationReopenSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            quotation = reopen_commercial_quotation_negotiation(
                quotation=quotation,
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except CommercialQuotationError as exc:
            _raise_service_validation_error(exc)

        quotation = (
            CommercialQuotation.objects
            .select_related(
                "source_projection",
                "created_by",
                "sent_by",
                "accepted_by",
                "reopened_by",
                "discount_approved_by",
            )
            .prefetch_related("items__product")
            .get(pk=quotation.pk)
        )

        return Response(
            CommercialQuotationSerializer(
                quotation,
                context={"request": request},
            ).data
        )

    @action(detail=True, methods=["get", "post"], url_path="adoptions")
    def adoptions(self, request, pk=None):
        opportunity = self.get_object()

        if request.method == "GET":
            queryset = (
                opportunity.adoptions
                .select_related(
                    "advisor",
                    "advisor__book_express_profile",
                    "confirmed_by",
                    "authorized_contact",
                )
                .prefetch_related(
                    "items__product",
                    "items__quotation_item",
                )
                .order_by("-version")
            )
            return Response(
                AdoptionSerializer(
                    queryset,
                    many=True,
                ).data
            )

        if not _user_can_manage_visible_opportunity(
            request.user,
            opportunity,
        ):
            raise PermissionDenied(
                "No tienes permiso para confirmar adopciones "
                "en esta oportunidad."
            )

        serializer = AdoptionConfirmSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        quotation = serializer.validated_data["quotation"]

        if quotation.opportunity_id != opportunity.id:
            raise serializers.ValidationError(
                {
                    "quotation": (
                        "La cotización no pertenece a esta oportunidad."
                    )
                }
            )

        contact = serializer.validated_data["authorized_contact"]

        if contact.school_id != opportunity.school_id:
            raise serializers.ValidationError(
                {
                    "authorized_contact": (
                        "El contacto no pertenece al colegio "
                        "de esta oportunidad."
                    )
                }
            )

        try:
            adoption = confirm_adoption(
                quotation=quotation,
                authorized_contact=contact,
                signed_at=serializer.validated_data["signed_at"],
                actor=request.user,
                notes=serializer.validated_data.get("notes", ""),
            )
        except AdoptionError as exc:
            _raise_service_validation_error(exc)

        adoption = (
            Adoption.objects
            .select_related(
                "advisor",
                "advisor__book_express_profile",
                "confirmed_by",
                "authorized_contact",
            )
            .prefetch_related(
                "items__product",
                "items__quotation_item",
            )
            .get(pk=adoption.pk)
        )

        return Response(
            AdoptionSerializer(adoption).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        opportunity = self.get_object()
        queryset = opportunity.stage_history.select_related(
            "from_stage",
            "to_stage",
            "changed_by",
        ).order_by("-created_at", "-id")
        return Response(
            OpportunityStageHistorySerializer(
                queryset,
                many=True,
            ).data
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="commercial-history",
        url_name="commercial-history",
    )
    def commercial_history(self, request, pk=None):
        opportunity = self.get_object()
        activities = (
            visible_commercial_activities_queryset(request.user)
            .filter(opportunity=opportunity)
        )
        events = build_opportunity_commercial_history(
            opportunity=opportunity,
            activities_queryset=activities,
        )
        return Response(
            CRMCommercialHistoryEventSerializer(
                events,
                many=True,
            ).data
        )

    @action(detail=True, methods=["get", "post"], url_path="activities")
    def activities(self, request, pk=None):
        opportunity = self.get_object()
        if request.method == "GET":
            queryset = visible_commercial_activities_queryset(request.user).filter(opportunity=opportunity).select_related(
                "contact", "performed_by", "created_by"
            ).prefetch_related("evidences__uploaded_by").order_by("-occurred_at", "-id")
            page = self.paginate_queryset(queryset)
            if page is not None:
                return self.get_paginated_response(CommercialActivitySerializer(
                    page,
                    many=True,
                    context={"request": request},
                ).data)
            return Response(CommercialActivitySerializer(
                queryset,
                many=True,
                context={"request": request},
            ).data)
        if not _user_can_manage_visible_opportunity(request.user, opportunity):
            raise PermissionDenied("No tienes permiso para registrar actividad en esta oportunidad.")
        serializer = CommercialActivityCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            activity = record_commercial_activity(
                opportunity=opportunity,
                performed_by=request.user,
                created_by=request.user,
                **serializer.validated_data,
            )
        except CommercialActivityError as exc:
            _raise_service_validation_error(exc)
        return Response(
            CommercialActivitySerializer(
                activity,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"activities/(?P<activity_id>[^/.]+)/evidence",
        url_name="activity-evidence",
    )
    def activity_evidence(
        self,
        request,
        pk=None,
        activity_id=None,
    ):
        opportunity = self.get_object()

        if not _user_can_manage_visible_opportunity(
            request.user,
            opportunity,
        ):
            raise PermissionDenied(
                "No tienes permiso para adjuntar evidencias "
                "en esta oportunidad."
            )

        if opportunity.is_closed:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "La oportunidad está cerrada. "
                        "Adjunta evidencias antes del cierre comercial."
                    )
                }
            )

        activity = (
            visible_commercial_activities_queryset(request.user)
            .filter(
                pk=activity_id,
                opportunity=opportunity,
            )
            .select_related(
                "school",
                "opportunity",
                "contact",
            )
            .first()
        )

        if activity is None:
            return Response(
                {
                    "detail": (
                        "La actividad no pertenece a esta oportunidad."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CommercialActivityEvidenceCreateSerializer(
            data=request.data,
            context={
                "activity": activity,
                "uploaded_by": request.user,
            },
        )
        serializer.is_valid(raise_exception=True)
        evidence = serializer.save()

        record_history_event(
            school=opportunity.school,
            opportunity=opportunity,
            contact=activity.contact,
            actor=request.user,
            category="evidence",
            event_type="activity_evidence_added",
            title="Evidencia adjuntada",
            description=evidence.original_name,
            source_type="commercial_activity_evidence",
            source_id=evidence.id,
            metadata={
                "activity_id": activity.id,
                "evidence_id": evidence.id,
                "evidence_type": evidence.evidence_type,
            },
        )

        return Response(
            CommercialActivityEvidenceSerializer(
                evidence,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="work-items")
    def work_items(self, request, pk=None):
        opportunity = self.get_object()
        queryset = work_items_for_opportunity(opportunity)
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(WorkItemLinkSerializer(page, many=True).data)
        return Response(WorkItemLinkSerializer(queryset, many=True).data)

    @action(detail=True, methods=["post"], url_path="tasks")
    def create_task(self, request, pk=None):
        opportunity = self.get_object()
        if not _user_can_manage_visible_opportunity(request.user, opportunity):
            raise PermissionDenied("No tienes permiso para programar trabajo en esta oportunidad.")
        serializer = OpportunityTaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            task = create_opportunity_task(opportunity=opportunity, actor=request.user, **serializer.validated_data)
        except CRMPlanningError as exc:
            _raise_service_validation_error(exc)
        return Response({
            "id": task.id, "title": task.title, "status": task.status, "priority": task.priority,
            "assigned_to_id": task.assigned_to_id, "due_at": task.due_at, "reminder_at": task.reminder_at,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="events")
    def create_event(self, request, pk=None):
        opportunity = self.get_object()
        if not _user_can_manage_visible_opportunity(request.user, opportunity):
            raise PermissionDenied("No tienes permiso para programar eventos en esta oportunidad.")
        serializer = OpportunityEventCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            event = create_opportunity_event(opportunity=opportunity, actor=request.user, **serializer.validated_data)
        except CRMPlanningError as exc:
            _raise_service_validation_error(exc)
        return Response({
            "id": event.id, "title": event.title, "event_type": event.event_type,
            "assigned_to_id": event.assigned_to_id, "start_at": event.start_at,
            "end_at": event.end_at, "location": event.location,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="reminders")
    def create_reminder(self, request, pk=None):
        opportunity = self.get_object()
        if not _user_can_manage_visible_opportunity(request.user, opportunity):
            raise PermissionDenied("No tienes permiso para programar recordatorios en esta oportunidad.")
        serializer = OpportunityReminderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reminder = create_opportunity_reminder(opportunity=opportunity, actor=request.user, **serializer.validated_data)
        except CRMPlanningError as exc:
            _raise_service_validation_error(exc)
        return Response({
            "id": reminder.id, "title": reminder.title, "status": reminder.status,
            "user_id": reminder.user_id, "remind_at": reminder.remind_at,
        }, status=status.HTTP_201_CREATED)