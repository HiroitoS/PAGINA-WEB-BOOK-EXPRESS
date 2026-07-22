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
    queryset = (
        ContactRequest.objects
        .select_related("product", "provider")
        .all()
        .order_by("-created_at")
    )
    serializer_class = ContactRequestAdminSerializer
    permission_classes = [EsAdministradorOAtencion]