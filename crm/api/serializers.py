from django.contrib.auth import get_user_model
from rest_framework import serializers

from django.utils.text import slugify

from catalog.models import Area, Level
from crm.models import (
    Campaign,
    CommercialActivity,
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
    MarketEditorial,
)
from workspaces.models import CalendarEvent, Task, WorkspaceGroup


User = get_user_model()


class UserSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "full_name")

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class LevelSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Level
        fields = ("id", "name")


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


class SchoolPopulationRecordSerializer(serializers.ModelSerializer):
    source_display = serializers.CharField(
        source="get_source_display",
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
            "created_at",
            "updated_at",
        )

class SchoolPopulationRecordWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolPopulationRecord
        fields = (
            "year",
            "student_count",
            "source",
            "source_detail",
        )


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

    class Meta:
        model = Opportunity
        fields = (
            "id", "title", "school", "campaign", "stage", "team", "owner",
            "last_activity_at", "closed_at", "is_closed", "updated_at",
        )

    def get_school(self, obj):
        return {"id": obj.school_id, "name": obj.school.name}

    def get_campaign(self, obj):
        return {"id": obj.campaign_id, "code": obj.campaign.code, "name": obj.campaign.name, "year": obj.campaign.year}


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
    title = serializers.CharField(max_length=200)
    school = serializers.PrimaryKeyRelatedField(queryset=School.objects.filter(is_active=True))
    campaign = serializers.PrimaryKeyRelatedField(queryset=Campaign.objects.exclude(status=Campaign.Status.CLOSED))
    pipeline = serializers.PrimaryKeyRelatedField(queryset=Pipeline.objects.filter(is_active=True))
    primary_contact = serializers.PrimaryKeyRelatedField(queryset=SchoolContact.objects.filter(is_active=True), required=False, allow_null=True)
    team = serializers.PrimaryKeyRelatedField(queryset=CommercialTeam.objects.filter(is_active=True), required=False, allow_null=True)
    owner = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


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
