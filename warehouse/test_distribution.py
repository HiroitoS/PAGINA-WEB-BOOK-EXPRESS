"""Modalidades logísticas intercambiables, con trazabilidad sin cambiar la adopción."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from purchasing.test_integration import GeneracionPedidosAdopcionTests
from warehouse.models import (
    DistributionOperation, DistributionOperationEvent,
    DistributionOperationLine, StockEntry, StockTransfer, WarehouseLocation,
)


class DistributionAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        GeneracionPedidosAdopcionTests.setUpTestData.__func__(cls)
        cls.main = WarehouseLocation.objects.create(
            code="D-PRINC", name="Principal", kind=WarehouseLocation.Kind.MAIN,
        )
        cls.store = WarehouseLocation.objects.create(
            code="D-TIENDA", name="Tienda", kind=WarehouseLocation.Kind.STORE,
        )
        cls.fair = WarehouseLocation.objects.create(
            code="D-FERIA", name="Feria", kind=WarehouseLocation.Kind.FAIR,
        )
        cls.cons = WarehouseLocation.objects.create(
            code="D-CONSIG", name="Consignación", kind=WarehouseLocation.Kind.CONSIGNMENT,
        )
        cls.outsider = get_user_model().objects.create_user(username="sin-distribucion")

    def client_as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def payload(self, **overrides):
        data = {
            "idempotency_key": str(uuid4()),
            "adoption_id": self.adopcion.pk,
            "mode": "fair",
            "source_id": self.main.pk,
            "destination_id": self.fair.pk,
            "operation_name": "Feria de campaña del colegio",
            "responsible_name": "Responsable de almacén",
            "scheduled_on": "2027-02-01",
            "scheduled_until": "2027-02-03",
            "notes": "Sólo planificación",
            "items": [
                {"product_id": item.product_id, "quantity": item.quantity}
                for item in self.adopcion.items.all()
            ],
        }
        data.update(overrides)
        return data

    def test_crear_desde_adopcion_no_mueve_ni_reserva_inventario(self):
        before = StockEntry.objects.count(), StockTransfer.objects.count()
        response = self.client_as(self.user).post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            self.payload(), format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        record = DistributionOperation.objects.get()
        self.assertEqual(record.school_id, self.colegio.pk)
        self.assertEqual(record.mode, "fair")
        self.assertEqual(record.original_mode, "")
        self.assertEqual(record.events.count(), 1)
        self.assertEqual(
            sorted(record.items.values_list("quantity_planned", flat=True)),
            [40, 100],
        )
        self.assertEqual(
            (StockEntry.objects.count(), StockTransfer.objects.count()), before,
        )
        self.assertIn("todavía no reserva", response.data["notice"])
        self.assertEqual(
            self.client_as(self.user).get(
                "/api/admin/erp/almacen/operaciones-distribucion/opciones/"
            ).status_code, 200,
        )

    def test_opciones_busqueda_por_colegio_anio_y_paginacion(self):
        client = self.client_as(self.user)
        url = "/api/admin/erp/almacen/operaciones-distribucion/opciones/"
        result = client.get(url)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertGreaterEqual(result.data["adoptions_meta"]["count"], 1)
        self.assertEqual(result.data["adoptions_meta"]["page"], 1)
        self.assertIn(self.adopcion.pk, [item["id"] for item in result.data["adoptions"]])

        name = self.adopcion.school_name_snapshot[:5]
        filtered = client.get(url, {"buscar": name, "anio": self.adopcion.campaign.year})
        self.assertEqual(filtered.status_code, 200, filtered.data)
        self.assertIn(
            self.adopcion.pk, [item["id"] for item in filtered.data["adoptions"]],
        )

        no_match = client.get(url, {"buscar": "colegio-que-no-existe-999"})
        self.assertEqual(no_match.status_code, 200, no_match.data)
        self.assertEqual(no_match.data["adoptions_meta"]["count"], 0)
        self.assertEqual(no_match.data["adoptions"], [])

        for params in (
            {"page": "0"}, {"page": "999999"},
            {"anio": "20xx"}, {"buscar": "a" * 101},
        ):
            with self.subTest(params=params):
                invalid = client.get(url, params)
                self.assertEqual(invalid.status_code, 400, invalid.data)

        self.assertEqual(
            self.client_as(self.outsider).get(url).status_code, 403,
        )
        self.assertFalse(DistributionOperation.objects.exists())

    def test_transiciones_todas_las_modalidades_y_repetidos_con_historial(self):
        client = self.client_as(self.user)
        for original, destino in [
            ("point_of_sale", "fair"),
            ("point_of_sale", "consignment"),
            ("fair", "point_of_sale"),
            ("fair", "consignment"),
            ("consignment", "point_of_sale"),
            ("consignment", "fair"),
        ]:
            with self.subTest(original=original, destino=destino):
                self.adopcion.sale_mode = original
                self.adopcion.save(update_fields=["sale_mode"])
                created = client.post(
                    "/api/admin/erp/almacen/operaciones-distribucion/",
                    self.payload(
                        idempotency_key=str(uuid4()),
                        mode=original,
                    ), format="json",
                )
                self.assertEqual(created.status_code, 201, created.data)
                pk = created.data["id"]
                response = client.patch(
                    f"/api/admin/erp/almacen/operaciones-distribucion/{pk}/",
                    {
                        "mode": destino,
                        "reason": "El colegio cambió de modalidad de entrega.",
                    }, format="json",
                )
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["mode"], destino)
                self.assertEqual(response.data["original_mode"], original)
                self.assertEqual(len(response.data["events"]), 2)
                self.assertEqual(response.data["events"][1]["previous"]["mode"], original)
                self.assertEqual(response.data["events"][1]["current"]["mode"], destino)
                self.adopcion.refresh_from_db()
                self.assertEqual(self.adopcion.sale_mode, original)
                self.assertEqual(
                    client.post(
                        f"/api/admin/erp/almacen/operaciones-distribucion/{pk}/anular/",
                        {"reason": "La prueba pasa a otra modalidad."},
                        format="json",
                    ).status_code, 200,
                )
        self.assertEqual(StockEntry.objects.count(), 0)
        self.assertEqual(StockTransfer.objects.count(), 0)

    def test_b2_distribuir_total_o_dividir_en_tres_entregas(self):
        client = self.client_as(self.user)
        url = "/api/admin/erp/almacen/operaciones-distribucion/"
        product = self.adopcion.items.order_by("-quantity").first()
        other = self.adopcion.items.exclude(product_id=product.product_id).first()

        def items(q1, q2):
            return [
                {"product_id": product.product_id, "quantity": q1},
                {"product_id": other.product_id, "quantity": q2},
            ]

        first = client.post(url, self.payload(
            mode="fair", items=items(50, 20),
        ), format="json")
        self.assertEqual(first.status_code, 201, first.data)
        second = client.post(url, self.payload(
            mode="point_of_sale", destination_id=self.store.pk,
            items=items(30, 10),
        ), format="json")
        self.assertEqual(second.status_code, 201, second.data)
        third = client.post(url, self.payload(
            mode="consignment", destination_id=self.cons.pk,
            items=items(20, 10),
        ), format="json")
        self.assertEqual(third.status_code, 201, third.data)

        summary = client.get(
            url + "asignacion/", {"adoption_id": self.adopcion.pk},
        )
        self.assertEqual(summary.status_code, 200, summary.data)
        by_product = {line["product_id"]: line for line in summary.data["items"]}
        self.assertEqual(by_product[product.product_id]["assignable"], 0)
        self.assertEqual(by_product[other.product_id]["assignable"], 0)

        excessive = client.post(url, self.payload(
            items=items(1, 1),
        ), format="json")
        self.assertEqual(excessive.status_code, 400, excessive.data)
        self.assertEqual(DistributionOperation.objects.count(), 3)
        self.assertEqual(StockEntry.objects.count(), 0)
        self.assertEqual(StockTransfer.objects.count(), 0)

        cancel = client.post(
            url + f"{third.data['id']}/anular/",
            {"reason": "El colegio reprograma esta entrega."},
            format="json",
        )
        self.assertEqual(cancel.status_code, 200, cancel.data)
        summary = client.get(
            url + "asignacion/", {"adoption_id": self.adopcion.pk},
        )
        by_product = {line["product_id"]: line for line in summary.data["items"]}
        self.assertEqual(by_product[product.product_id]["assignable"], 20)
        self.assertEqual(by_product[other.product_id]["assignable"], 10)

    def test_b2_editar_cantidades_con_motivo_y_liberar_saldo(self):
        client = self.client_as(self.user)
        url = "/api/admin/erp/almacen/operaciones-distribucion/"
        products = list(self.adopcion.items.all())
        first = client.post(url, self.payload(
            items=[
                {"product_id": item.product_id, "quantity": 10}
                for item in products
            ],
        ), format="json")
        self.assertEqual(first.status_code, 201, first.data)
        pk = first.data["id"]
        summary = client.get(
            url + "asignacion/",
            {"adoption_id": self.adopcion.pk, "operation_id": pk},
        )
        self.assertEqual(summary.status_code, 200, summary.data)
        for line in summary.data["items"]:
            self.assertEqual(line["current_planned"], 10)
            self.assertEqual(line["other_planned"], 0)
            self.assertEqual(line["assignable"], line["adopted"])

        only = products[0]
        edited = client.patch(
            url + f"{pk}/",
            {
                "items": [{"product_id": only.product_id, "quantity": 4}],
                "reason": "Separar la siguiente entrega a tienda.",
            },
            format="json",
        )
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(len(edited.data["items"]), 1)
        self.assertEqual(edited.data["items"][0]["quantity_planned"], 4)
        self.assertEqual(len(edited.data["events"]), 2)
        self.assertEqual(
            sorted(x["quantity"] for x in edited.data["events"][0]["current"]["items"]),
            [10, 10],
        )
        self.assertEqual(
            edited.data["events"][1]["current"]["items"][0]["quantity"], 4,
        )

        follow = client.post(
            url,
            self.payload(
                destination_id=self.store.pk, mode="point_of_sale",
                items=[
                    {"product_id": only.product_id, "quantity": only.quantity - 4},
                ],
            ),
            format="json",
        )
        self.assertEqual(follow.status_code, 201, follow.data)

    def test_b2_rechaza_cantidades_erroneas_y_duplicados(self):
        client = self.client_as(self.user)
        url = "/api/admin/erp/almacen/operaciones-distribucion/"
        item = self.adopcion.items.first()
        bad_cases = [
            [],
            [{"product_id": item.product_id, "quantity": 0}],
            [{"product_id": item.product_id, "quantity": -1}],
            [{"product_id": item.product_id, "quantity": 1.5}],
            [{"product_id": item.product_id, "quantity": item.quantity + 1}],
            [{"product_id": 9999999, "quantity": 1}],
            [
                {"product_id": item.product_id, "quantity": 1},
                {"product_id": item.product_id, "quantity": 1},
            ],
        ]
        for items in bad_cases:
            with self.subTest(items=items):
                response = client.post(
                    url, self.payload(items=items), format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(DistributionOperation.objects.exists())
        self.assertEqual(
            self.client_as(self.outsider).get(
                url + "asignacion/", {"adoption_id": self.adopcion.pk},
            ).status_code, 403,
        )

    def test_b2_no_reutiliza_clave_para_otras_cantidades(self):
        client = self.client_as(self.user)
        url = "/api/admin/erp/almacen/operaciones-distribucion/"
        data = self.payload()
        created = client.post(url, data, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        again = client.post(url, data, format="json")
        self.assertEqual(again.status_code, 200, again.data)
        original = data["items"][0]
        altered = {
            **data,
            "items": [
                {**original, "quantity": original["quantity"] - 1},
                *data["items"][1:],
            ],
        }
        duplicate = client.post(url, altered, format="json")
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        self.assertEqual(DistributionOperation.objects.count(), 1)

    def test_reintento_idempotente_y_no_permite_reutilizar_clave_con_otros_datos(self):
        client = self.client_as(self.user)
        data = self.payload()
        first = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            data, format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        repeat = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            data, format="json",
        )
        self.assertEqual(repeat.status_code, 200, repeat.data)
        other = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            {**data, "mode": "point_of_sale"}, format="json",
        )
        self.assertEqual(other.status_code, 400, other.data)
        self.assertEqual(DistributionOperation.objects.count(), 1)
        self.assertEqual(DistributionOperationEvent.objects.count(), 1)

    def test_anulacion_no_modifica_registros_anteriores(self):
        client = self.client_as(self.user)
        new = client.post(
            "/api/admin/erp/almacen/operaciones-distribucion/",
            self.payload(), format="json",
        )
        pk = new.data["id"]
        base = f"/api/admin/erp/almacen/operaciones-distribucion/{pk}/"
        self.assertEqual(
            client.patch(base, {"mode": "consignment"}, format="json").status_code,
            400,
        )
        self.assertEqual(
            client.post(base + "anular/", {"reason": "No"}, format="json").status_code,
            400,
        )
        cancelled = client.post(
            base + "anular/", {"reason": "El colegio suspendió su feria."},
            format="json",
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["status"], "cancelled")
        self.assertEqual(
            client.patch(
                base, {"mode": "point_of_sale", "reason": "Cambiar a librería."},
                format="json",
            ).status_code, 400,
        )
        self.assertEqual(DistributionOperationLine.objects.count(), 2)
        self.assertEqual(DistributionOperationEvent.objects.count(), 2)

    def test_restricciones_de_destino_fechas_permisos(self):
        client = self.client_as(self.user)
        cases = [
            self.payload(destination_id=self.main.pk),
            self.payload(scheduled_on="2027-05-05", scheduled_until="2027-01-01"),
            self.payload(mode="otra"),
            self.payload(responsible_name=""),
            self.payload(adoption_id=999999),
        ]
        for data in cases:
            with self.subTest(data=data):
                response = client.post(
                    "/api/admin/erp/almacen/operaciones-distribucion/",
                    data, format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(DistributionOperation.objects.exists())
        self.assertEqual(
            self.client_as(self.outsider).get(
                "/api/admin/erp/almacen/operaciones-distribucion/",
            ).status_code, 403,
        )
        self.assertEqual(
            self.client_as(self.outsider).post(
                "/api/admin/erp/almacen/operaciones-distribucion/",
                self.payload(), format="json",
            ).status_code, 403,
        )
