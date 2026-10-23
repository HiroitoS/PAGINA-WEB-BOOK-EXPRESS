from rest_framework import serializers

from purchasing.models import PurchaseOrder, PurchaseOrderItem


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderItem
        fields = (
            "id", "product", "adoption_item", "product_name_snapshot",
            "product_code_snapshot", "quantity_ordered", "unit_supplier_cost", "currency",
        )
        read_only_fields = fields


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = (
            "id", "reference", "origin", "provider", "provider_name_snapshot",
            "school", "school_name_snapshot", "campaign", "campaign_name_snapshot",
            "adoption", "status", "notes", "created_at", "approved_at", "sent_at", "items",
        )
        read_only_fields = fields


class GenerateFromAdoptionSerializer(serializers.Serializer):
    adoption_id = serializers.IntegerField(min_value=1)


class ChangeQuantitySerializer(serializers.Serializer):
    item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class DispatchEvidenceSerializer(serializers.Serializer):
    evidence = serializers.CharField(max_length=2000, allow_blank=False, trim_whitespace=True)
