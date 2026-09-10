from django.db.models import Q
from django.utils import timezone

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.permissions import EsAdministradorOAtencion

from .models import (
    ContactRequest,
    ContactRequestComment,
    ContactRequestStatusHistory,
)
from .serializers import (
    ContactRequestCreateSerializer,
    ContactRequestAdminSerializer,
    ContactRequestStatusUpdateSerializer,
    ContactRequestAssignSerializer,
    ContactRequestAddCommentSerializer,
    ContactRequestCommentSerializer,
    ContactRequestStatusHistorySerializer,
)


class PublicContactRequestViewSet(
    mixins.CreateModelMixin,
    viewsets.GenericViewSet
):
    queryset = ContactRequest.objects.all()
    serializer_class = ContactRequestCreateSerializer
    permission_classes = [AllowAny]


class AdminContactRequestViewSet(viewsets.ModelViewSet):
    serializer_class = ContactRequestAdminSerializer
    permission_classes = [EsAdministradorOAtencion]

    def get_queryset(self):
        queryset = (
            ContactRequest.objects
            .select_related(
                "product",
                "provider",
                "assigned_to",
            )
            .prefetch_related(
                "comments",
                "status_history",
            )
            .all()
            .order_by("-created_at")
        )

        status_param = self.request.query_params.get("status")
        source = self.request.query_params.get("source")
        priority = self.request.query_params.get("priority")
        assigned_to = self.request.query_params.get("assigned_to")
        search = self.request.query_params.get("search")
        has_next_action = self.request.query_params.get("has_next_action")

        if status_param:
            queryset = queryset.filter(status=status_param)

        if source:
            queryset = queryset.filter(source=source)

        if priority:
            queryset = queryset.filter(priority=priority)

        if assigned_to:
            queryset = queryset.filter(assigned_to_id=assigned_to)

        if has_next_action == "true":
            queryset = queryset.filter(next_action_at__isnull=False)

        if has_next_action == "false":
            queryset = queryset.filter(next_action_at__isnull=True)

        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search) |
                Q(phone__icontains=search) |
                Q(email__icontains=search) |
                Q(message__icontains=search) |
                Q(product__name__icontains=search) |
                Q(provider__name__icontains=search) |
                Q(assigned_to__username__icontains=search) |
                Q(assigned_to__first_name__icontains=search) |
                Q(assigned_to__last_name__icontains=search)
            )

        return queryset

    def perform_update(self, serializer):
        instance = self.get_object()
        old_status = instance.status

        updated_instance = serializer.save()

        if old_status != updated_instance.status:
            self._register_status_history(
                contact_request=updated_instance,
                old_status=old_status,
                new_status=updated_instance.status,
                note=""
            )

            updated_instance.mark_attention()

            if updated_instance.status in ["closed", "discarded"]:
                updated_instance.closed_at = timezone.now()

            updated_instance.save(
                update_fields=[
                    "last_attention_at",
                    "closed_at",
                    "updated_at",
                ]
            )

    def _register_status_history(
        self,
        contact_request,
        old_status,
        new_status,
        note=""
    ):
        ContactRequestStatusHistory.objects.create(
            contact_request=contact_request,
            changed_by=self.request.user,
            old_status=old_status or "",
            new_status=new_status,
            note=note
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="change-status"
    )
    def change_status(self, request, pk=None):
        contact_request = self.get_object()
        serializer = ContactRequestStatusUpdateSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        old_status = contact_request.status
        new_status = serializer.validated_data["status"]
        note = serializer.validated_data.get("note", "")

        if old_status == new_status:
            return Response(
                {"detail": "La solicitud ya se encuentra en ese estado."},
                status=status.HTTP_400_BAD_REQUEST
            )

        contact_request.status = new_status
        contact_request.mark_attention()

        if new_status in ["closed", "discarded"]:
            contact_request.closed_at = timezone.now()
        else:
            contact_request.closed_at = None

        contact_request.save(
            update_fields=[
                "status",
                "last_attention_at",
                "closed_at",
                "updated_at",
            ]
        )

        self._register_status_history(
            contact_request=contact_request,
            old_status=old_status,
            new_status=new_status,
            note=note
        )

        response_serializer = self.get_serializer(contact_request)

        return Response(response_serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="assign"
    )
    def assign(self, request, pk=None):
        contact_request = self.get_object()
        serializer = ContactRequestAssignSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        contact_request.assigned_to = serializer.validated_data.get("assigned_to")
        contact_request.mark_attention()
        contact_request.save(
            update_fields=[
                "assigned_to",
                "last_attention_at",
                "updated_at",
            ]
        )

        ContactRequestComment.objects.create(
            contact_request=contact_request,
            user=request.user,
            action_type="internal",
            comment="Se actualizó el responsable de atención."
        )

        response_serializer = self.get_serializer(contact_request)

        return Response(response_serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="add-comment"
    )
    def add_comment(self, request, pk=None):
        contact_request = self.get_object()
        serializer = ContactRequestAddCommentSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        comment = ContactRequestComment.objects.create(
            contact_request=contact_request,
            user=request.user,
            action_type=serializer.validated_data["action_type"],
            comment=serializer.validated_data["comment"]
        )

        contact_request.mark_attention()
        contact_request.save(
            update_fields=[
                "last_attention_at",
                "updated_at",
            ]
        )

        response_serializer = ContactRequestCommentSerializer(comment)

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="comments"
    )
    def comments(self, request, pk=None):
        contact_request = self.get_object()
        comments = contact_request.comments.select_related("user").all()
        serializer = ContactRequestCommentSerializer(comments, many=True)

        return Response(serializer.data)

    @action(
        detail=True,
        methods=["get"],
        url_path="history"
    )
    def history(self, request, pk=None):
        contact_request = self.get_object()
        history = contact_request.status_history.select_related("changed_by").all()
        serializer = ContactRequestStatusHistorySerializer(history, many=True)

        return Response(serializer.data)