"""Pruebas integradas de pedidos generados desde adopciones reales."""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from catalog.models import Product, Provider
from crm.models import (
    Adoption, AdoptionItem, Campaign, CommercialQuotation,
    CommercialQuotationItem, Opportunity, Pipeline, PipelineStage,
    School, SchoolContact,
)
from purchasing.models import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem
from purchasing.order_creation import create_orders_from_adoption


class GeneracionPedidosAdopcionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="compras-prueba", email="compras@example.test", password="prueba"
        )
        cls.colegio = School.objects.create(name="Colegio de prueba", created_by=cls.user)
        cls.campania = Campaign.objects.create(
            code="COMPRAS-2027-PRUEBA", name="Campaña de prueba",
            year=2027, created_by=cls.user,
        )
        cls.pipeline = Pipeline.objects.create(
            code="COMPRAS-PRUEBA", name="Pipeline de prueba", created_by=cls.user,
        )
        cls.etapa = PipelineStage.objects.create(
            pipeline=cls.pipeline, code="adopcion", name="Adopción",
            order=1, category=PipelineStage.Category.WON,
            created_by=cls.user,
        )
        cls.oportunidad = Opportunity.objects.create(
            title="Oportunidad de prueba", school=cls.colegio,
            campaign=cls.campania, pipeline=cls.pipeline,
            stage=cls.etapa, owner=cls.user, created_by=cls.user,
        )
        cls.directivo = SchoolContact.objects.create(
            school=cls.colegio, full_name="Directivo de prueba",
            position="Director", created_by=cls.user,
        )
        cls.cotizacion = CommercialQuotation.objects.create(
            opportunity=cls.oportunidad, version=1,
            status=CommercialQuotation.Status.ACCEPTED,
            school_name_snapshot=cls.colegio.name,
            campaign_name_snapshot=cls.campania.name,
            created_by=cls.user,
        )
        cls.adopcion = Adoption.objects.create(
            opportunity=cls.oportunidad, quotation=cls.cotizacion,
            school=cls.colegio, campaign=cls.campania,
            school_name_snapshot=cls.colegio.name,
            campaign_name_snapshot=cls.campania.name,
            authorized_contact=cls.directivo,
            authorized_contact_name_snapshot=cls.directivo.full_name,
            signed_at=timezone.now(), confirmed_at=timezone.now(),
            confirmed_by=cls.user,
        )
        for nombre, cantidad, costo in (
            ("Santillana Prueba", 100, Decimal("75.00")),
            ("Khalamos Prueba", 40, Decimal("35.50")),
        ):
            proveedor = Provider.objects.create(name=nombre)
            producto = Product.objects.create(
                provider=proveedor, name=f"Libro {nombre}",
                code=f"COD-{cantidad}",
            )
            detalle_cotizacion = CommercialQuotationItem.objects.create(
                quotation=cls.cotizacion, product=producto,
                product_name_snapshot=producto.name,
                provider_name_snapshot=proveedor.name,
                quantity=cantidad, pvp=Decimal("100.00"),
                supplier_cost=costo, school_price=Decimal("90.00"),
                parent_price=Decimal("100.00"),
            )
            AdoptionItem.objects.create(
                adoption=cls.adopcion, quotation_item=detalle_cotizacion,
                product=producto, product_name_snapshot=producto.name,
                provider_name_snapshot=proveedor.name,
                quantity=cantidad, pvp=Decimal("100.00"),
                supplier_cost=costo, school_price=Decimal("90.00"),
                parent_price=Decimal("100.00"),
            )

    def test_genera_pedido_por_editorial_con_cantidades_y_costos(self):
        pedidos = create_orders_from_adoption(adoption_id=self.adopcion.pk, actor=self.user)
        self.assertEqual(len(pedidos), 2)
        self.assertEqual(PurchaseOrder.objects.count(), 2)
        self.assertEqual(PurchaseOrderItem.objects.count(), 2)
        self.assertEqual(PurchaseOrderEvent.objects.count(), 2)
        self.assertEqual(
            {d.quantity_ordered for d in PurchaseOrderItem.objects.all()},
            {100, 40},
        )
        self.assertEqual(
            {d.unit_supplier_cost for d in PurchaseOrderItem.objects.all()},
            {Decimal("75.00"), Decimal("35.50")},
        )
        self.assertTrue(all(p.school_id == self.colegio.pk for p in pedidos))
        self.assertTrue(all(p.status == PurchaseOrder.Status.DRAFT for p in pedidos))

    def test_repetir_generacion_no_duplicar_ni_modificar_pedidos(self):
        primera = create_orders_from_adoption(adoption_id=self.adopcion.pk, actor=self.user)
        primera[0].status = PurchaseOrder.Status.APPROVED
        primera[0].save(update_fields=["status"])
        segunda = create_orders_from_adoption(adoption_id=self.adopcion.pk, actor=self.user)
        self.assertEqual({p.pk for p in primera}, {p.pk for p in segunda})
        self.assertEqual(PurchaseOrder.objects.count(), 2)
        self.assertEqual(PurchaseOrderItem.objects.count(), 2)
        self.assertEqual(PurchaseOrderEvent.objects.count(), 2)
        primera[0].refresh_from_db()
        self.assertEqual(primera[0].status, PurchaseOrder.Status.APPROVED)

    def test_rechaza_adopcion_no_vigente(self):
        self.adopcion.is_current = False
        self.adopcion.save(update_fields=["is_current"])
        with self.assertRaises(ValidationError):
            create_orders_from_adoption(adoption_id=self.adopcion.pk, actor=self.user)
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_no_deja_pedidos_parciales_si_falla_la_segunda_editorial(self):
        with patch(
            "purchasing.order_creation.PurchaseOrderEvent.objects.create",
            side_effect=[None, ValueError("Fallo simulado")],
        ):
            with self.assertRaises(ValueError):
                create_orders_from_adoption(adoption_id=self.adopcion.pk, actor=self.user)
        self.assertEqual(PurchaseOrder.objects.count(), 0)
        self.assertEqual(PurchaseOrderItem.objects.count(), 0)
