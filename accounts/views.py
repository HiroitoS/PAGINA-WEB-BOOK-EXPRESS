from django.contrib.auth.models import Group, User

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
