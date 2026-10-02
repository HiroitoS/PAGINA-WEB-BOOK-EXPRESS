from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import serializers

from django.utils import timezone
from django.utils.text import slugify

from accounts.permissions import usuario_es_administrador
from catalog.models import Area, Grade, Level, Product
from crm.models import (
    Adoption,
    AdoptionItem,
    Campaign,
    CommercialActivity,
    CommercialQuotation,
    CommercialQuotationItem,
    CommercialProjection,
    CommercialProjectionGrade,
    CommercialProjectionItem,
    CommercialTeam,
    CommercialTeamMembership,
    CRMWorkItemLink,
    Opportunity,
    OpportunityStageHistory,
    Pipeline,
    PipelineStage,
    School,
    SchoolCommercialProfile,
    SchoolContact,
    SchoolEditorialUsage,
    SchoolEducationalService,
    SchoolPopulationRecord,
    SchoolPopulationDetail,
    MarketEditorial,
)
from crm.permissions import usuario_puede_supervisar_crm
from crm.services.commercial_lines import green_margin_threshold
from workspaces.models import CalendarEvent, Task, WorkspaceGroup


User = get_user_model()


def _request_can_view_quotation_financials(serializer):
    request = serializer.context.get("request")
    user = getattr(request, "user", None)

    if user is None or not user.is_authenticated:
        return False

    return (
        usuario_es_administrador(user)
        or usuario_puede_supervisar_crm(user)
    )


class UserSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    whatsapp = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "whatsapp",
        )

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_phone(self, obj):
        profile = getattr(obj, "book_express_profile", None)
        return getattr(profile, "phone", "") if profile else ""

    def get_whatsapp(self, obj):
        profile = getattr(obj, "book_express_profile", None)
        return getattr(profile, "whatsapp", "") if profile else ""


class LevelSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Level
        fields = ("id", "name")


class GradeSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Grade
        fields = ("id", "name", "order")


class CommercialTeamSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = CommercialTeam
        fields = ("id", "code", "name")


