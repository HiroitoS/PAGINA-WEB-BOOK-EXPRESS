from django.db.models import Q
from django.utils import timezone

from rest_framework import viewsets, status, filters
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework.response import Response

from accounts.permissions import EsAdministradorOCatalogo, EsAdministrador, EsUsuarioPanel
from inquiries.models import ContactRequest

from .models import (
    Provider,
    Level,
    Grade,
    Area,
    Series,
    ProductType,
    Product,
    ProductPrice,
    CargaExcel,
)

from .serializers import (
    ProviderSerializer,
    LevelSerializer,
    GradeSerializer,
    AreaSerializer,
    SeriesSerializer,
    ProductTypeSerializer,
    ProductPriceSerializer,
    ProductPublicListSerializer,
    ProductPublicDetailSerializer,
    ProductAdminSerializer,
    CargaExcelSerializer,
    CargaExcelListSerializer,
    CargaExcelPreviewSerializer,
)

from catalog.services.importar_productos_excel import (
    crear_vista_previa_productos,
    confirmar_importacion_productos,
)


# ============================================================
# API PÚBLICA - WEB BOOK EXPRESS
# ============================================================

class PublicProviderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProviderSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        return Provider.objects.filter(is_active=True).order_by("order", "name")


class PublicLevelViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LevelSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        return Level.objects.filter(is_active=True).order_by("name")


class PublicGradeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = GradeSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        return Grade.objects.filter(is_active=True).order_by("order", "name")


class PublicAreaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AreaSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        return Area.objects.filter(is_active=True).order_by("name")


class PublicSeriesViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SeriesSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        queryset = Series.objects.filter(is_active=True).select_related("provider")

        provider = self.request.query_params.get("provider")
        if provider:
            queryset = queryset.filter(provider__slug=provider)

        return queryset.order_by("name")


class PublicProductTypeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductTypeSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        return ProductType.objects.filter(is_active=True).order_by("name")


class PublicProductViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        queryset = (
            Product.objects
            .filter(is_active=True, provider__is_active=True)
            .select_related(
                "provider",
                "series",
                "level",
                "grade",
                "area",
                "product_type",
            )
            .prefetch_related("prices")
        )

        provider = self.request.query_params.get("provider")
        level = self.request.query_params.get("level")
        grade = self.request.query_params.get("grade")
        area = self.request.query_params.get("area")
        product_type = self.request.query_params.get("product_type")
        series = self.request.query_params.get("series")
        year = self.request.query_params.get("year")
        search = self.request.query_params.get("search")
        featured = self.request.query_params.get("featured")

        if provider:
            queryset = queryset.filter(provider__slug=provider)

        if level:
            queryset = queryset.filter(level__slug=level)

        if grade:
            queryset = queryset.filter(grade__slug=grade)

        if area:
            queryset = queryset.filter(area__slug=area)

        if product_type:
            queryset = queryset.filter(product_type__slug=product_type)

        if series:
            queryset = queryset.filter(series__slug=series)

        if year:
            queryset = queryset.filter(
                prices__year=year,
                prices__is_active=True,
            ).distinct()

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(slug__icontains=search) |
                Q(sku__icontains=search) |
                Q(code__icontains=search) |
                Q(description__icontains=search) |
                Q(provider__name__icontains=search) |
                Q(provider__slug__icontains=search) |
                Q(series__name__icontains=search) |
                Q(series__slug__icontains=search) |
                Q(level__name__icontains=search) |
                Q(level__slug__icontains=search) |
                Q(grade__name__icontains=search) |
                Q(grade__slug__icontains=search) |
                Q(area__name__icontains=search) |
                Q(area__slug__icontains=search) |
                Q(product_type__name__icontains=search) |
                Q(product_type__slug__icontains=search)
            ).distinct()

        if featured == "true":
            queryset = queryset.filter(is_featured=True)

        return queryset.order_by("provider__name", "order", "name")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ProductPublicDetailSerializer

        return ProductPublicListSerializer


# ============================================================
# API ADMINISTRATIVA - PANEL REACT
# ============================================================

class AdminProviderViewSet(viewsets.ModelViewSet):
    queryset = Provider.objects.all().order_by("order", "name")
    serializer_class = ProviderSerializer
    permission_classes = [EsAdministradorOCatalogo]


class AdminLevelViewSet(viewsets.ModelViewSet):
    queryset = Level.objects.all().order_by("name")
    serializer_class = LevelSerializer
    permission_classes = [EsAdministradorOCatalogo]


class AdminGradeViewSet(viewsets.ModelViewSet):
    queryset = Grade.objects.all().order_by("order", "name")
    serializer_class = GradeSerializer
    permission_classes = [EsAdministradorOCatalogo]


