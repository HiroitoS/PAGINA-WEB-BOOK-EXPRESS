from rest_framework import viewsets, status, filters
from rest_framework.permissions import AllowAny
from accounts.permissions import EsAdministradorOCatalogo, EsAdministrador
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import (
    Provider,
    Level,
    Grade,
    Area,
    Series,
    ProductType,
    Product,
    ProductPrice,
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
)

from catalog.models import CargaExcel
from catalog.serializers import (
    CargaExcelPreviewSerializer,
    CargaExcelSerializer,
)
from catalog.services.importar_productos_excel import (
    crear_vista_previa_productos,
    confirmar_importacion_productos,
)


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

        if year:
            queryset = queryset.filter(
                prices__year=year,
                prices__is_active=True
            ).distinct()

        if search:
            queryset = queryset.filter(name__icontains=search)

        if featured == "true":
            queryset = queryset.filter(is_featured=True)

        return queryset.order_by("provider__name", "order", "name")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ProductPublicDetailSerializer
        return ProductPublicListSerializer


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

        if is_active in ["true", "false"]:
            queryset = queryset.filter(is_active=(is_active == "true"))

        return queryset


class AdminProductPriceViewSet(viewsets.ModelViewSet):
    queryset = (
        ProductPrice.objects
        .select_related("product", "product__provider")
        .all()
        .order_by("-year", "product__name")
    )
    serializer_class = ProductPriceSerializer
    permission_classes = [EsAdministradorOCatalogo]



class VistaPreviaCargaProductosAPIView(APIView):
    permission_classes = [EsAdministrador]
    def post(self, request):
        serializer = CargaExcelPreviewSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
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
            status=status.HTTP_201_CREATED
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
            status=status.HTTP_200_OK
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