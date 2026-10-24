from rest_framework import serializers

from warehouse.models import GoodsReceipt, GoodsReceiptLine


class ReceiptLineInputSerializer(serializers.Serializer):
    order_item_id = serializers.IntegerField(min_value=1)
    quantity_arrived = serializers.IntegerField(min_value=1)
    quantity_accepted = serializers.IntegerField(min_value=0)
    quantity_observed = serializers.IntegerField(min_value=0)
    notes = serializers.CharField(max_length=500, allow_blank=True, required=False)

    def validate(self, attrs):
        if attrs["quantity_arrived"] != attrs["quantity_accepted"] + attrs["quantity_observed"]:
            raise serializers.ValidationError(
                "La cantidad llegada debe ser igual a aceptada más observada."
            )
        return attrs


class CreateReceiptSerializer(serializers.Serializer):
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
            "quantity_arrived", "quantity_accepted", "quantity_observed", "notes",
        )


class GoodsReceiptSerializer(serializers.ModelSerializer):
    lines = GoodsReceiptLineSerializer(many=True, read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = GoodsReceipt
        fields = (
            "id", "reference", "provider", "provider_name", "document_type",
            "document_number", "received_on", "status", "notes",
            "created_by", "validated_by", "validated_at", "created_at", "lines",
        )
        read_only_fields = fields
