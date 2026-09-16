from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = (
            Notification.objects
            .select_related("actor", "recipient")
            .filter(recipient=self.request.user)
            .order_by("-created_at")
        )

        is_read = self.request.query_params.get("is_read")
        module = self.request.query_params.get("module")
        severity = self.request.query_params.get("severity")
        is_resolved = self.request.query_params.get("is_resolved")

        if is_read == "true":
            queryset = queryset.filter(is_read=True)

        if is_read == "false":
            queryset = queryset.filter(is_read=False)

        if module:
            queryset = queryset.filter(module=module)

        if severity:
            queryset = queryset.filter(severity=severity)

        if is_resolved == "true":
            queryset = queryset.filter(is_resolved=True)

        if is_resolved == "false":
            queryset = queryset.filter(is_resolved=False)

        return queryset

    @action(
        detail=False,
        methods=["get"],
        url_path="unread-count",
    )
    def unread_count(self, request):
        count = self.get_queryset().filter(
            is_read=False,
            is_resolved=False,
        ).count()

        return Response({
            "count": count,
        })

    @action(
        detail=True,
        methods=["post"],
        url_path="mark-read",
    )
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()

        return Response(
            self.get_serializer(notification).data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="mark-all-read",
    )
    def mark_all_read(self, request):
        now = timezone.now()

        updated = self.get_queryset().filter(
            is_read=False,
        ).update(
            is_read=True,
            read_at=now,
            updated_at=now,
        )

        return Response({
            "updated": updated,
        })
