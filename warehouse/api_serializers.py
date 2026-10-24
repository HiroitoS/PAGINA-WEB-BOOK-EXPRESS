from rest_framework import serializers

from warehouse.models import GoodsReceipt, GoodsReceiptEvent, GoodsReceiptLine


class ReceiptLineInputSerializer(serializers.Serializer):
    order_item_id = serializers.IntegerField(min_value=1)
    quantity_arrived = serializers.IntegerField(min_value=1)
    quantity_accepted = serializers.IntegerField(min_value=0)
    quantity_observed = serializers.IntegerField(min_value=0)
    quantity_documented = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    quantity_extra = serializers.IntegerField(min_value=0, required=False, default=0)
    notes = serializers.CharField(max_length=500, allow_blank=True, required=False)

    def validate(self, attrs):
        if attrs["quantity_documented"] is not None and attrs["quantity_documented"] < 0:
            raise serializers.ValidationError("La cantidad de guía no puede ser negativa.")
        if attrs["quantity_arrived"] != attrs["quantity_accepted"] + attrs["quantity_observed"] + attrs["quantity_extra"]:
            raise serializers.ValidationError(
                "Lo recibido debe coincidir con aceptado, excedente conforme y observado."
            )
        return attrs


class CreateReceiptSerializer(serializers.Serializer):
    def validate(self, attrs):
        if attrs["document_type"] == GoodsReceipt.DocumentType.GUIDE:
            for row in attrs["lines"]:
                if row.get("quantity_documented") is None:
                    raise serializers.ValidationError({"lines": "Registra la cantidad según guía de cada producto."})
        return attrs

    provider_id = serializers.IntegerField(min_value=1)
    document_type = serializers.ChoiceField(choices=GoodsReceipt.DocumentType.choices)
    document_number = serializers.CharField(max_length=100, allow_blank=True)
    received_on = serializers.DateField()
    notes = serializers.CharField(allow_blank=True, required=False)
    lines = ReceiptLineInputSerializer(many=True, allow_empty=False)


class GoodsReceiptLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="order_item.product_name_snapshot", read_only=True,
    )
    order_id = serializers.IntegerField(
        source="order_item.order_id", read_only=True,
    )

    class Meta:
        model = GoodsReceiptLine
        fields = (
            "id", "order_item", "order_id", "product_name",
            "quantity_arrived", "quantity_documented", "quantity_accepted", "quantity_extra", "quantity_observed", "notes",
        )


class GoodsReceiptEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    def get_actor_name(self, obj):
        return obj.actor.get_full_name().strip() or obj.actor.get_username()

    class Meta:
        model = GoodsReceiptEvent
        fields = ("id", "action", "actor_name", "created_at", "notes")
        read_only_fields = fields


class GoodsReceiptSerializer(serializers.ModelSerializer):
    lines = GoodsReceiptLineSerializer(many=True, read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    fulfillment_status = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    validated_by_name = serializers.SerializerMethodField()
    events = GoodsReceiptEventSerializer(many=True, read_only=True)

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name().strip() or obj.created_by.get_username()

    def get_validated_by_name(self, obj):
        if not obj.validated_by_id:
            return None
        return obj.validated_by.get_full_name().strip() or obj.validated_by.get_username()

    def get_fulfillment_status(self, obj):
        # Estado de cumplimiento de los pedidos asociados, distinto de
        # la validación administrativa del documento de entrega.
        if obj.status != GoodsReceipt.Status.VALIDATED:
            return "draft"
        estados = {line.order_item.order.status for line in obj.lines.all()}
        if estados and estados == {"received"}:
            return "complete"
        return "pending"

    class Meta:
        model = GoodsReceipt
        fields = (
            "id", "reference", "provider", "provider_name", "document_type",
            "document_number", "received_on", "status", "fulfillment_status", "notes",
            "created_by", "created_by_name", "validated_by", "validated_by_name",
            "validated_at", "created_at", "lines", "events",
        )
        read_only_fields = fields