class CampaignSerializer(serializers.ModelSerializer):
    campaign_type_display = serializers.CharField(source="get_campaign_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Campaign
        fields = (
            "id", "code", "name", "year", "campaign_type", "campaign_type_display",
            "status", "status_display", "starts_on", "ends_on",
        )


class PipelineStageSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = PipelineStage
        fields = (
            "id", "code", "name", "order", "category", "category_display",
            "is_initial", "is_active",
        )


class PipelineSerializer(serializers.ModelSerializer):
    stages = PipelineStageSerializer(many=True, read_only=True)

    class Meta:
        model = Pipeline
        fields = ("id", "code", "name", "description", "is_default", "is_active", "stages")


class CommercialTeamMemberSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = CommercialTeamMembership
        fields = ("id", "user", "role", "role_display", "is_active")


class CommercialTeamDetailSerializer(serializers.ModelSerializer):
    memberships = serializers.SerializerMethodField()

    class Meta:
        model = CommercialTeam
        fields = ("id", "code", "name", "description", "is_active", "memberships")

    def get_memberships(self, obj):
        queryset = obj.memberships.filter(is_active=True, user__is_active=True).select_related("user")
        return CommercialTeamMemberSerializer(queryset, many=True).data


class SchoolContactSerializer(serializers.ModelSerializer):
    decision_role_display = serializers.CharField(
        source="get_decision_role_display",
        read_only=True,
    )

    class Meta:
        model = SchoolContact
        fields = (
            "id",
            "full_name",
            "position",
            "decision_role",
            "decision_role_display",
            "relationship_level",
            "phone",
            "whatsapp",
            "email",
            "is_primary",
            "is_active",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class SchoolContactCRMSerializer(SchoolContactSerializer):
    school = serializers.SerializerMethodField()

    class Meta(SchoolContactSerializer.Meta):
        fields = SchoolContactSerializer.Meta.fields + ("school",)

    def get_school(self, obj):
        return {
            "id": obj.school_id,
            "name": obj.school.name,
        }


class SchoolPopulationDetailSerializer(serializers.ModelSerializer):
    grade = GradeSummarySerializer(read_only=True)
    student_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = SchoolPopulationDetail
        fields = (
            "id",
            "grade",
            "section_count",
            "students_per_section",
            "student_count",
        )


class SchoolPopulationDetailWriteSerializer(serializers.ModelSerializer):
    grade = serializers.PrimaryKeyRelatedField(
        queryset=Grade.objects.filter(is_active=True),
    )

    class Meta:
        model = SchoolPopulationDetail
        fields = (
            "grade",
            "section_count",
            "students_per_section",
        )


class SchoolPopulationRecordSerializer(serializers.ModelSerializer):
    source_display = serializers.CharField(
        source="get_source_display",
        read_only=True,
    )
    details = SchoolPopulationDetailSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = SchoolPopulationRecord
        fields = (
            "id",
            "year",
            "student_count",
            "source",
            "source_display",
            "source_detail",
            "is_current",
            "details",
            "created_at",
            "updated_at",
        )


class SchoolPopulationRecordWriteSerializer(serializers.ModelSerializer):
    student_count = serializers.IntegerField(
        min_value=0,
        required=False,
    )
    details = SchoolPopulationDetailWriteSerializer(
        many=True,
        required=False,
    )

    class Meta:
        model = SchoolPopulationRecord
        fields = (
            "year",
            "student_count",
            "source",
            "source_detail",
            "details",
        )

    def validate(self, attrs):
        details = attrs.get("details")
        student_count = attrs.get("student_count")

        if details:
            grade_ids = [detail["grade"].id for detail in details]

            if len(grade_ids) != len(set(grade_ids)):
                raise serializers.ValidationError(
                    {
                        "details": (
                            "No puedes registrar dos veces el mismo grado "
                            "en un nivel."
                        )
                    }
                )

            attrs["student_count"] = sum(
                detail["section_count"]
                * detail["students_per_section"]
                for detail in details
            )
        elif student_count is None:
            raise serializers.ValidationError(
                {
                    "student_count": (
                        "Registra la cantidad de alumnos o el detalle "
                        "de población por grado."
                    )
                }
            )

        return attrs

    def create(self, validated_data):
        details = validated_data.pop("details", [])
        population = SchoolPopulationRecord.objects.create(
            **validated_data,
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

        return population


class SchoolEducationalServiceSerializer(serializers.ModelSerializer):
    level = LevelSummarySerializer(read_only=True)
    latest_population = serializers.SerializerMethodField()

    class Meta:
        model = SchoolEducationalService
        fields = (
            "id",
            "level",
            "modular_code",
            "modality",
            "is_active",
            "latest_population",
        )

    def get_latest_population(self, obj):
        record = next(
            (
                item
                for item in obj.population_records.all()
                if item.is_current
            ),
            None,
        )

        if record is None:
            return None

        return SchoolPopulationRecordSerializer(record).data

class SchoolEducationalServiceWriteSerializer(serializers.ModelSerializer):
    level = serializers.PrimaryKeyRelatedField(
        queryset=Level.objects.filter(is_active=True),
    )

    class Meta:
        model = SchoolEducationalService
        fields = (
            "level",
            "modular_code",
            "modality",
            "is_active",
        )

    def validate_modular_code(self, value):
        modular_code = (value or "").strip()

        if not modular_code:
            return None

        queryset = SchoolEducationalService.objects.filter(
            modular_code=modular_code,
        )

        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "Este código modular ya está registrado."
            )

        return modular_code

    def validate(self, attrs):
        school = self.context.get("school")
        level = attrs.get("level")

        if school is not None and level is not None:
            queryset = SchoolEducationalService.objects.filter(
                school=school,
                level=level,
            )

            if self.instance is not None:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise serializers.ValidationError(
                    {
                        "level": (
                            "Este nivel educativo ya está registrado "
                            "en el colegio."
                        )
                    }
                )

        return attrs


class MarketEditorialSerializer(serializers.ModelSerializer):
    verification_status_display = serializers.CharField(
        source="get_verification_status_display",
        read_only=True,
    )
    catalog_provider = serializers.SerializerMethodField()

    class Meta:
        model = MarketEditorial
        fields = (
            "id",
            "name",
            "catalog_provider",
            "verification_status",
            "verification_status_display",
            "is_active",
        )

    def get_catalog_provider(self, obj):
        if obj.catalog_provider_id is None:
            return None

        return {
            "id": obj.catalog_provider_id,
            "name": obj.catalog_provider.name,
        }


class MarketEditorialCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketEditorial
        fields = ("name",)

    def validate_name(self, value):
        name = " ".join((value or "").split())

        if not name:
            raise serializers.ValidationError(
                "Ingresa el nombre de la editorial."
            )

        normalized_name = slugify(name) or name.casefold()

        if MarketEditorial.objects.filter(
            normalized_name=normalized_name,
        ).exists():
            raise serializers.ValidationError(
                "Esta editorial ya está registrada."
            )

        return name

class SchoolEditorialUsageSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    source_display = serializers.CharField(
        source="get_source_display",
        read_only=True,
    )
    service = serializers.SerializerMethodField()
    area = serializers.SerializerMethodField()
    editorial = serializers.SerializerMethodField()
    provider = serializers.SerializerMethodField()

    class Meta:
        model = SchoolEditorialUsage
        fields = (
            "id",
            "year",
            "service",
            "area",
            "product_name",
            "editorial",
            "provider",
            "status",
            "status_display",
            "source",
            "source_display",
            "observed_on",
            "notes",
            "created_at",
            "updated_at",
        )

    def get_service(self, obj):
        if obj.service_id is None:
            return None

        return {
            "id": obj.service_id,
            "level": obj.service.level.name,
            "modular_code": obj.service.modular_code,
        }

    def get_area(self, obj):
        if obj.area_id is None:
            return None

        return {
            "id": obj.area_id,
            "name": obj.area.name,
        }

    def get_editorial(self, obj):
        if obj.editorial_id is None:
            return None

        return {
            "id": obj.editorial_id,
            "name": obj.editorial.name,
            "verification_status": obj.editorial.verification_status,
            "verification_status_display": (
                obj.editorial.get_verification_status_display()
            ),
            "is_catalog_editorial": (
                obj.editorial.catalog_provider_id is not None
            ),
        }

    def get_provider(self, obj):
        if obj.provider_id is None:
            return None

        return {
            "id": obj.provider_id,
            "name": obj.provider.name,
        }


class SchoolEditorialUsageWriteSerializer(serializers.ModelSerializer):
    service = serializers.PrimaryKeyRelatedField(
        queryset=SchoolEducationalService.objects.all(),
        required=False,
        allow_null=True,
    )
    area = serializers.PrimaryKeyRelatedField(
        queryset=Area.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    editorial = serializers.PrimaryKeyRelatedField(
        queryset=MarketEditorial.objects.filter(is_active=True),
    )

    class Meta:
        model = SchoolEditorialUsage
        fields = (
            "year",
            "service",
            "area",
            "product_name",
            "editorial",
            "status",
            "source",
            "observed_on",
            "notes",
        )

    def validate(self, attrs):
        school = self.context.get("school")

        service = attrs.get(
            "service",
            getattr(self.instance, "service", None),
        )

        if service is not None and service.school_id != school.id:
            raise serializers.ValidationError(
                {
                    "service": (
                        "El nivel educativo seleccionado "
                        "no pertenece a este colegio."
                    )
                }
            )

        year = attrs.get(
            "year",
            getattr(self.instance, "year", None),
        )

        area = attrs.get(
            "area",
            getattr(self.instance, "area", None),
        )

        editorial = attrs.get(
            "editorial",
            getattr(self.instance, "editorial", None),
        )

        if editorial is None:
            raise serializers.ValidationError(
                {
                    "editorial": "Selecciona una editorial."
                }
            )

        product_name = " ".join(
            (
                attrs.get(
                    "product_name",
                    getattr(self.instance, "product_name", ""),
                )
                or ""
            ).split()
        )

        attrs["product_name"] = product_name
        attrs["provider"] = editorial.catalog_provider

        queryset = SchoolEditorialUsage.objects.filter(
            school=school,
            year=year,
            service=service,
            area=area,
            editorial=editorial,
            product_name__iexact=product_name,
        )

        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "Esta información editorial ya está registrada."
            )

        return attrs

class SchoolCommercialProfileSerializer(serializers.ModelSerializer):
    campaign = CampaignSerializer(read_only=True)
    segment_display = serializers.CharField(
        source="get_segment_display",
        read_only=True,
    )
    priority_display = serializers.CharField(
        source="get_priority_display",
        read_only=True,
    )
    textbook_usage_display = serializers.CharField(
        source="get_textbook_usage_display",
        read_only=True,
    )

    class Meta:
        model = SchoolCommercialProfile
        fields = (
            "id",
            "campaign",
            "population_total",
            "segment",
            "segment_display",
            "textbook_usage",
            "textbook_usage_display",
            "priority",
            "priority_display",
            "priority_score",
            "score_reasons",
            "score_version",
            "scored_at",
            "updated_at",
        )


def _latest_population_for_service(service):
    current_records = [
        record
        for record in service.population_records.all()
        if record.is_current
    ]

    if not current_records:
        return None

    return max(
        current_records,
        key=lambda record: (record.year, record.created_at, record.id),
    )


def _current_population_total(school):
    total = 0

    for service in school.educational_services.all():
        if not service.is_active:
            continue

        record = _latest_population_for_service(service)

        if record is not None:
            total += record.student_count

    return total


class SchoolListSerializer(serializers.ModelSerializer):
    owner = UserSummarySerializer(read_only=True)
    team = CommercialTeamSummarySerializer(read_only=True)
    levels = LevelSummarySerializer(many=True, read_only=True)
    current_population_total = serializers.SerializerMethodField()
    segment = serializers.SerializerMethodField()

    class Meta:
        model = School
        fields = (
            "id",
            "institution_code",
            "name",
            "modular_code",
            "ruc",
            "phone",
            "whatsapp",
            "email",
            "department",
            "province",
            "district",
            "estimated_students",
            "current_population_total",
            "segment",
            "levels",
            "team",
            "owner",
            "is_active",
            "updated_at",
        )

    def get_current_population_total(self, obj):
        total = _current_population_total(obj)

        if total > 0:
            return total

        return obj.estimated_students

    def get_segment(self, obj):
        population = self.get_current_population_total(obj)

        if population is None:
            return "OUT"
        if population >= 500:
            return "A"
        if population >= 250:
            return "B"
        if population >= 101:
            return "C"

        return "OUT"


class SchoolDetailSerializer(SchoolListSerializer):
    contacts = SchoolContactSerializer(many=True, read_only=True)
    educational_services = SchoolEducationalServiceSerializer(
        many=True,
        read_only=True,
    )
    editorial_usages = SchoolEditorialUsageSerializer(
        many=True,
        read_only=True,
    )
    commercial_profile = serializers.SerializerMethodField()

    class Meta(SchoolListSerializer.Meta):
        fields = SchoolListSerializer.Meta.fields + (
            "address",
            "reference",
            "notes",
            "contacts",
            "educational_services",
            "editorial_usages",
            "commercial_profile",
            "created_at",
        )

    def get_commercial_profile(self, obj):
        profile = next(iter(obj.commercial_profiles.all()), None)

        if profile is None:
            return None

        return SchoolCommercialProfileSerializer(profile).data


class SchoolWriteSerializer(serializers.ModelSerializer):
    levels = serializers.PrimaryKeyRelatedField(queryset=Level.objects.filter(is_active=True), many=True, required=False)
    team = serializers.PrimaryKeyRelatedField(queryset=CommercialTeam.objects.filter(is_active=True), required=False, allow_null=True)
    owner = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False, allow_null=True)

    class Meta:
        model = School
        fields = (
            "institution_code", "name", "modular_code", "ruc", "phone", "whatsapp", "email", "address",
            "reference", "department", "province", "district", "estimated_students",
            "levels", "team", "owner", "notes", "is_active",
        )


class OpportunityListSerializer(serializers.ModelSerializer):
    school = serializers.SerializerMethodField()
    campaign = serializers.SerializerMethodField()
    stage = PipelineStageSerializer(read_only=True)
    team = CommercialTeamSummarySerializer(read_only=True)
    owner = UserSummarySerializer(read_only=True)
    is_closed = serializers.BooleanField(read_only=True)
    next_activity = serializers.SerializerMethodField()

    class Meta:
        model = Opportunity
        fields = (
            "id", "title", "school", "campaign", "stage", "team", "owner",
            "last_activity_at", "next_activity", "closed_at", "is_closed",
            "updated_at",
        )

    def get_school(self, obj):
        return {"id": obj.school_id, "name": obj.school.name}

    def get_campaign(self, obj):
        return {
            "id": obj.campaign_id,
            "code": obj.campaign.code,
            "name": obj.campaign.name,
            "year": obj.campaign.year,
        }

    def get_next_activity(self, obj):
        links = getattr(
            obj,
            "prefetched_next_activity_links",
            None,
        )

        if links is None:
            links = (
                obj.work_item_links
                .select_related("task", "event", "reminder")
                .all()
            )

        now = timezone.now()
        candidates = []

        for link in links:
            if link.task_id:
                task = link.task

                if task.status in {"completed", "cancelled"}:
                    continue

                future_dates = [
                    value
                    for value in (
                        task.start_at,
                        task.due_at,
                        task.reminder_at,
                    )
                    if value is not None and value >= now
                ]

                if not future_dates:
                    continue

                candidates.append(
                    {
                        "type": "task",
                        "type_display": "Tarea",
                        "id": task.id,
                        "title": task.title,
                        "scheduled_at": min(future_dates),
                        "status": task.status,
                    }
                )
                continue

            if link.event_id:
                event = link.event

                if event.start_at < now:
                    continue

                candidates.append(
                    {
                        "type": "event",
                        "type_display": event.get_event_type_display(),
                        "id": event.id,
                        "title": event.title,
                        "scheduled_at": event.start_at,
                        "status": None,
                    }
                )
                continue

            reminder = link.reminder

            if reminder.status in {"completed", "dismissed"}:
                continue

            if reminder.remind_at < now:
                continue

            candidates.append(
                {
                    "type": "reminder",
                    "type_display": "Recordatorio",
                    "id": reminder.id,
                    "title": reminder.title,
                    "scheduled_at": reminder.remind_at,
                    "status": reminder.status,
                }
            )

        if not candidates:
            return None

        return min(
            candidates,
            key=lambda candidate: candidate["scheduled_at"],
        )


class OpportunityDetailSerializer(OpportunityListSerializer):
    pipeline = PipelineSerializer(read_only=True)
    primary_contact = SchoolContactSerializer(read_only=True)
    created_by = UserSummarySerializer(read_only=True)
    closed_by = UserSummarySerializer(read_only=True)

    class Meta(OpportunityListSerializer.Meta):
        fields = OpportunityListSerializer.Meta.fields + (
            "pipeline", "primary_contact", "notes", "closure_note", "created_by",
            "closed_by", "created_at",
        )


class OpportunityCreateSerializer(serializers.Serializer):
    title = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default="",
    )
    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.filter(is_active=True),
    )
    campaign = serializers.PrimaryKeyRelatedField(
        queryset=Campaign.objects.exclude(
            status=Campaign.Status.CLOSED,
        ),
        required=False,
    )
    pipeline = serializers.PrimaryKeyRelatedField(
        queryset=Pipeline.objects.filter(is_active=True),
        required=False,
    )
    primary_contact = serializers.PrimaryKeyRelatedField(
        queryset=SchoolContact.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    team = serializers.PrimaryKeyRelatedField(
        queryset=CommercialTeam.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    owner = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class OpportunityUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    primary_contact = serializers.PrimaryKeyRelatedField(queryset=SchoolContact.objects.filter(is_active=True), required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class OpportunityStageChangeSerializer(serializers.Serializer):
    stage = serializers.PrimaryKeyRelatedField(queryset=PipelineStage.objects.filter(is_active=True))
    note = serializers.CharField(required=False, allow_blank=True, default="")


class OpportunityReopenSerializer(serializers.Serializer):
    stage = serializers.PrimaryKeyRelatedField(queryset=PipelineStage.objects.filter(is_active=True, category=PipelineStage.Category.OPEN))
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)


class CommercialProjectionGradeSerializer(serializers.ModelSerializer):
    service = serializers.SerializerMethodField()
    grade = GradeSummarySerializer(read_only=True)

    class Meta:
        model = CommercialProjectionGrade
        fields = (
            "id",
            "service",
            "grade",
            "level_name_snapshot",
            "grade_name_snapshot",
            "section_count",
            "student_count",
        )

    def get_service(self, obj):
        return {
            "id": obj.service_id,
            "level": {
                "id": obj.service.level_id,
                "name": obj.service.level.name,
            },
        }


class CommercialProjectionItemSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()
    grade_line_id = serializers.IntegerField(read_only=True)
    subtotal = serializers.SerializerMethodField()
    commercial_line = serializers.SerializerMethodField()

    class Meta:
        model = CommercialProjectionItem
        fields = (
            "id",
            "grade_line_id",
            "product",
            "product_name_snapshot",
            "provider_name_snapshot",
            "level_name_snapshot",
            "grade_name_snapshot",
            "area_name_snapshot",
            "commercial_line",
            "quantity",
            "unit_price",
            "subtotal",
            "price_year_snapshot",
            "price_campaign_snapshot",
        )

    def get_product(self, obj):
        product_type = getattr(obj.product, "product_type", None)

        return {
            "id": obj.product_id,
            "name": obj.product.name,
            "code": obj.product.code or obj.product.sku or "",
            "provider": {
                "id": obj.product.provider_id,
                "name": obj.product.provider.name,
            },
            "product_type": (
                {
                    "id": product_type.id,
                    "name": product_type.name,
                }
                if product_type
                else None
            ),
        }

    def get_commercial_line(self, obj):
        return obj.product.commercial_line

    def get_subtotal(self, obj):
        return f"{obj.subtotal:.2f}"


class CommercialProjectionSerializer(serializers.ModelSerializer):
    commercial_line_display = serializers.CharField(
        source="get_commercial_line_display",
        read_only=True,
    )
    grades = CommercialProjectionGradeSerializer(
        many=True,
        read_only=True,
    )
    items = CommercialProjectionItemSerializer(
        many=True,
        read_only=True,
    )
    created_by = UserSummarySerializer(read_only=True)
    total_students = serializers.SerializerMethodField()
    total_amount = serializers.SerializerMethodField()
    editorial_totals = serializers.SerializerMethodField()

    class Meta:
        model = CommercialProjection
        fields = (
            "id",
            "version",
            "is_current",
            "school_name_snapshot",
            "campaign_name_snapshot",
            "campaign_year_snapshot",
            "commercial_line",
            "commercial_line_display",
            "notes",
            "total_students",
            "total_amount",
            "editorial_totals",
            "grades",
            "items",
            "created_by",
            "created_at",
            "updated_at",
        )

    def get_total_students(self, obj):
        return sum(
            grade.student_count
            for grade in obj.grades.all()
        )

    def get_total_amount(self, obj):
        total = sum(
            (item.subtotal for item in obj.items.all()),
            0,
        )
        return f"{total:.2f}"

    def get_editorial_totals(self, obj):
        totals = {}

        for item in obj.items.all():
            provider = item.provider_name_snapshot
            totals[provider] = totals.get(provider, 0) + item.subtotal

        return [
            {
                "editorial": provider,
                "amount": f"{amount:.2f}",
            }
            for provider, amount in sorted(totals.items())
        ]


class CommercialProjectionGradeInputSerializer(serializers.Serializer):
    service = serializers.PrimaryKeyRelatedField(
        queryset=SchoolEducationalService.objects.filter(is_active=True),
    )
    grade = serializers.PrimaryKeyRelatedField(
        queryset=Grade.objects.filter(is_active=True),
    )
    section_count = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    student_count = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )


class CommercialProjectionItemInputSerializer(serializers.Serializer):
    service = serializers.PrimaryKeyRelatedField(
        queryset=SchoolEducationalService.objects.filter(is_active=True),
    )
    grade = serializers.PrimaryKeyRelatedField(
        queryset=Grade.objects.filter(is_active=True),
    )
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(is_active=True),
    )
    quantity = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )


