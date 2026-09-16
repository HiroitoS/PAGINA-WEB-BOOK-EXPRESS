from rest_framework.permissions import BasePermission, SAFE_METHODS


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
ROL_JEFE_COMERCIAL = "JEFE_COMERCIAL"
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


def usuario_es_jefe_comercial(user):
    return usuario_en_grupo(user, ROL_JEFE_COMERCIAL)


def usuario_tiene_permiso(user, permission):
    if not user or not user.is_authenticated:
        return False

    if usuario_es_administrador(user):
        return True

    return user.has_perm(permission)


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


# ============================================================
# PERMISOS FUNCIONALES V2 - BOOK EXPRESS
# ============================================================

class TienePermisoFuncional(BasePermission):
    """
    Permiso genérico para vistas que declaran:
        required_permission = "app.codename"

    Mantiene al ADMINISTRADOR como acceso total y delega el resto
    a los permisos efectivos de Django.
    """

    def has_permission(self, request, view):
        permission = getattr(view, "required_permission", None)

        if not permission:
            return False

        return usuario_tiene_permiso(request.user, permission)


class PermisoCatalogo(BasePermission):
    """
    Catálogo interno:
    - GET / HEAD / OPTIONS -> catalog.view_catalog
    - POST / PUT / PATCH / DELETE -> catalog.manage_catalog
    """

    def has_permission(self, request, view):
        permission = (
            "catalog.view_catalog"
            if request.method in SAFE_METHODS
            else "catalog.manage_catalog"
        )
        return usuario_tiene_permiso(request.user, permission)


class PermisoPrecios(BasePermission):
    """
    Precios internos:
    - GET / HEAD / OPTIONS -> catalog.view_prices
    - POST / PUT / PATCH / DELETE -> catalog.manage_prices
    """

    def has_permission(self, request, view):
        permission = (
            "catalog.view_prices"
            if request.method in SAFE_METHODS
            else "catalog.manage_prices"
        )
        return usuario_tiene_permiso(request.user, permission)


class PuedeGestionarImportaciones(BasePermission):
    """
    Importaciones del catálogo.
    """

    def has_permission(self, request, view):
        return usuario_tiene_permiso(
            request.user,
            "catalog.manage_imports",
        )


class PermisoSolicitudes(BasePermission):
    """
    Solicitudes:
    - GET / HEAD / OPTIONS -> inquiries.view_inquiries
    - operaciones de atención -> inquiries.manage_inquiries

    La asignación de responsable se protege aparte con
    PuedeAsignarSolicitudes.
    """

    def has_permission(self, request, view):
        permission = (
            "inquiries.view_inquiries"
            if request.method in SAFE_METHODS
            else "inquiries.manage_inquiries"
        )
        return usuario_tiene_permiso(request.user, permission)


class PuedeAsignarSolicitudes(BasePermission):
    """
    Permiso específico para cambiar el responsable de una solicitud.
    """

    def has_permission(self, request, view):
        return usuario_tiene_permiso(
            request.user,
            "inquiries.assign_inquiries",
        )
