from django.contrib.auth import get_user_model
from rest_framework import serializers

from catalog.models import Level
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
    SchoolContact,
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
    class Meta:
        model = SchoolContact
        fields = (
            "id", "full_name", "position", "phone", "whatsapp", "email",
            "is_primary", "is_active", "notes", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class SchoolListSerializer(serializers.ModelSerializer):
    owner = UserSummarySerializer(read_only=True)
    team = CommercialTeamSummarySerializer(read_only=True)
    levels = LevelSummarySerializer(many=True, read_only=True)

    class Meta:
        model = School
        fields = (
            "id", "name", "modular_code", "ruc", "phone", "whatsapp", "email",
            "department", "province", "district", "estimated_students", "levels",
            "team", "owner", "is_active", "updated_at",
        )


class SchoolDetailSerializer(SchoolListSerializer):
    contacts = SchoolContactSerializer(many=True, read_only=True)

    class Meta(SchoolListSerializer.Meta):
        fields = SchoolListSerializer.Meta.fields + (
            "address", "reference", "notes", "contacts", "created_at",
        )


class SchoolWriteSerializer(serializers.ModelSerializer):
    levels = serializers.PrimaryKeyRelatedField(queryset=Level.objects.filter(is_active=True), many=True, required=False)
    team = serializers.PrimaryKeyRelatedField(queryset=CommercialTeam.objects.filter(is_active=True), required=False, allow_null=True)
    owner = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False, allow_null=True)

    class Meta:
        model = School
        fields = (
            "name", "modular_code", "ruc", "phone", "whatsapp", "email", "address",
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
            "id", "activity_type", "activity_type_display", "summary", "result",
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


class WorkItemLinkSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="work_item_type", read_only=True)
    item = serializers.SerializerMethodField()

    class Meta:
        model = CRMWorkItemLink
        fields = ("id", "type", "item", "origin_activity_id", "created_at")

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
