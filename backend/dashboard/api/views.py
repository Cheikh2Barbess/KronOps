from drf_spectacular.utils import OpenApiParameter, extend_schema
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api import TenantAPIView
from catalog.models import Article
from dashboard import product_selectors, selectors, services
from dashboard.api.serializers import (
    DashboardQuerySerializer,
    TargetQuerySerializer,
    TargetWriteSerializer,
    ThresholdSerializer,
    ThresholdWriteSerializer,
)
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


class TargetView(TenantAPIView):
    """Cibles mensuelles par produit : lisibles par tous les roles, saisies par l'Admin."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [DashboardPermission()]
        return [IsAuthenticated(), IsTenantAdmin()]

    def _payload(self, year):
        rows = product_selectors.targets_for_year(year)
        return {"year": year, "months": product_selectors.MONTHS,
                "articles": [{**r, "id": str(r["id"])} for r in rows]}

    @extend_schema(parameters=[OpenApiParameter("year", int, description="Année (défaut : l'année en cours)")])
    def get(self, request):
        query = TargetQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(self._payload(query.validated_data.get("year") or timezone.localdate().year))

    @extend_schema(request=TargetWriteSerializer)
    def put(self, request):
        serializer = TargetWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        article = Article.objects.filter(pk=data["article"]).first()
        if article is None:
            raise ValidationError({"article": ["Introuvable."]})
        services.set_targets(tenant_id=request.user.tenant_id, user=request.user, article=article,
                             year=data["year"], months=data["months"])
        row = next(r for r in self._payload(data["year"])["articles"] if r["id"] == str(article.id))
        return Response(row)