class CommercialProjectionCreateSerializer(serializers.Serializer):
    commercial_line = serializers.ChoiceField(
        choices=(
            CommercialProjection.CommercialLine.SCHOOL_TEXT,
            CommercialProjection.CommercialLine.READING_PLAN,
        ),
        required=False,
        default=CommercialProjection.CommercialLine.SCHOOL_TEXT,
    )
    grades = CommercialProjectionGradeInputSerializer(
        many=True,
        allow_empty=False,
    )
    items = CommercialProjectionItemInputSerializer(
        many=True,
        required=False,
        default=list,
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        grades = attrs["grades"]
        items = attrs.get("items", [])

        grade_keys = [
            (grade["service"].id, grade["grade"].id)
            for grade in grades
        ]

        if len(grade_keys) != len(set(grade_keys)):
            raise serializers.ValidationError(
                {
                    "grades": (
                        "No puedes registrar dos veces "
                        "el mismo nivel y grado."
                    )
                }
            )

        item_keys = [
            (
                item["service"].id,
                item["grade"].id,
                item["product"].id,
            )
            for item in items
        ]

        if len(item_keys) != len(set(item_keys)):
            raise serializers.ValidationError(
                {
                    "items": (
                        "No puedes registrar dos veces el mismo "
                        "producto en el mismo nivel y grado."
                    )
                }
            )

        unknown_grade = next(
            (
                item
                for item in items
                if (item["service"].id, item["grade"].id)
                not in set(grade_keys)
            ),
            None,
        )

        if unknown_grade is not None:
            raise serializers.ValidationError(
                {
                    "items": (
                        "Cada producto debe pertenecer a un nivel "
                        "y grado incluidos en la proyección."
                    )
                }
            )

        return attrs


class CommercialQuotationItemSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()
    school_discount_amount = serializers.SerializerMethodField()
    margin_before_commission_unit = serializers.SerializerMethodField()
    green_margin_threshold_unit = serializers.SerializerMethodField()
    green_margin_surplus_unit = serializers.SerializerMethodField()
    green_margin_surplus_total = serializers.SerializerMethodField()
    additional_discount_available_points = serializers.SerializerMethodField()
    discount_recovery_required_points = serializers.SerializerMethodField()
    commercial_line_display = serializers.CharField(
        source="get_commercial_line_display",
        read_only=True,
    )
    profitability_band_display = serializers.CharField(
        source="get_profitability_band_display",
        read_only=True,
    )

    class Meta:
        model = CommercialQuotationItem
        fields = (
            "id",
            "product",
            "product_name_snapshot",
            "provider_name_snapshot",
            "level_name_snapshot",
            "grade_name_snapshot",
            "area_name_snapshot",
            "product_code_snapshot",
            "product_type_name_snapshot",
            "commercial_line",
            "commercial_line_display",
            "reading_month",
            "quantity",
            "pvp",
            "supplier_cost",
            "supplier_discount_percent",
            "school_price",
            "school_discount_percent",
            "school_discount_amount",
            "margin_before_commission_unit",
            "parent_price",
            "school_commission",
            "commission_mode",
            "commission_input_amount",
            "commercial_margin_unit",
            "commercial_margin_total",
            "commercial_margin_percent",
            "green_margin_threshold_unit",
            "green_margin_surplus_unit",
            "green_margin_surplus_total",
            "additional_discount_available_points",
            "discount_recovery_required_points",
            "profitability_band",
            "profitability_band_display",
            "max_green_discount_percent",
            "green_discount_headroom_points",
            "price_year_snapshot",
            "price_campaign_snapshot",
            "uses_reference_price",
        )

    def get_product(self, obj):
        return {
            "id": obj.product_id,
            "name": obj.product.name,
        }

    def get_school_discount_amount(self, obj):
        return (obj.pvp - obj.school_price).quantize(
            Decimal("0.01")
        )

    def get_margin_before_commission_unit(self, obj):
        if obj.supplier_discount_percent is None:
            return None

        return (obj.school_price - obj.supplier_cost).quantize(
            Decimal("0.01")
        )

    def get_green_margin_threshold_unit(self, obj):
        return green_margin_threshold(obj.commercial_line)

    def get_green_margin_surplus_unit(self, obj):
        if obj.supplier_discount_percent is None:
            return None

        threshold = green_margin_threshold(obj.commercial_line)

        if threshold is None:
            return None

        return (obj.commercial_margin_unit - threshold).quantize(
            Decimal("0.01")
        )

    def get_green_margin_surplus_total(self, obj):
        surplus = self.get_green_margin_surplus_unit(obj)

        if surplus is None:
            return None

        return (surplus * Decimal(obj.quantity)).quantize(
            Decimal("0.01")
        )

    def get_additional_discount_available_points(self, obj):
        headroom = obj.green_discount_headroom_points

        if headroom is None:
            return None

        return max(headroom, Decimal("0.00"))

    def get_discount_recovery_required_points(self, obj):
        headroom = obj.green_discount_headroom_points

        if headroom is None:
            return None

        return max(-headroom, Decimal("0.00"))

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if _request_can_view_quotation_financials(self):
            if instance.supplier_discount_percent is None:
                for field_name in (
                    "supplier_cost",
                    "margin_before_commission_unit",
                    "commercial_margin_unit",
                    "commercial_margin_total",
                    "commercial_margin_percent",
                    "green_margin_surplus_unit",
                    "green_margin_surplus_total",
                    "additional_discount_available_points",
                    "discount_recovery_required_points",
                    "max_green_discount_percent",
                    "green_discount_headroom_points",
                ):
                    data[field_name] = None

                data["profitability_band"] = "unclassified"
                data["profitability_band_display"] = "Sin clasificar"

            return data

        for field_name in (
            "supplier_cost",
            "supplier_discount_percent",
            "school_discount_amount",
            "margin_before_commission_unit",
            "school_commission",
            "commission_mode",
            "commission_input_amount",
            "commercial_margin_unit",
            "commercial_margin_total",
            "commercial_margin_percent",
            "green_margin_threshold_unit",
            "green_margin_surplus_unit",
            "green_margin_surplus_total",
            "additional_discount_available_points",
            "discount_recovery_required_points",
            "profitability_band",
            "profitability_band_display",
            "max_green_discount_percent",
            "green_discount_headroom_points",
        ):
            data.pop(field_name, None)

        return data


class CommercialQuotationSerializer(serializers.ModelSerializer):
    commercial_line_display = serializers.CharField(
        source="get_commercial_line_display",
        read_only=True,
    )
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    discount_approval_status_display = serializers.CharField(
        source="get_discount_approval_status_display",
        read_only=True,
    )
    source_projection = serializers.SerializerMethodField()
    commercial_analysis = serializers.SerializerMethodField()
    items = CommercialQuotationItemSerializer(
        many=True,
        read_only=True,
    )
    created_by = UserSummarySerializer(read_only=True)
    sent_by = UserSummarySerializer(read_only=True)
    accepted_by = UserSummarySerializer(read_only=True)
    reopened_by = UserSummarySerializer(read_only=True)
    discount_approved_by = UserSummarySerializer(read_only=True)

    class Meta:
        model = CommercialQuotation
        fields = (
            "id",
            "version",
            "internal_code",
            "status",
            "status_display",
            "source_projection",
            "commercial_analysis",
            "school_name_snapshot",
            "campaign_name_snapshot",
            "primary_contact_name_snapshot",
            "primary_contact_position_snapshot",
            "primary_contact_phone_snapshot",
            "primary_contact_email_snapshot",
            "advisor_name_snapshot",
            "advisor_phone_snapshot",
            "advisor_whatsapp_snapshot",
            "commercial_line",
            "commercial_line_display",
            "notes",
            "requires_discount_approval",
            "discount_approval_status",
            "discount_approval_status_display",
            "discount_approved_at",
            "discount_approved_by",
            "discount_approval_note",
            "sent_at",
            "sent_by",
            "accepted_at",
            "accepted_by",
            "reopened_at",
            "reopened_by",
            "reopen_reason",
            "created_by",
            "items",
            "created_at",
            "updated_at",
        )

    def get_source_projection(self, obj):
        if obj.source_projection_id is None:
            return None

        return {
            "id": obj.source_projection_id,
            "version": obj.source_projection.version,
            "campaign_year": obj.source_projection.campaign_year_snapshot,
            "commercial_line": obj.source_projection.commercial_line,
            "commercial_line_display": (
                obj.source_projection.get_commercial_line_display()
            ),
        }

    def get_commercial_analysis(self, obj):
        if not _request_can_view_quotation_financials(self):
            return None

        sales_total = Decimal("0.00")
        cost_total = Decimal("0.00")
        commission_total = Decimal("0.00")
        margin_total = Decimal("0.00")
        green_margin_surplus_total = Decimal("0.00")
        pending_supplier_conditions = 0
        band_counts = {
            "green": 0,
            "amber": 0,
            "red": 0,
            "loss": 0,
            "unclassified": 0,
        }
        margin_by_editorial = {}

        for item in obj.items.all():
            quantity = Decimal(item.quantity)
            item_sales = item.school_price * quantity
            item_commission = item.school_commission * quantity

            sales_total += item_sales
            commission_total += item_commission

            if item.supplier_discount_percent is None:
                pending_supplier_conditions += 1
                band_counts["unclassified"] += 1
                continue

            item_cost = item.supplier_cost * quantity
            cost_total += item_cost
            margin_total += item.commercial_margin_total

            threshold = green_margin_threshold(item.commercial_line)
            if threshold is not None:
                green_margin_surplus_total += (
                    (item.commercial_margin_unit - threshold)
                    * quantity
                )

            band_counts[item.profitability_band] = (
                band_counts.get(item.profitability_band, 0) + 1
            )

            editorial_name = (
                item.provider_name_snapshot or "Sin editorial"
            )
            margin_by_editorial[editorial_name] = (
                margin_by_editorial.get(
                    editorial_name,
                    Decimal("0.00"),
                )
                + item.commercial_margin_total
            )

        has_pending_supplier_conditions = (
            pending_supplier_conditions > 0
        )

        margin_percent = None
        if (
            not has_pending_supplier_conditions
            and sales_total > Decimal("0.00")
        ):
            margin_percent = (
                margin_total / sales_total * Decimal("100.00")
            ).quantize(Decimal("0.01"))

        return {
            "commercial_line": obj.commercial_line,
            "commercial_line_display": obj.get_commercial_line_display(),
            "sales_total": sales_total,
            "cost_total": (
                None if has_pending_supplier_conditions else cost_total
            ),
            "commission_total": commission_total,
            "margin_total": (
                None if has_pending_supplier_conditions else margin_total
            ),
            "margin_percent": margin_percent,
            "has_pending_supplier_conditions": (
                has_pending_supplier_conditions
            ),
            "pending_supplier_conditions": (
                pending_supplier_conditions
            ),
            "green_margin_threshold_unit": green_margin_threshold(
                obj.commercial_line
            ),
            "green_margin_surplus_total": (
                None
                if has_pending_supplier_conditions
                else green_margin_surplus_total.quantize(
                    Decimal("0.01")
                )
            ),

            "products_by_band": band_counts,
            "margin_by_editorial": (
                []
                if has_pending_supplier_conditions
                else [
                {
                    "editorial": editorial,
                    "margin_total": margin,
                }
                    for editorial, margin in sorted(
                        margin_by_editorial.items()
                    )
                ]
            ),
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if not _request_can_view_quotation_financials(self):
            data.pop("commercial_analysis", None)

        return data


class CommercialQuotationItemCreateSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(is_active=True),
    )
    quantity = serializers.IntegerField(min_value=1)
    pvp = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
    )
    supplier_cost = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
    )
    school_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
    )
    parent_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
    )
    school_commission = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
        required=False,
        default=0,
    )