class AdminAreaViewSet(viewsets.ModelViewSet):
    queryset = Area.objects.all().order_by("name")
    serializer_class = AreaSerializer
    permission_classes = [EsAdministradorOCatalogo]


class AdminSeriesViewSet(viewsets.ModelViewSet):
    queryset = Series.objects.select_related("provider").all().order_by("name")
    serializer_class = SeriesSerializer
    permission_classes = [EsAdministradorOCatalogo]


class AdminProductTypeViewSet(viewsets.ModelViewSet):
    queryset = ProductType.objects.all().order_by("name")
    serializer_class = ProductTypeSerializer
    permission_classes = [EsAdministradorOCatalogo]


class AdminProductViewSet(viewsets.ModelViewSet):
    queryset = (
        Product.objects
        .select_related(
            "provider",
            "series",
            "level",
            "grade",
            "area",
            "product_type",
        )
        .prefetch_related("prices")
        .all()
        .order_by("provider__name", "order", "name")
    )
    serializer_class = ProductAdminSerializer
    permission_classes = [EsAdministradorOCatalogo]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "name",
        "sku",
        "code",
        "provider__name",
        "area__name",
        "grade__name",
    ]
    ordering_fields = [
        "name",
        "provider__name",
        "created_at",
        "updated_at",
        "order",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        provider = self.request.query_params.get("provider")
        level = self.request.query_params.get("level")
        grade = self.request.query_params.get("grade")
        area = self.request.query_params.get("area")
        product_type = self.request.query_params.get("product_type")
        series = self.request.query_params.get("series")
        is_active = self.request.query_params.get("is_active")

        if provider:
            queryset = queryset.filter(provider_id=provider)

        if level:
            queryset = queryset.filter(level_id=level)

        if grade:
            queryset = queryset.filter(grade_id=grade)

        if area:
            queryset = queryset.filter(area_id=area)

        if product_type:
            queryset = queryset.filter(product_type_id=product_type)

        if series:
            queryset = queryset.filter(series_id=series)

        if is_active in ["true", "false"]:
            queryset = queryset.filter(is_active=(is_active == "true"))

        return queryset


class AdminProductPriceViewSet(viewsets.ModelViewSet):
    serializer_class = ProductPriceSerializer
    permission_classes = [EsAdministradorOCatalogo]

    def get_queryset(self):
        queryset = (
            ProductPrice.objects
            .select_related(
                "product",
                "product__provider",
            )
            .all()
        )

        search = self.request.query_params.get("search")
        year = self.request.query_params.get("year")
        is_active = self.request.query_params.get("is_active")
        product = self.request.query_params.get("product")
        provider = self.request.query_params.get("provider")

        if search:
            queryset = queryset.filter(
                Q(product__name__icontains=search) |
                Q(product__code__icontains=search) |
                Q(product__sku__icontains=search) |
                Q(product__provider__name__icontains=search) |
                Q(campaign__icontains=search)
            )

        if year:
            queryset = queryset.filter(year=year)

        if is_active in ["true", "false"]:
            queryset = queryset.filter(is_active=(is_active == "true"))

        if product:
            queryset = queryset.filter(product_id=product)

        if provider:
            queryset = queryset.filter(product__provider_id=provider)

        return queryset.order_by("product__name", "-year", "-created_at")


# ============================================================
# DASHBOARD ADMINISTRATIVO
# ============================================================

class DashboardResumenAPIView(APIView):
    permission_classes = [EsUsuarioPanel]

    def get(self, request):
        anio_actual = timezone.now().year
        anio = request.query_params.get("anio") or request.query_params.get("year") or anio_actual

        try:
            anio = int(anio)
        except (TypeError, ValueError):
            anio = anio_actual

        total_productos = Product.objects.count()
        productos_activos = Product.objects.filter(is_active=True).count()
        productos_inactivos = Product.objects.filter(is_active=False).count()

        productos_sin_portada = Product.objects.filter(
            is_active=True
        ).filter(
            Q(cover_image__isnull=True) | Q(cover_image="")
        ).count()

        productos_con_precio_anio = Product.objects.filter(
            prices__year=anio,
            prices__is_active=True,
        ).distinct().count()

        productos_sin_precio_anio = Product.objects.filter(
            is_active=True
        ).exclude(
            prices__year=anio,
            prices__is_active=True,
        ).distinct().count()

        total_proveedores = Provider.objects.count()
        proveedores_activos = Provider.objects.filter(is_active=True).count()
        proveedores_inactivos = Provider.objects.filter(is_active=False).count()

        total_solicitudes = ContactRequest.objects.count()
        solicitudes_nuevas = ContactRequest.objects.filter(status="new").count()
        solicitudes_contactadas = ContactRequest.objects.filter(status="contacted").count()
        solicitudes_en_seguimiento = ContactRequest.objects.filter(status="in_follow_up").count()
        solicitudes_cerradas = ContactRequest.objects.filter(status="closed").count()
        solicitudes_descartadas = ContactRequest.objects.filter(status="discarded").count()

        importaciones_queryset = CargaExcel.objects.filter(anio_catalogo=anio)

        total_importaciones = importaciones_queryset.count()
        importaciones_validadas = importaciones_queryset.filter(estado="VALIDADO").count()
        importaciones_importadas = importaciones_queryset.filter(estado="IMPORTADO").count()
        importaciones_con_error = importaciones_queryset.filter(estado="ERROR").count()

        ultimas_solicitudes = (
            ContactRequest.objects
            .select_related("product", "provider")
            .all()
            .order_by("-created_at")[:5]
        )

        ultimas_importaciones = (
            CargaExcel.objects
            .filter(anio_catalogo=anio)
            .order_by("-creado_en")[:5]
        )

        ultimas_solicitudes_data = []
        for solicitud in ultimas_solicitudes:
            ultimas_solicitudes_data.append({
                "id": solicitud.id,
                "full_name": solicitud.full_name,
                "phone": solicitud.phone,
                "email": solicitud.email,
                "message": solicitud.message,
                "source": solicitud.source,
                "status": solicitud.status,
                "created_at": solicitud.created_at,
                "product_name": solicitud.product.name if solicitud.product else "",
                "provider_name": solicitud.provider.name if solicitud.provider else "",
            })

        ultimas_importaciones_data = []
        for carga in ultimas_importaciones:
            archivo_nombre = ""

            if carga.archivo:
                archivo_nombre = carga.archivo.name.split("/")[-1]

            ultimas_importaciones_data.append({
                "id": carga.id,
                "archivo": archivo_nombre,
                "anio_catalogo": carga.anio_catalogo,
                "estado": carga.estado,
                "total_filas": carga.total_filas,
                "total_nuevos": carga.total_nuevos,
                "total_actualizados": carga.total_actualizados,
                "total_errores": carga.total_errores,
                "creado_en": carga.creado_en,
            })

        data = {
            "anio": anio,
            "productos": {
                "total": total_productos,
                "activos": productos_activos,
                "inactivos": productos_inactivos,
                "sin_portada": productos_sin_portada,
                "con_precio_anio": productos_con_precio_anio,
                "sin_precio_anio": productos_sin_precio_anio,
            },
            "proveedores": {
                "total": total_proveedores,
                "activos": proveedores_activos,
                "inactivos": proveedores_inactivos,
            },
            "solicitudes": {
                "total": total_solicitudes,
                "nuevas": solicitudes_nuevas,
                "contactadas": solicitudes_contactadas,
                "en_seguimiento": solicitudes_en_seguimiento,
                "cerradas": solicitudes_cerradas,
                "descartadas": solicitudes_descartadas,
            },
            "importaciones": {
                "total": total_importaciones,
                "validadas": importaciones_validadas,
                "importadas": importaciones_importadas,
                "con_error": importaciones_con_error,
            },
            "actividad_reciente": {
                "ultimas_solicitudes": ultimas_solicitudes_data,
                "ultimas_importaciones": ultimas_importaciones_data,
            },
        }

        return Response(data, status=status.HTTP_200_OK)



# ============================================================
# CARGA MASIVA DESDE EXCEL
# ============================================================

class VistaPreviaCargaProductosAPIView(APIView):
    permission_classes = [EsAdministrador]

    def post(self, request):
        serializer = CargaExcelPreviewSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        archivo = serializer.validated_data["archivo"]
        anio_catalogo = serializer.validated_data["anio_catalogo"]

        carga = crear_vista_previa_productos(
            archivo=archivo,
            anio_catalogo=anio_catalogo,
        )

        response_serializer = CargaExcelSerializer(carga)

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )


class ConfirmarCargaProductosAPIView(APIView):
    permission_classes = [EsAdministrador]

    def post(self, request, carga_id):
        try:
            carga = confirmar_importacion_productos(carga_id)
        except CargaExcel.DoesNotExist:
            return Response(
                {"error": "La carga no existe."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as error:
            return Response(
                {"error": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CargaExcelSerializer(carga)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class AdminCargaExcelViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        CargaExcel.objects
        .all()
        .order_by("-creado_en")
    )
    permission_classes = [EsAdministradorOCatalogo]

    def get_queryset(self):
        queryset = super().get_queryset()

        if self.action == "retrieve":
            return queryset.prefetch_related("detalles")

        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return CargaExcelListSerializer

        return CargaExcelSerializer