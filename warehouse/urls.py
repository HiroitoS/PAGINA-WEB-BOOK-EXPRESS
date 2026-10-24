from django.urls import include, path
from rest_framework.routers import DefaultRouter

from warehouse.api_views import GoodsReceiptViewSet

router = DefaultRouter()
router.register("recepciones", GoodsReceiptViewSet, basename="recepcion-mercaderia")

urlpatterns = [path("", include(router.urls))]
