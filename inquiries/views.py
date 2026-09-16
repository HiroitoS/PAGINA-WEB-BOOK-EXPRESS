from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.permissions import (
    PermisoSolicitudes,
    PuedeAsignarSolicitudes,
)

from .models import (
    ContactRequest,
    ContactRequestComment,
    ContactRequestStatusHistory,
)
from .notification_events import (
    notify_contact_request_assigned,
    notify_contact_request_comment_added,
    notify_contact_request_status_changed,
    notify_new_contact_request,
    resolve_contact_request_notifications,
)
from .serializers import (
    ContactRequestCreateSerializer,
    ContactRequestAdminSerializer,
    ContactRequestStatusUpdateSerializer,
    ContactRequestAssignSerializer,
    ContactRequestAddCommentSerializer,
    ContactRequestCommentSerializer,
    ContactRequestStatusHistorySerializer,
    ContactRequestAttentionSerializer,
    ContactRequestReopenSerializer,
)


class PublicContactRequestViewSet(
    mixins.CreateModelMixin,
    viewsets.GenericViewSet
):
    queryset = ContactRequest.objects.all()
    serializer_class = ContactRequestCreateSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        contact_request = serializer.save()

        notify_new_contact_request(contact_request)


class AdminContactRequestViewSet(viewsets.ModelViewSet):
    serializer_class = ContactRequestAdminSerializer
    permission_classes = [PermisoSolicitudes]
    CLOSED_STATUSES = {"closed", "discarded"}

    def _request_is_closed(self, contact_request):
        return contact_request.status in self.CLOSED_STATUSES

    def _closed_response(self):
        return Response(
            {
                "detail": (
                    "La solicitud está cerrada. Reábrela con un motivo "
                    "antes de registrar nuevas atenciones o cambios."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def get_permissions(self):
        if self.action == "assign":
            return [PuedeAsignarSolicitudes()]

        return [permission() for permission in self.permission_classes]

    def destroy(self, request, *args, **kwargs):
        return Response(
            {
                "detail": (
                    "Las solicitudes no se eliminan. Si no corresponde continuar, "
                    "registra una atención y cambia su estado a Descartado."
                )
            },
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

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
        inquiry_type = self.request.query_params.get("inquiry_type")
        priority = self.request.query_params.get("priority")
        assigned_to = self.request.query_params.get("assigned_to")
        search = self.request.query_params.get("search")
        has_next_action = self.request.query_params.get("has_next_action")

        if status_param:
            queryset = queryset.filter(status=status_param)

        if source:
            queryset = queryset.filter(source=source)

        if inquiry_type:
            queryset = queryset.filter(inquiry_type=inquiry_type)

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
    @transaction.atomic
    def change_status(self, request, pk=None):
        contact_request = self.get_object()
        serializer = ContactRequestStatusUpdateSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        old_status = contact_request.status
        new_status = serializer.validated_data["status"]
        note = serializer.validated_data.get("note", "")

        if self._request_is_closed(contact_request):
            return self._closed_response()

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

        if new_status in ["closed", "discarded"]:
            resolve_contact_request_notifications(contact_request)

        notify_contact_request_status_changed(
            contact_request,
            actor=request.user,
            old_status=old_status,
        )

        response_serializer = self.get_serializer(contact_request)

        return Response(response_serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="register-attention"
    )
    @transaction.atomic
    def register_attention(self, request, pk=None):
        contact_request = self.get_object()

        if self._request_is_closed(contact_request):
            return self._closed_response()

        serializer = ContactRequestAttentionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_status = contact_request.status
        new_status = serializer.validated_data.get("status") or old_status

        comment = ContactRequestComment.objects.create(
            contact_request=contact_request,
            user=request.user,
            action_type=serializer.validated_data["action_type"],
            comment=serializer.validated_data["comment"],
        )

        status_changed = new_status != old_status
        contact_request.mark_attention()

        update_fields = [
            "last_attention_at",
            "updated_at",
        ]

        if status_changed:
            contact_request.status = new_status
            update_fields.append("status")

            if new_status in ["closed", "discarded"]:
                contact_request.closed_at = timezone.now()
            else:
                contact_request.closed_at = None

            update_fields.append("closed_at")

        contact_request.save(update_fields=update_fields)

        if status_changed:
            self._register_status_history(
                contact_request=contact_request,
                old_status=old_status,
                new_status=new_status,
                note="",
            )

            if new_status in ["closed", "discarded"]:
                resolve_contact_request_notifications(contact_request)

            notify_contact_request_status_changed(
                contact_request,
                actor=request.user,
                old_status=old_status,
            )
        else:
            notify_contact_request_comment_added(
                comment,
                actor=request.user,
            )

        response_serializer = self.get_serializer(contact_request)

        return Response(response_serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="reopen"
    )
    @transaction.atomic
    def reopen(self, request, pk=None):
        contact_request = self.get_object()

        if not self._request_is_closed(contact_request):
            return Response(
                {"detail": "Solo una solicitud cerrada o descartada puede reabrirse."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ContactRequestReopenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_status = contact_request.status
        reason = serializer.validated_data["reason"]

        contact_request.status = "in_follow_up"
        contact_request.closed_at = None
        contact_request.mark_attention()
        contact_request.save(
            update_fields=[
                "status",
                "closed_at",
                "last_attention_at",
                "updated_at",
            ]
        )

        self._register_status_history(
            contact_request=contact_request,
            old_status=old_status,
            new_status="in_follow_up",
            note=reason,
        )

        notify_contact_request_status_changed(
            contact_request,
            actor=request.user,
            old_status=old_status,
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

        if self._request_is_closed(contact_request):
            return self._closed_response()

        serializer = ContactRequestAssignSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        previous_assignee = contact_request.assigned_to
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

        notify_contact_request_assigned(
            contact_request,
            actor=request.user,
            previous_assignee=previous_assignee,
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

        if self._request_is_closed(contact_request):
            return self._closed_response()

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

        notify_contact_request_comment_added(
            comment,
            actor=request.user,
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