class CommercialQuotationCreateSerializer(serializers.Serializer):
    items = CommercialQuotationItemCreateSerializer(
        many=True,
        allow_empty=False,
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class CommercialQuotationProjectionItemAdjustmentSerializer(
    serializers.Serializer
):
    projection_item = serializers.PrimaryKeyRelatedField(
        queryset=CommercialProjectionItem.objects.all(),
    )
    quantity = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    school_discount_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=100,
        required=False,
    )
    parent_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
        required=False,
    )
    supplier_discount_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=100,
        required=False,
        allow_null=True,
    )
    reading_month = serializers.IntegerField(
        min_value=1,
        max_value=12,
        required=False,
        allow_null=True,
    )
    commission_mode = serializers.ChoiceField(
        choices=CommercialQuotationItem.CommissionMode.choices,
        required=False,
    )
    commission_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
        required=False,
    )
    school_commission = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0,
        required=False,
        write_only=True,
    )

    def validate(self, attrs):
        if (
            "commission_amount" in attrs
            and "school_commission" in attrs
        ):
            raise serializers.ValidationError(
                {
                    "commission_amount": (
                        "Usa commission_amount o school_commission, "
                        "pero no ambos."
                    )
                }
            )

        return attrs


class CommercialQuotationFromProjectionSerializer(serializers.Serializer):
    items = CommercialQuotationProjectionItemAdjustmentSerializer(
        many=True,
        required=False,
        allow_empty=True,
        default=list,
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class CommercialQuotationDiscountApprovalSerializer(
    serializers.Serializer
):
    note = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class CommercialQuotationReopenSerializer(serializers.Serializer):
    reason = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )


class AdoptionItemSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()
    product_code_snapshot = serializers.CharField(
        source="quotation_item.product_code_snapshot",
        read_only=True,
    )

    class Meta:
        model = AdoptionItem
        fields = (
            "id",
            "product",
            "product_name_snapshot",
            "product_code_snapshot",
            "provider_name_snapshot",
            "level_name_snapshot",
            "grade_name_snapshot",
            "area_name_snapshot",
            "quantity",
            "pvp",
            "supplier_cost",
            "supplier_discount_percent",
            "school_price",
            "parent_price",
            "school_commission",
            "reading_month",
        )

    def get_product(self, obj):
        return {
            "id": obj.product_id,
            "name": obj.product.name,
        }


class AdoptionSerializer(serializers.ModelSerializer):
    advisor = UserSummarySerializer(read_only=True)
    confirmed_by = UserSummarySerializer(read_only=True)
    authorized_contact = SchoolContactSerializer(read_only=True)
    items = AdoptionItemSerializer(many=True, read_only=True)

    class Meta:
        model = Adoption
        fields = (
            "id",
            "version",
            "is_current",
            "school_name_snapshot",
            "campaign_name_snapshot",
            "advisor",
            "advisor_name_snapshot",
            "authorized_contact",
            "authorized_contact_name_snapshot",
            "signed_at",
            "confirmed_at",
            "confirmed_by",
            "notes",
            "items",
            "created_at",
            "updated_at",
        )


