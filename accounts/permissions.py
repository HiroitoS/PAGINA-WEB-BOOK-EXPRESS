from rest_framework.permissions import BasePermission


# ============================================================
# ROLES WEB - BOOK EXPRESS
# ============================================================

ROL_ADMINISTRADOR = "ADMINISTRADOR"
ROL_CATALOGO = "CATALOGO"
ROL_ATENCION = "ATENCION"


# ============================================================
# ROLES ERP FUTURO - NO USAR TODAVÍA EN LA WEB V1
# ============================================================

ROL_ASESOR_COMERCIAL = "ASESOR_COMERCIAL"
ROL_ALMACEN = "ALMACEN"


def usuario_en_grupo(user, nombre_grupo):
    if not user or not user.is_authenticated:
        return False

    return user.groups.filter(name=nombre_grupo).exists()


def usuario_es_administrador(user):
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return usuario_en_grupo(user, ROL_ADMINISTRADOR)


def usuario_es_catalogo(user):
    return usuario_en_grupo(user, ROL_CATALOGO)


def usuario_es_atencion(user):
    return usuario_en_grupo(user, ROL_ATENCION)


class EsAdministrador(BasePermission):
    """
    Permiso fuerte para acciones sensibles.

    Permite:
    - superuser
    - grupo ADMINISTRADOR

    Uso recomendado:
    - usuarios
    - roles
    - acciones críticas
    """

    def has_permission(self, request, view):
        return usuario_es_administrador(request.user)


class EsAdministradorOCatalogo(BasePermission):
    """
    Permiso para gestión del catálogo.

    Permite:
    - ADMINISTRADOR
    - CATALOGO

    Uso recomendado:
    - productos
    - precios
    - proveedores
    - niveles
    - grados
    - áreas
    - series
    - tipos de producto
    - importaciones Excel
    """

    def has_permission(self, request, view):
        user = request.user

        if usuario_es_administrador(user):
            return True

        if usuario_es_catalogo(user):
            return True

        return False


class EsAdministradorOAtencion(BasePermission):
    """
    Permiso para atención comercial web.

    Permite:
    - ADMINISTRADOR
    - ATENCION

    Uso recomendado:
    - solicitudes de contacto
    - seguimiento por WhatsApp
    """

    def has_permission(self, request, view):
        user = request.user

        if usuario_es_administrador(user):
            return True

        if usuario_es_atencion(user):
            return True

        return False


class EsUsuarioPanel(BasePermission):
    """
    Permiso general para entrar al panel administrativo web.

    Permite:
    - ADMINISTRADOR
    - CATALOGO
    - ATENCION

    Uso recomendado:
    - dashboard
    - endpoints generales del panel
    """

    def has_permission(self, request, view):
        user = request.user

        if usuario_es_administrador(user):
            return True

        if usuario_es_catalogo(user):
            return True

        if usuario_es_atencion(user):
            return True

        return False