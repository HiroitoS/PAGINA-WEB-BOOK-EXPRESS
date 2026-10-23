from django.urls import include, path
from rest_framework.routers import DefaultRouter

from purchasing.api_views import PurchaseOrderViewSet

router = DefaultRouter()
router.register("pedidos", PurchaseOrderViewSet, basename="pedido-editorial")

urlpatterns = [path("", include(router.urls))]
