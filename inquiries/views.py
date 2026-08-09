from django.db.models import Q

from rest_framework import mixins, viewsets
from rest_framework.permissions import AllowAny

from accounts.permissions import EsAdministradorOAtencion

from .models import ContactRequest
from .serializers import (
    ContactRequestCreateSerializer,
    ContactRequestAdminSerializer,
)


class PublicContactRequestViewSet(
    mixins.CreateModelMixin,
    viewsets.GenericViewSet
):
    queryset = ContactRequest.objects.all()
    serializer_class = ContactRequestCreateSerializer
    permission_classes = [AllowAny]


class AdminContactRequestViewSet(viewsets.ModelViewSet):
    serializer_class = ContactRequestAdminSerializer
    permission_classes = [EsAdministradorOAtencion]

    def get_queryset(self):
        queryset = (
            ContactRequest.objects
            .select_related("product", "provider")
            .all()
            .order_by("-created_at")
        )

        status = self.request.query_params.get("status")
        source = self.request.query_params.get("source")
        search = self.request.query_params.get("search")

        if status:
            queryset = queryset.filter(status=status)

        if source:
            queryset = queryset.filter(source=source)

        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search) |
                Q(phone__icontains=search) |
                Q(email__icontains=search) |
                Q(message__icontains=search) |
                Q(product__name__icontains=search) |
                Q(provider__name__icontains=search)
            )

        return queryset