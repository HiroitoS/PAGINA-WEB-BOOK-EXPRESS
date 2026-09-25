from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import usuario_es_administrador
from crm.models import (
    Adoption,
    Campaign,
    CommercialQuotation,
    CommercialTeam,
    CommercialTeamMembership,
    CRMWorkItemLink,
    MarketEditorial,
    Pipeline,
    PipelineStage,
    School,
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
    CommercialActivityError,
    CommercialQuotationError,
    OpportunityTransitionError,
    accept_commercial_quotation,
    confirm_adoption,
    create_commercial_quotation,
    create_opportunity,
    create_opportunity_event,
    create_opportunity_reminder,
    create_opportunity_task,
    create_school_event,
    create_school_reminder,
    create_school_task,
    record_commercial_activity,
    send_commercial_quotation,
    reopen_opportunity,
    transition_opportunity_stage,
)

from .pagination import CRMPageNumberPagination
from .serializers import (
    AdoptionConfirmSerializer,
    AdoptionSerializer,
    CampaignSerializer,
    CommercialActivityCreateSerializer,
    CommercialActivitySerializer,
    CommercialQuotationCreateSerializer,
    CommercialQuotationSerializer,
    CommercialTeamDetailSerializer,
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
    SchoolDetailSerializer,
    SchoolEducationalServiceSerializer,
    SchoolEducationalServiceWriteSerializer,
    SchoolEventCreateSerializer,
    SchoolListSerializer,
    SchoolPopulationRecordSerializer,
    SchoolPopulationRecordWriteSerializer,
    SchoolReminderCreateSerializer,
    SchoolTaskCreateSerializer,
    SchoolWriteSerializer,
    WorkItemLinkSerializer,
    SchoolEditorialUsageSerializer,
    SchoolEditorialUsageWriteSerializer,
    MarketEditorialCreateSerializer,
    MarketEditorialSerializer,
)


def _raise_service_validation_error(exc):
    if hasattr(exc, "message_dict"):
        raise serializers.ValidationError(exc.message_dict)
    messages = getattr(exc, "messages", None)
    if messages:
        raise serializers.ValidationError({"detail": messages})
    raise serializers.ValidationError({"detail": str(exc)})


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


class CommercialTeamViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [EsUsuarioCRM]
    pagination_class = None
    serializer_class = CommercialTeamDetailSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = CommercialTeam.objects.filter(is_active=True)
        if usuario_es_administrador(user):
            return queryset.order_by("name")
        return queryset.filter(memberships__user=user, memberships__is_active=True).distinct().order_by("name")


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
            .order_by("-occurred_at", "-id")
        )

        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(
                CommercialActivitySerializer(
                    page,
                    many=True,
                ).data
            )

        return Response(
            CommercialActivitySerializer(
                queryset,
                many=True,
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

class SchoolViewSet(viewsets.ModelViewSet):
    permission_classes = [EsUsuarioCRM]
    pagination_class = CRMPageNumberPagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = (
            visible_schools_queryset(self.request.user)
            .select_related("team", "owner")
            .prefetch_related(
                "levels",
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
        is_active = self.request.query_params.get("is_active")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(institution_code__icontains=search)
                | Q(modular_code__icontains=search)
                | Q(educational_services__modular_code__icontains=search)
                | Q(ruc__icontains=search)
                | Q(phone__icontains=search) | Q(whatsapp__icontains=search) | Q(email__icontains=search)
                | Q(owner__username__icontains=search) | Q(owner__first_name__icontains=search)
                | Q(owner__last_name__icontains=search)
            )
        if team:
            queryset = queryset.filter(team_id=team)
        if owner:
            queryset = queryset.filter(owner_id=owner)
        if department:
            queryset = queryset.filter(department__iexact=department)
        if province:
            queryset = queryset.filter(province__iexact=province)
        if district:
            queryset = queryset.filter(district__iexact=district)
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
        if levels:
            school.levels.set(levels)
        return Response(SchoolDetailSerializer(school).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        if not usuario_puede_gestionar_colegios(request.user):
            raise PermissionDenied("No tienes permiso para modificar colegios.")
        school = self.get_object()
        serializer = self.get_serializer(school, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        can_assign = usuario_es_administrador(request.user) or usuario_puede_asignar_colegios(request.user)
        if not can_assign:
            if "owner" in data and data["owner"] != school.owner:
                raise PermissionDenied("No puedes reasignar el colegio.")
            if "team" in data and data["team"] != school.team:
                raise PermissionDenied("No puedes cambiar el equipo comercial del colegio.")
        levels = data.pop("levels", None)
        for field, value in data.items():
            setattr(school, field, value)
        school.full_clean()
        school.save()
        if levels is not None:
            school.levels.set(levels)
        return Response(SchoolDetailSerializer(school).data)

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
                .select_related("level")
                .prefetch_related(
                    "population_records",
                    "population_records__details__grade",
                )
                .order_by("level__name", "id")
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
                .order_by("-occurred_at", "-id")
            )

            page = self.paginate_queryset(queryset)

            if page is not None:
                return self.get_paginated_response(
                    CommercialActivitySerializer(
                        page,
                        many=True,
                    ).data
                )

            return Response(
                CommercialActivitySerializer(
                    queryset,
                    many=True,
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
        opportunity = data.pop("opportunity", None)

        if opportunity is None:
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
            CommercialActivitySerializer(activity).data,
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
        opportunity = data.get("opportunity")

        if opportunity is None:
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
        opportunity = data.get("opportunity")

        if opportunity is None:
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
        opportunity = data.get("opportunity")

        if opportunity is None:
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

    @action(detail=True, methods=["get", "post"], url_path="quotations")
    def quotations(self, request, pk=None):
        opportunity = self.get_object()

        if request.method == "GET":
            queryset = (
                opportunity.quotations
                .select_related(
                    "created_by",
                    "sent_by",
                    "accepted_by",
                )
                .prefetch_related("items__product")
                .order_by("-version")
            )
            return Response(
                CommercialQuotationSerializer(
                    queryset,
                    many=True,
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
                notes=serializer.validated_data.get("notes", ""),
            )
        except CommercialQuotationError as exc:
            _raise_service_validation_error(exc)

        quotation = (
            CommercialQuotation.objects
            .select_related(
                "created_by",
                "sent_by",
                "accepted_by",
            )
            .prefetch_related("items__product")
            .get(pk=quotation.pk)
        )

        return Response(
            CommercialQuotationSerializer(quotation).data,
            status=status.HTTP_201_CREATED,
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
                "created_by",
                "sent_by",
                "accepted_by",
            )
            .prefetch_related("items__product")
            .get(pk=quotation.pk)
        )

        return Response(
            CommercialQuotationSerializer(quotation).data
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
                "created_by",
                "sent_by",
                "accepted_by",
            )
            .prefetch_related("items__product")
            .get(pk=quotation.pk)
        )

        return Response(
            CommercialQuotationSerializer(quotation).data
        )

    @action(detail=True, methods=["get", "post"], url_path="adoptions")
    def adoptions(self, request, pk=None):
        opportunity = self.get_object()

        if request.method == "GET":
            queryset = (
                opportunity.adoptions
                .select_related(
                    "advisor",
                    "confirmed_by",
                    "authorized_contact",
                )
                .prefetch_related("items__product")
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
                "confirmed_by",
                "authorized_contact",
            )
            .prefetch_related("items__product")
            .get(pk=adoption.pk)
        )

        return Response(
            AdoptionSerializer(adoption).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        opportunity = self.get_object()
        queryset = opportunity.stage_history.select_related("from_stage", "to_stage", "changed_by").order_by("-created_at", "-id")
        return Response(OpportunityStageHistorySerializer(queryset, many=True).data)

    @action(detail=True, methods=["get", "post"], url_path="activities")
    def activities(self, request, pk=None):
        opportunity = self.get_object()
        if request.method == "GET":
            queryset = visible_commercial_activities_queryset(request.user).filter(opportunity=opportunity).select_related(
                "contact", "performed_by", "created_by"
            ).order_by("-occurred_at", "-id")
            page = self.paginate_queryset(queryset)
            if page is not None:
                return self.get_paginated_response(CommercialActivitySerializer(page, many=True).data)
            return Response(CommercialActivitySerializer(queryset, many=True).data)
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
        return Response(CommercialActivitySerializer(activity).data, status=status.HTTP_201_CREATED)

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