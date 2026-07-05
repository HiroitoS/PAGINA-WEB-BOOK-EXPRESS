from rest_framework import serializers

from .models import ContactRequest


class ContactRequestCreateSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True
    )
    provider_name = serializers.CharField(
        source="provider.name",
        read_only=True
    )

    class Meta:
        model = ContactRequest
        fields = [
                    "id",
                    "full_name",
                    "phone",
                    "email",
                    "product",
                    "product_name",
                    "provider",
                    "provider_name",
                    "message",
                    "source",
                    "status",
                    "created_at",
                    ]
        read_only_fields = [
                        "id",
                        "product_name",
                        "provider_name",
                        "status",
                        "created_at",
                    ]

    def validate(self, attrs):
        product = attrs.get("product")
        provider = attrs.get("provider")

        if product and provider and product.provider_id != provider.id:
            raise serializers.ValidationError({
                "provider": "El proveedor enviado no corresponde al producto seleccionado."
            })

        return attrs

    def create(self, validated_data):
        product = validated_data.get("product")

        if product and not validated_data.get("provider"):
            validated_data["provider"] = product.provider

        return super().create(validated_data)


class ContactRequestAdminSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True
    )
    provider_name = serializers.CharField(
        source="provider.name",
        read_only=True
    )

    class Meta:
        model = ContactRequest
        fields = "__all__"