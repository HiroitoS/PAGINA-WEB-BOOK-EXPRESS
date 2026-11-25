from django.urls import include, path
from rest_framework.routers import DefaultRouter

from purchasing.api_views import PurchaseOrderViewSet
from purchasing.api_supplier_invoices import SupplierInvoiceViewSet

router = DefaultRouter()
router.register("pedidos", PurchaseOrderViewSet, basename="pedido-editorial")
router.register("facturas-editoriales", SupplierInvoiceViewSet, basename="factura-editorial")

urlpatterns = [path("", include(router.urls))]
