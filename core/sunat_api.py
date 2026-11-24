"""Estado de configuración SUNAT y prueba explícita de autenticación GRE."""
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from accounts.permissions import usuario_es_administrador
from core.sunat_gre import gre_configuration, verify_gre_oauth, GreConnectionError


class SunatAdministratorOnly(BasePermission):
    def has_permission(self, request, view):
        return usuario_es_administrador(request.user)


class SunatGreConnectionView(APIView):
    permission_classes = [SunatAdministratorOnly]

    def get(self, request):
        return Response(gre_configuration())

    def post(self, request):
        # Nunca se reciben credenciales en la solicitud ni se devuelve un token.
        if request.data:
            return Response(
                {"detail": "La prueba de conexión no admite datos ni contraseñas."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            outcome = verify_gre_oauth()
        except GreConnectionError:
            return Response(
                {
                    "authenticated": False,
                    "detail": "No se pudo validar la conexión GRE. "
                    "Revisa la configuración privada del servidor.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(outcome)
