from rest_framework import serializers
from catalog.models import CargaExcel, CargaExcelDetalle

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



class ProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Provider
        fields = [
            "id",
            "name",
            "slug",
            "business_name",
            "ruc",
            "description",
            "logo",
            "website",
            "is_active",
            "order",
        ]


class LevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Level
        fields = ["id", "name", "slug", "is_active"]


class GradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Grade
        fields = ["id", "name", "slug", "order", "is_active"]


class AreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ["id", "name", "slug", "is_active"]


class SeriesSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(
        source="provider.name",
        read_only=True
    )

    class Meta:
        model = Series
        fields = [
            "id",
            "name",
            "slug",
            "provider",
            "provider_name",
            "is_active",
        ]


class ProductTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductType
        fields = ["id", "name", "slug", "is_active"]


class ProductPriceSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True
    )
    provider_name = serializers.CharField(
        source="product.provider.name",
        read_only=True
    )

    class Meta:
        model = ProductPrice
        fields = [
            "id",
            "product",
            "product_name",
            "provider_name",
            "year",
            "campaign",
            "currency",
            "cost_price",
            "price",
            "show_price",
            "consult_price",
            "availability",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "product_name",
            "provider_name",
            "created_at",
            "updated_at",
        ]


class ProductPublicListSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    provider_slug = serializers.CharField(source="provider.slug", read_only=True)
    series_name = serializers.CharField(source="series.name", read_only=True)
    level_name = serializers.CharField(source="level.name", read_only=True)
    grade_name = serializers.CharField(source="grade.name", read_only=True)
    area_name = serializers.CharField(source="area.name", read_only=True)
    product_type_name = serializers.CharField(source="product_type.name", read_only=True)
    latest_price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "provider",
            "provider_name",
            "provider_slug",
            "name",
            "slug",
            "sku",
            "series_name",
            "level_name",
            "grade_name",
            "area_name",
            "product_type_name",
            "cover_image",
            "description",
            "is_featured",
            "latest_price",
        ]

    def get_latest_price(self, obj):
        price = obj.prices.filter(is_active=True).order_by("-year").first()

        if not price:
            return None

        return {
            "year": price.year,
            "campaign": price.campaign,
            "currency": price.currency,
            "price": price.price if price.show_price else None,
            "show_price": price.show_price,
            "consult_price": price.consult_price,
            "availability": price.availability,
        }


class ProductPublicDetailSerializer(serializers.ModelSerializer):
    provider = ProviderSerializer(read_only=True)
    series = SeriesSerializer(read_only=True)
    level = LevelSerializer(read_only=True)
    grade = GradeSerializer(read_only=True)
    area = AreaSerializer(read_only=True)
    product_type = ProductTypeSerializer(read_only=True)
    prices = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "provider",
            "name",
            "slug",
            "sku",
            "series",
            "level",
            "grade",
            "area",
            "product_type",
            "cover_image",
            "description",
            "is_featured",
            "prices",
        ]

    def get_prices(self, obj):
        prices = obj.prices.filter(is_active=True).order_by("-year")
        data = []

        for price in prices:
            data.append({
                "year": price.year,
                "campaign": price.campaign,
                "currency": price.currency,
                "price": price.price if price.show_price else None,
                "show_price": price.show_price,
                "consult_price": price.consult_price,
                "availability": price.availability,
            })

        return data


class ProductAdminSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    series_name = serializers.CharField(source="series.name", read_only=True)
    level_name = serializers.CharField(source="level.name", read_only=True)
    grade_name = serializers.CharField(source="grade.name", read_only=True)
    area_name = serializers.CharField(source="area.name", read_only=True)
    product_type_name = serializers.CharField(source="product_type.name", read_only=True)
    latest_price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "provider",
            "provider_name",
            "name",
            "slug",
            "code",
            "sku",
            "series",
            "series_name",
            "level",
            "level_name",
            "grade",
            "grade_name",
            "area",
            "area_name",
            "product_type",
            "product_type_name",
            "cover_image",
            "description",
            "is_featured",
            "is_active",
            "order",
            "latest_price",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "provider_name",
            "series_name",
            "level_name",
            "grade_name",
            "area_name",
            "product_type_name",
            "latest_price",
            "created_at",
            "updated_at",
        ]

    def get_latest_price(self, obj):
        price = obj.prices.filter(is_active=True).order_by("-year").first()

        if not price:
            return None

        return {
            "id": price.id,
            "year": price.year,
            "campaign": price.campaign,
            "currency": price.currency,
            "cost_price": price.cost_price,
            "price": price.price,
            "show_price": price.show_price,
            "consult_price": price.consult_price,
            "availability": price.availability,
            "is_active": price.is_active,
        }



class CargaExcelPreviewSerializer(serializers.Serializer):
    archivo = serializers.FileField()
    anio_catalogo = serializers.IntegerField()


class CargaExcelDetalleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CargaExcelDetalle
        fields = [
            "id",
            "numero_fila",
            "codigo_producto",
            "sku",
            "nombre",
            "proveedor_editorial",
            "accion",
            "errores",
            "datos_originales",
            "procesado",
            "creado_en",
        ]


class CargaExcelSerializer(serializers.ModelSerializer):
    detalles = CargaExcelDetalleSerializer(many=True, read_only=True)

    class Meta:
        model = CargaExcel
        fields = [
            "id",
            "archivo",
            "anio_catalogo",
            "estado",
            "total_filas",
            "total_nuevos",
            "total_actualizados",
            "total_errores",
            "creado_en",
            "actualizado_en",
            "detalles",
        ]

class CargaExcelListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CargaExcel
        fields = [
            "id",
            "archivo",
            "anio_catalogo",
            "estado",
            "total_filas",
            "total_nuevos",
            "total_actualizados",
            "total_errores",
            "creado_en",
            "actualizado_en",
        ]