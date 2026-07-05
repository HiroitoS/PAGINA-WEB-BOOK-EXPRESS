from django.urls import path, include
from rest_framework.routers import DefaultRouter

from catalog.views import (
    VistaPreviaCargaProductosAPIView,
    ConfirmarCargaProductosAPIView,
)

router = DefaultRouter()

urlpatterns = [
    path("", include(router.urls)),

    path(
        "importaciones/productos/preview/",
        VistaPreviaCargaProductosAPIView.as_view(),
        name="preview-carga-productos",
    ),
    path(
        "importaciones/productos/<int:carga_id>/confirmar/",
        ConfirmarCargaProductosAPIView.as_view(),
        name="confirmar-carga-productos",
    ),
]