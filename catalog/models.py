from django.db import models
from django.utils.text import slugify

from core.models import TimeStampedModel


class Provider(TimeStampedModel):
    name = models.CharField(
        max_length=150,
        unique=True,
        verbose_name="Nombre comercial"
    )
    slug = models.SlugField(
        max_length=180,
        unique=True,
        blank=True
    )
    business_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Razón social"
    )
    ruc = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="RUC"
    )
    description = models.TextField(
        blank=True,
        verbose_name="Descripción"
    )
    logo = models.ImageField(
        upload_to="providers/logos/",
        blank=True,
        null=True,
        verbose_name="Logo"
    )
    website = models.URLField(
        blank=True,
        verbose_name="Sitio web"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Orden"
    )

    class Meta:
        verbose_name = "Proveedor / Editorial"
        verbose_name_plural = "Proveedores / Editoriales"
        ordering = ["order", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Level(TimeStampedModel):
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Nivel"
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Nivel"
        verbose_name_plural = "Niveles"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Grade(TimeStampedModel):
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Grado"
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Grado"
        verbose_name_plural = "Grados"
        ordering = ["order", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Area(TimeStampedModel):
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Área"
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Área"
        verbose_name_plural = "Áreas"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Series(TimeStampedModel):
    name = models.CharField(
        max_length=150,
        verbose_name="Serie"
    )
    slug = models.SlugField(
        max_length=180,
        blank=True
    )
    provider = models.ForeignKey(
        Provider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="series",
        verbose_name="Proveedor / Editorial"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Serie"
        verbose_name_plural = "Series"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "name"],
                name="unique_series_by_provider"
            )
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            if self.provider:
                self.slug = slugify(f"{self.provider.name}-{self.name}")
            else:
                self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProductType(TimeStampedModel):
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Tipo de producto"
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Tipo de producto"
        verbose_name_plural = "Tipos de producto"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(TimeStampedModel):
    provider = models.ForeignKey(
        Provider,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Proveedor / Editorial"
    )
    name = models.CharField(
        max_length=250,
        verbose_name="Nombre del libro"
    )
    slug = models.SlugField(
        max_length=280,
        blank=True
    )
    code = models.CharField(
    max_length=100,
    blank=True,
    verbose_name="Código de producto / código de barras"
    )
    sku = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Código interno / SKU"
    )

    series = models.ForeignKey(
        Series,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Serie"
    )
    level = models.ForeignKey(
        Level,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Nivel"
    )
    grade = models.ForeignKey(
        Grade,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Grado"
    )
    area = models.ForeignKey(
        Area,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Área"
    )
    product_type = models.ForeignKey(
        ProductType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Tipo de producto"
    )

    cover_image = models.ImageField(
        upload_to="products/covers/",
        blank=True,
        null=True,
        verbose_name="Portada"
    )
    description = models.TextField(
        blank=True,
        verbose_name="Descripción"
    )
    is_featured = models.BooleanField(
        default=False,
        verbose_name="Destacado"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Orden"
    )

    class Meta:
        verbose_name = "Producto / Libro"
        verbose_name_plural = "Productos / Libros"
        ordering = ["provider__name", "order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "name"],
                name="unique_product_name_by_provider"
            )
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.provider.name}-{self.name}")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} - {self.provider.name}"


class ProductPrice(TimeStampedModel):
    AVAILABILITY_CHOICES = [
        ("available", "Disponible"),
        ("limited", "Stock limitado"),
        ("out_of_stock", "Agotado"),
        ("on_request", "A consultar"),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="prices",
        verbose_name="Producto"
    )
    year = models.PositiveIntegerField(
        verbose_name="Año de catálogo"
    )
    campaign = models.CharField(
        max_length=100,
        default="Campaña escolar",
        verbose_name="Campaña"
    )
    currency = models.CharField(
        max_length=10,
        default="PEN",
        verbose_name="Moneda"
    )
    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Precio costo"
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Precio referencial"
    )
    show_price = models.BooleanField(
        default=False,
        verbose_name="Mostrar precio en web"
    )
    consult_price = models.BooleanField(
        default=True,
        verbose_name="Mostrar como consultar precio"
    )
    availability = models.CharField(
        max_length=30,
        choices=AVAILABILITY_CHOICES,
        default="on_request",
        verbose_name="Disponibilidad"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )

    class Meta:
        verbose_name = "Precio por año"
        verbose_name_plural = "Precios por año"
        ordering = ["-year", "product__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "year", "campaign"],
                name="unique_price_by_product_year_campaign"
            )
        ]

    def __str__(self):
        if self.price and self.show_price:
            return f"{self.product.name} - {self.year} - S/ {self.price}"
        return f"{self.product.name} - {self.year} - Consultar precio"

class CargaExcel(models.Model):
    ESTADO_CHOICES = [
        ("PENDIENTE", "Pendiente"),
        ("VALIDADO", "Validado"),
        ("IMPORTADO", "Importado"),
        ("ERROR", "Error"),
    ]

    archivo = models.FileField(upload_to="importaciones/productos/")
    anio_catalogo = models.PositiveIntegerField()
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default="PENDIENTE"
    )

    total_filas = models.PositiveIntegerField(default=0)
    total_nuevos = models.PositiveIntegerField(default=0)
    total_actualizados = models.PositiveIntegerField(default=0)
    total_errores = models.PositiveIntegerField(default=0)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Carga Excel"
        verbose_name_plural = "Cargas Excel"

    def __str__(self):
        return f"Carga Excel {self.id} - {self.anio_catalogo} - {self.estado}"


class CargaExcelDetalle(models.Model):
    ACCION_CHOICES = [
        ("NUEVO", "Nuevo"),
        ("ACTUALIZAR", "Actualizar"),
        ("ERROR", "Error"),
    ]

    carga = models.ForeignKey(
        CargaExcel,
        on_delete=models.CASCADE,
        related_name="detalles"
    )

    numero_fila = models.PositiveIntegerField()

    codigo_producto = models.CharField(max_length=100, blank=True, null=True)
    sku = models.CharField(max_length=100, blank=True, null=True)
    nombre = models.CharField(max_length=255, blank=True, null=True)
    proveedor_editorial = models.CharField(max_length=150, blank=True, null=True)

    accion = models.CharField(max_length=20, choices=ACCION_CHOICES)
    errores = models.JSONField(default=list, blank=True)
    datos_originales = models.JSONField(default=dict, blank=True)

    procesado = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Detalle de carga Excel"
        verbose_name_plural = "Detalles de carga Excel"

    def __str__(self):
        return f"Fila {self.numero_fila} - {self.accion}"