class AdoptionConfirmSerializer(serializers.Serializer):
    quotation = serializers.PrimaryKeyRelatedField(
        queryset=CommercialQuotation.objects.all(),
    )
    authorized_contact = serializers.PrimaryKeyRelatedField(
        queryset=SchoolContact.objects.filter(is_active=True),
    )
    signed_at = serializers.DateTimeField()
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class OpportunityStageHistorySerializer(serializers.ModelSerializer):
    from_stage = PipelineStageSerializer(read_only=True)
    to_stage = PipelineStageSerializer(read_only=True)
    changed_by = UserSummarySerializer(read_only=True)
    transition_type_display = serializers.CharField(source="get_transition_type_display", read_only=True)

    class Meta:
        model = OpportunityStageHistory
        fields = (
            "id", "from_stage", "to_stage", "changed_by", "transition_type",
            "transition_type_display", "note", "created_at",
        )


class CommercialActivitySerializer(serializers.ModelSerializer):
    contact = SchoolContactSerializer(read_only=True)
    performed_by = UserSummarySerializer(read_only=True)
    activity_type_display = serializers.CharField(source="get_activity_type_display", read_only=True)

    class Meta:
        model = CommercialActivity
        fields = (
            "id", "school_id", "opportunity_id",
            "activity_type", "activity_type_display", "summary", "result",
            "contact", "performed_by", "occurred_at", "is_important", "created_at",
        )


