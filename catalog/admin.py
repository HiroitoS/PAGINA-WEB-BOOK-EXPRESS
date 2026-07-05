from django.contrib import admin

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


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "business_name", "ruc", "is_active", "order")
    list_filter = ("is_active",)
    search_fields = ("name", "business_name", "ruc")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("order", "name")


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("order", "name")


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "is_active")
    list_filter = ("provider", "is_active")
    search_fields = ("name", "provider__name")


@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


class ProductPriceInline(admin.TabularInline):
    model = ProductPrice
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "provider",
        "series",
        "level",
        "grade",
        "area",
        "product_type",
        "is_featured",
        "is_active",
    )
    list_filter = (
        "provider",
        "level",
        "grade",
        "area",
        "product_type",
        "is_featured",
        "is_active",
    )
    search_fields = ("name", "sku", "provider__name")
    inlines = [ProductPriceInline]
    ordering = ("provider__name", "order", "name")


@admin.register(ProductPrice)
class ProductPriceAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "year",
        "campaign",
        "price",
        "show_price",
        "consult_price",
        "availability",
        "is_active",
    )
    list_filter = ("year", "campaign", "availability", "is_active")
    search_fields = ("product__name", "product__provider__name")
    ordering = ("-year", "product__name")