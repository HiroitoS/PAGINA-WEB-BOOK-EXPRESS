from django.urls import include, path
from rest_framework.routers import DefaultRouter

from warehouse.api_views import GoodsReceiptViewSet, ReceivingIncidentViewSet

router = DefaultRouter()
router.register("recepciones", GoodsReceiptViewSet, basename="recepcion-mercaderia")

router.register("incidencias", ReceivingIncidentViewSet, basename="incidencia-recepcion")

urlpatterns = [path("", include(router.urls))]