class CommercialActivityCreateSerializer(serializers.Serializer):
    activity_type = serializers.ChoiceField(choices=CommercialActivity.ActivityType.choices)
    summary = serializers.CharField(max_length=200)
    result = serializers.CharField()
    contact = serializers.PrimaryKeyRelatedField(queryset=SchoolContact.objects.filter(is_active=True), required=False, allow_null=True)
    occurred_at = serializers.DateTimeField(required=False)
    is_important = serializers.BooleanField(required=False, default=False)


class OpportunityTaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)
    assigned_to = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    priority = serializers.ChoiceField(choices=Task.PRIORITY_CHOICES, required=False, default="medium")
    group = serializers.PrimaryKeyRelatedField(queryset=WorkspaceGroup.objects.filter(is_active=True), required=False, allow_null=True)
    start_at = serializers.DateTimeField(required=False, allow_null=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    reminder_at = serializers.DateTimeField(required=False, allow_null=True)
    is_important = serializers.BooleanField(required=False, default=False)
    is_private = serializers.BooleanField(required=False, default=False)


class OpportunityEventCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)
    start_at = serializers.DateTimeField()
    assigned_to = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False, allow_null=True)
    participants = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), many=True, required=False)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    event_type = serializers.ChoiceField(choices=CalendarEvent.EVENT_TYPE_CHOICES, required=False, default="visit")
    group = serializers.PrimaryKeyRelatedField(queryset=WorkspaceGroup.objects.filter(is_active=True), required=False, allow_null=True)
    end_at = serializers.DateTimeField(required=False, allow_null=True)
    is_all_day = serializers.BooleanField(required=False, default=False)
    location = serializers.CharField(required=False, allow_blank=True, default="", max_length=180)


class OpportunityReminderCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)
    remind_at = serializers.DateTimeField()
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False, allow_null=True)
    message = serializers.CharField(required=False, allow_blank=True, default="")
    group = serializers.PrimaryKeyRelatedField(queryset=WorkspaceGroup.objects.filter(is_active=True), required=False, allow_null=True)
    task = serializers.PrimaryKeyRelatedField(queryset=Task.objects.all(), required=False, allow_null=True)
    event = serializers.PrimaryKeyRelatedField(queryset=CalendarEvent.objects.all(), required=False, allow_null=True)


class SchoolCommercialActivityCreateSerializer(
    CommercialActivityCreateSerializer
):
    opportunity = serializers.PrimaryKeyRelatedField(
        queryset=Opportunity.objects.all(),
        required=False,
        allow_null=True,
    )


class SchoolTaskCreateSerializer(OpportunityTaskCreateSerializer):
    contact = serializers.PrimaryKeyRelatedField(
        queryset=SchoolContact.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    opportunity = serializers.PrimaryKeyRelatedField(
        queryset=Opportunity.objects.all(),
        required=False,
        allow_null=True,
    )
    origin_activity = serializers.PrimaryKeyRelatedField(
        queryset=CommercialActivity.objects.all(),
        required=False,
        allow_null=True,
    )


class SchoolEventCreateSerializer(OpportunityEventCreateSerializer):
    contact = serializers.PrimaryKeyRelatedField(
        queryset=SchoolContact.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    opportunity = serializers.PrimaryKeyRelatedField(
        queryset=Opportunity.objects.all(),
        required=False,
        allow_null=True,
    )
    origin_activity = serializers.PrimaryKeyRelatedField(
        queryset=CommercialActivity.objects.all(),
        required=False,
        allow_null=True,
    )


class SchoolReminderCreateSerializer(OpportunityReminderCreateSerializer):
    contact = serializers.PrimaryKeyRelatedField(
        queryset=SchoolContact.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    opportunity = serializers.PrimaryKeyRelatedField(
        queryset=Opportunity.objects.all(),
        required=False,
        allow_null=True,
    )
    origin_activity = serializers.PrimaryKeyRelatedField(
        queryset=CommercialActivity.objects.all(),
        required=False,
        allow_null=True,
    )


class WorkItemLinkSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="work_item_type", read_only=True)
    item = serializers.SerializerMethodField()

    class Meta:
        model = CRMWorkItemLink
        fields = (
            "id",
            "school_id",
            "contact_id",
            "opportunity_id",
            "type",
            "item",
            "origin_activity_id",
            "created_at",
        )

    def get_item(self, obj):
        if obj.task_id:
            return {
                "id": obj.task_id, "title": obj.task.title, "status": obj.task.status,
                "priority": obj.task.priority, "assigned_to_id": obj.task.assigned_to_id,
                "due_at": obj.task.due_at, "reminder_at": obj.task.reminder_at,
            }
        if obj.event_id:
            return {
                "id": obj.event_id, "title": obj.event.title, "event_type": obj.event.event_type,
                "assigned_to_id": obj.event.assigned_to_id, "start_at": obj.event.start_at,
                "end_at": obj.event.end_at, "location": obj.event.location,
            }
        return {
            "id": obj.reminder_id, "title": obj.reminder.title, "status": obj.reminder.status,
            "user_id": obj.reminder.user_id, "remind_at": obj.reminder.remind_at,
        }