from django.contrib.auth.models import Group, User
from django.db import transaction

from accounts.models import RolePermissionAudit
from accounts.permission_registry import get_functional_permissions_queryset, permission_code

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.permissions import EsAdministrador
from .permission_registry import serialize_functional_permissions
from .serializers import (
    AdminUserSerializer,
    ChangePasswordSerializer,
    GroupSerializer,
    RolePermissionsUpdateSerializer,
    LoginSerializer,
    get_user_auth_data,
)


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes= [AllowAny]


class UsuarioActualView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            get_user_auth_data(request.user)
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")

        if not refresh_token:
            return Response(
                {"error": "Debe enviar el refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            return Response(
                {"error": "Token inválido o ya cerrado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"message": "Sesión cerrada correctamente."},
            status=status.HTTP_200_OK,
        )


class AdminUserViewSet(viewsets.ModelViewSet):
    queryset = (
        User.objects
        .select_related("book_express_profile")
        .prefetch_related(
            "groups",
            "groups__permissions__content_type",
            "user_permissions__content_type",
        )
        .all()
        .order_by("username")
    )
    serializer_class = AdminUserSerializer
    permission_classes = [EsAdministrador]

    @action(
        detail=False,
        methods=["get"],
        url_path="permissions",
    )
    def permissions(self, request):
        return Response({
            "results": serialize_functional_permissions(),
        })

    @action(
        detail=True,
        methods=["post"],
        url_path="change-password",
    )
    def change_password(self, request, pk=None):
        user = self.get_object()
        serializer = ChangePasswordSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        user.set_password(serializer.validated_data["password"])
        user.save()

        return Response({
            "message": "Contraseña actualizada correctamente."
        })


class AdminGroupViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Group.objects
        .prefetch_related("permissions__content_type")
        .all()
        .order_by("name")
    )
    serializer_class = GroupSerializer
    permission_classes = [EsAdministrador]

    @action(detail=True, methods=["patch"], url_path="permisos")
    @transaction.atomic
    def update_functional_permissions(self, request, pk=None):
        """Modifica el rol base sin tocar otros permisos y conserva auditoría."""
        if set(request.data) != {"functional_permission_ids"}:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({
                "detail": "Envía únicamente la lista de permisos funcionales del rol."
            })
        group = Group.objects.select_for_update().get(pk=self.get_object().pk)
        if group.name == "ADMINISTRADOR":
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                "El rol Administrador está protegido. Gestiona otros roles o permisos individuales."
            )
        serializer = RolePermissionsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested = serializer.validated_data["functional_permission_ids"]
        functional_ids = set(
            get_functional_permissions_queryset().values_list("id", flat=True)
        )
        current_permissions = list(group.permissions.all())
        old = sorted(
            permission_code(item) for item in current_permissions
            if item.pk in functional_ids
        )
        new = sorted(permission_code(item) for item in requested)
        if old != new:
            preserved = [
                item for item in current_permissions if item.pk not in functional_ids
            ]
            group.permissions.set([*preserved, *requested])
            RolePermissionAudit.objects.create(
                group=group, actor=request.user,
                previous_permissions=old, new_permissions=new,
            )
        return Response(GroupSerializer(group).data)

    @action(detail=True, methods=["get"], url_path="historial-permisos")
    def permission_history(self, request, pk=None):
        group = self.get_object()
        changes = group.book_express_permission_changes.select_related("actor")[:25]
        return Response({
            "results": [
                {
                    "id": item.pk,
                    "changed_at": item.changed_at,
                    "actor": item.actor.get_full_name().strip() or item.actor.get_username(),
                    "previous_permissions": item.previous_permissions,
                    "new_permissions": item.new_permissions,
                }
                for item in changes
            ]
        })
