from django.urls import include, path
from rest_framework.routers import DefaultRouter

from warehouse.api_views import GoodsReceiptViewSet, ReceivingIncidentViewSet
from warehouse.api_inventory import InventoryEntryViewSet
from warehouse.api_locations import WarehouseLocationViewSet
from warehouse.api_transfers import StockTransferViewSet

router = DefaultRouter()
router.register("recepciones", GoodsReceiptViewSet, basename="recepcion-mercaderia")

router.register("incidencias", ReceivingIncidentViewSet, basename="incidencia-recepcion")
router.register("inventario", InventoryEntryViewSet, basename="inventario")
router.register("ubicaciones", WarehouseLocationViewSet, basename="ubicaciones-almacen")
router.register("traslados", StockTransferViewSet, basename="traslados-almacen")

urlpatterns = [path("", include(router.urls))]
