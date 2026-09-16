from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    severity_display = serializers.CharField(
        source="get_severity_display",
        read_only=True,
    )

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "event_type",
            "module",
            "severity",
            "severity_display",
            "link",
            "is_read",
            "read_at",
            "is_resolved",
            "resolved_at",
            "actor",
            "actor_name",
            "source_app",
            "source_model",
            "source_id",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields

    def get_actor_name(self, obj):
        if not obj.actor:
            return ""

        full_name = obj.actor.get_full_name().strip()

        return full_name or obj.actor.username
