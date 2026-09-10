from django.contrib.auth.models import User

from rest_framework import serializers

from .models import (
    ContactRequest,
    ContactRequestComment,
    ContactRequestStatusHistory,
)


class ContactRequestCreateSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True
    )
    provider_name = serializers.CharField(
        source="provider.name",
        read_only=True
    )

    class Meta:
        model = ContactRequest
        fields = [
            "id",
            "full_name",
            "phone",
            "email",
            "product",
            "product_name",
            "provider",
            "provider_name",
            "message",
            "source",
            "status",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "product_name",
            "provider_name",
            "status",
            "created_at",
        ]

    def validate(self, attrs):
        product = attrs.get("product")
        provider = attrs.get("provider")

        if product and provider and product.provider_id != provider.id:
            raise serializers.ValidationError({
                "provider": "La editorial enviada no corresponde al producto seleccionado."
            })

        return attrs

    def create(self, validated_data):
        product = validated_data.get("product")

        if product and not validated_data.get("provider"):
            validated_data["provider"] = product.provider

        return super().create(validated_data)


class ContactRequestCommentSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    action_type_display = serializers.CharField(
        source="get_action_type_display",
        read_only=True
    )

    class Meta:
        model = ContactRequestComment
        fields = [
            "id",
            "contact_request",
            "user",
            "user_name",
            "action_type",
            "action_type_display",
            "comment",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "contact_request",
            "user",
            "user_name",
            "action_type_display",
            "created_at",
            "updated_at",
        ]

    def get_user_name(self, obj):
        if not obj.user:
            return ""

        full_name = obj.user.get_full_name().strip()

        if full_name:
            return full_name

        return obj.user.username


class ContactRequestStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.SerializerMethodField()
    old_status_display = serializers.SerializerMethodField()
    new_status_display = serializers.SerializerMethodField()

    class Meta:
        model = ContactRequestStatusHistory
        fields = [
            "id",
            "contact_request",
            "changed_by",
            "changed_by_name",
            "old_status",
            "old_status_display",
            "new_status",
            "new_status_display",
            "note",
            "created_at",
        ]
        read_only_fields = fields

    def get_changed_by_name(self, obj):
        if not obj.changed_by:
            return ""

        full_name = obj.changed_by.get_full_name().strip()

        if full_name:
            return full_name

        return obj.changed_by.username

    def get_old_status_display(self, obj):
        return dict(ContactRequest.STATUS_CHOICES).get(
            obj.old_status,
            obj.old_status
        )

    def get_new_status_display(self, obj):
        return dict(ContactRequest.STATUS_CHOICES).get(
            obj.new_status,
            obj.new_status
        )


class ContactRequestAdminSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True
    )
    provider_name = serializers.CharField(
        source="provider.name",
        read_only=True
    )
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        allow_null=True
    )
    assigned_to_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True
    )
    priority_display = serializers.CharField(
        source="get_priority_display",
        read_only=True
    )
    source_display = serializers.CharField(
        source="get_source_display",
        read_only=True
    )
    comments = ContactRequestCommentSerializer(
        many=True,
        read_only=True
    )
    status_history = ContactRequestStatusHistorySerializer(
        many=True,
        read_only=True
    )

    class Meta:
        model = ContactRequest
        fields = [
            "id",
            "full_name",
            "phone",
            "email",
            "product",
            "product_name",
            "provider",
            "provider_name",
            "message",
            "source",
            "source_display",
            "status",
            "status_display",
            "priority",
            "priority_display",
            "assigned_to",
            "assigned_to_name",
            "last_attention_at",
            "next_action_at",
            "closed_at",
            "comments",
            "status_history",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "product_name",
            "provider_name",
            "source_display",
            "status_display",
            "priority_display",
            "assigned_to_name",
            "last_attention_at",
            "closed_at",
            "comments",
            "status_history",
            "created_at",
            "updated_at",
        ]

    def get_assigned_to_name(self, obj):
        if not obj.assigned_to:
            return ""

        full_name = obj.assigned_to.get_full_name().strip()

        if full_name:
            return full_name

        return obj.assigned_to.username


class ContactRequestStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=ContactRequest.STATUS_CHOICES
    )
    note = serializers.CharField(
        required=False,
        allow_blank=True
    )


class ContactRequestAssignSerializer(serializers.Serializer):
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        allow_null=True
    )


class ContactRequestAddCommentSerializer(serializers.Serializer):
    action_type = serializers.ChoiceField(
        choices=ContactRequestComment.ACTION_TYPE_CHOICES,
        default="general"
    )
    comment = serializers.CharField()