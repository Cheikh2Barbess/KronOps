from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api import TenantAPIView
from dashboard import selectors, services
from dashboard.api.serializers import DashboardQuerySerializer, ThresholdSerializer, ThresholdWriteSerializer
from dashboard.indicators import THRESHOLDS
from tenants.permissions import IsTenantAdmin, has_role
from tenants.models import User


class DashboardPermission(IsAuthenticated):
    """Tableau de bord : chaque role de l'entreprise a le sien. Le contenu depend du role (selectors.ROLE_TILES)."""

    def has_permission(self, request, view):
        return has_role(request.user, *User.Role.values)


class DashboardView(TenantAPIView):
    permission_classes = [DashboardPermission]

    @extend_schema(parameters=[OpenApiParameter("days", int, description="7, 30, 90 ou 365 jours")])
    def get(self, request):
        query = DashboardQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(selectors.dashboard(user=request.user, days=query.validated_data.get("days")))


class ThresholdListView(TenantAPIView):
    """Seuils des couleurs : lisibles par tous les roles (les ecrans en ont besoin), regles par l'Admin."""

    permission_classes = [DashboardPermission]

    @extend_schema(responses={200: ThresholdSerializer(many=True)})
    def get(self, request):
        return Response(ThresholdSerializer(selectors.thresholds().values(), many=True).data)


class ThresholdDetailView(TenantAPIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsTenantAdmin()]

    def _code(self, code):
        if code not in THRESHOLDS:
            raise NotFound("Indicateur inconnu.")
        return code

    @extend_schema(request=ThresholdWriteSerializer, responses={200: ThresholdSerializer})
    def put(self, request, code):
        code = self._code(code)
        serializer = ThresholdWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_threshold(tenant_id=request.user.tenant_id, user=request.user, code=code,
                               **serializer.validated_data)
        return Response(ThresholdSerializer(selectors.thresholds()[code]).data)

    @extend_schema(responses={200: ThresholdSerializer})
    def delete(self, request, code):
        code = self._code(code)
        services.reset_threshold(tenant_id=request.user.tenant_id, user=request.user, code=code)
        return Response(ThresholdSerializer(selectors.thresholds()[code]).data)
