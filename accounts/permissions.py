from rest_framework.permissions import BasePermission


ROL_ADMINISTRADOR = "ADMINISTRADOR"
ROL_CATALOGO = "CATALOGO"
ROL_ASESOR_COMERCIAL = "ASESOR_COMERCIAL"
ROL_ALMACEN = "ALMACEN"


def usuario_en_grupo(user, nombre_grupo):
    if not user or not user.is_authenticated:
        return False

    return user.groups.filter(name=nombre_grupo).exists()


class EsAdministradorOCatalogo(BasePermission):
    """
    Permiso para el panel administrativo de la web.
    Permite acceso a:
    - superuser
    - staff
    - grupo ADMINISTRADOR
    - grupo CATALOGO
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        if usuario_en_grupo(user, ROL_ADMINISTRADOR):
            return True

        if usuario_en_grupo(user, ROL_CATALOGO):
            return True

        return False


class EsAdministrador(BasePermission):
    """
    Permiso más fuerte para acciones sensibles.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        if usuario_en_grupo(user, ROL_ADMINISTRADOR):
            return True

        return False