from drf_spectacular.utils import extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit import selectors
from audit.api.serializers import AuditEntrySerializer, AuditFilterSerializer, AuditUserSerializer
from core.api import TenantAPIView
from tenants.permissions import AuditReadPermission
from tenants.selectors import users_of_tenant


class AuditPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class AuditListView(TenantAPIView):
    """Journal d'audit, lecture seule, le plus recent d'abord (US-03)."""

    permission_classes = [IsAuthenticated, AuditReadPermission]

    @extend_schema(parameters=[AuditFilterSerializer], responses={200: AuditEntrySerializer(many=True)})
    def get(self, request):
        filters = AuditFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        qs = selectors.audit_entries(
            entity_type=data.get("entity_type"), entity_id=data.get("entity_id"), action=data.get("action"),
            user_id=data.get("user"), date_from=data.get("date_from"), date_to=data.get("date_to"),
        )
        paginator = AuditPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(AuditEntrySerializer(page, many=True).data)


class AuditUserListView(TenantAPIView):
    """Utilisateurs de l'entreprise, pour le filtre « qui » de l'ecran."""

    permission_classes = [IsAuthenticated, AuditReadPermission]

    @extend_schema(responses={200: AuditUserSerializer(many=True)})
    def get(self, request):
        users = users_of_tenant(tenant_id=request.user.tenant_id)
        return Response(AuditUserSerializer(users, many=True).data)
