from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from rest_framework.routers import DefaultRouter

from accounts.views import AdminUserViewSet, AdminGroupViewSet

from catalog.views import (
    PublicProviderViewSet,
    PublicLevelViewSet,
    PublicGradeViewSet,
    PublicAreaViewSet,
    PublicSeriesViewSet,
    PublicProductTypeViewSet,
    PublicProductViewSet,
    AdminProviderViewSet,
    AdminLevelViewSet,
    AdminGradeViewSet,
    AdminAreaViewSet,
    AdminSeriesViewSet,
    AdminProductTypeViewSet,
    AdminProductViewSet,
    AdminProductPriceViewSet,
    VistaPreviaCargaProductosAPIView,
    ConfirmarCargaProductosAPIView,
    AdminCargaExcelViewSet,
    DashboardResumenAPIView,
)
from inquiries.views import (
    PublicContactRequestViewSet,
    AdminContactRequestViewSet,
)


public_router = DefaultRouter()
admin_router = DefaultRouter()

# API pública para la web
public_router.register(r"providers", PublicProviderViewSet, basename="public-provider")
public_router.register(r"levels", PublicLevelViewSet, basename="public-level")
public_router.register(r"grades", PublicGradeViewSet, basename="public-grade")
public_router.register(r"areas", PublicAreaViewSet, basename="public-area")
public_router.register(r"series", PublicSeriesViewSet, basename="public-series")
public_router.register(r"product-types", PublicProductTypeViewSet, basename="public-product-type")
public_router.register(r"products", PublicProductViewSet, basename="public-product")
public_router.register(r"contact-requests", PublicContactRequestViewSet, basename="public-contact-request")

# API privada para administración futura
admin_router.register(r"providers", AdminProviderViewSet, basename="admin-provider")
admin_router.register(r"levels", AdminLevelViewSet, basename="admin-level")
admin_router.register(r"grades", AdminGradeViewSet, basename="admin-grade")
admin_router.register(r"areas", AdminAreaViewSet, basename="admin-area")
admin_router.register(r"series", AdminSeriesViewSet, basename="admin-series")
admin_router.register(r"product-types", AdminProductTypeViewSet, basename="admin-product-type")
admin_router.register(r"products", AdminProductViewSet, basename="admin-product")
admin_router.register(r"prices", AdminProductPriceViewSet, basename="admin-price")
admin_router.register(r"contact-requests", AdminContactRequestViewSet, basename="admin-contact-request")
admin_router.register(r"importaciones", AdminCargaExcelViewSet, basename="admin-importacion")
admin_router.register(r"users", AdminUserViewSet, basename="admin-user")
admin_router.register(r"roles", AdminGroupViewSet, basename="admin-role")


urlpatterns = [
    path("admin/", admin.site.urls),

    path("api/auth/", include("accounts.urls")),

    path("api/public/", include(public_router.urls)),
    path("api/admin/", include(admin_router.urls)),

    path("api-auth/", include("rest_framework.urls")),

    path(
        "api/admin/dashboard/resumen/",
        DashboardResumenAPIView.as_view(),
        name="admin-dashboard-resumen",
    ),

    path(
        "api/admin/importaciones/productos/preview/",
        VistaPreviaCargaProductosAPIView.as_view(),
        name="preview-carga-productos",
    ),
    path(
        "api/admin/importaciones/productos/<int:carga_id>/confirmar/",
        ConfirmarCargaProductosAPIView.as_view(),
        name="confirmar-carga-productos",
    ),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )

