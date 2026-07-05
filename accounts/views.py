from django.contrib.auth.models import User, Group

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.permissions import EsAdministrador
from .serializers import (
    LoginSerializer,
    AdminUserSerializer,
    GroupSerializer,
    ChangePasswordSerializer,
)


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer


class UsuarioActualView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        grupos = list(user.groups.values_list("name", flat=True))

        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "roles": grupos,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")

        if not refresh_token:
            return Response(
                {"error": "Debe enviar el refresh token."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            return Response(
                {"error": "Token inválido o ya cerrado."},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"message": "Sesión cerrada correctamente."},
            status=status.HTTP_200_OK
        )


class AdminUserViewSet(viewsets.ModelViewSet):
    queryset = (
        User.objects
        .prefetch_related("groups")
        .all()
        .order_by("username")
    )
    serializer_class = AdminUserSerializer
    permission_classes = [EsAdministrador]

    @action(
        detail=True,
        methods=["post"],
        url_path="change-password"
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
    queryset = Group.objects.all().order_by("name")
    serializer_class = GroupSerializer
    permission_classes = [EsAdministrador]