from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from catalog import csv_import, selectors, services
from catalog.api.serializers import (
    AllergenSerializer,
    ArticleSerializer,
    ImportFileSerializer,
    PartnerSerializer,
    UnitConversionSerializer,
)
from core.api import TenantAPIView
from tenants.permissions import ReferentialPermission


class ReferentialView(TenantAPIView):
    permission_classes = [IsAuthenticated, ReferentialPermission]


def _active_param(request):
    value = request.query_params.get("active")
    return None if value is None else value.lower() in {"1", "true", "oui"}


class AllergenListView(ReferentialView):
    @extend_schema(responses={200: AllergenSerializer(many=True)})
    def get(self, request):
        return Response(AllergenSerializer(selectors.allergen_list(), many=True).data)


class ArticleListView(ReferentialView):
    @extend_schema(
        parameters=[OpenApiParameter("type", str), OpenApiParameter("active", bool)],
        responses={200: ArticleSerializer(many=True)},
    )
    def get(self, request):
        qs = selectors.articles(article_type=request.query_params.get("type"), active=_active_param(request))
        return Response(ArticleSerializer(qs, many=True).data)

    @extend_schema(request=ArticleSerializer, responses={201: ArticleSerializer})
    def post(self, request):
        serializer = ArticleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        article = services.create_article(
            tenant_id=request.user.tenant_id, user=request.user, **serializer.validated_data
        )
        article = selectors.article_or_404(article_id=article.id)
        return Response(ArticleSerializer(article).data, status=status.HTTP_201_CREATED)


class ArticleDetailView(ReferentialView):
    @extend_schema(responses={200: ArticleSerializer})
    def get(self, request, pk):
        return Response(ArticleSerializer(selectors.article_or_404(article_id=pk)).data)

    @extend_schema(request=ArticleSerializer, responses={200: ArticleSerializer})
    def patch(self, request, pk):
        article = selectors.article_or_404(article_id=pk)
        serializer = ArticleSerializer(article, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_article(
            tenant_id=request.user.tenant_id, user=request.user, article=article, **serializer.validated_data
        )
        return Response(ArticleSerializer(selectors.article_or_404(article_id=pk)).data)


class ArticleImportView(ReferentialView):
    parser_classes = [MultiPartParser]

    @extend_schema(request={"multipart/form-data": ImportFileSerializer}, responses={201: dict, 400: dict})
    def post(self, request):
        return _run_import(request, csv_import.parse_articles, services.import_articles)


class ConversionListView(ReferentialView):
    @extend_schema(responses={200: UnitConversionSerializer(many=True)})
    def get(self, request, pk):
        article = selectors.article_or_404(article_id=pk)
        return Response(UnitConversionSerializer(selectors.conversions_of(article=article), many=True).data)

    @extend_schema(request=UnitConversionSerializer, responses={201: UnitConversionSerializer})
    def post(self, request, pk):
        article = selectors.article_or_404(article_id=pk)
        serializer = UnitConversionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversion = services.create_conversion(
            tenant_id=request.user.tenant_id, user=request.user, article=article, **serializer.validated_data
        )
        return Response(UnitConversionSerializer(conversion).data, status=status.HTTP_201_CREATED)


class PartnerListView(ReferentialView):
    @extend_schema(
        parameters=[OpenApiParameter("role", str, enum=["supplier", "customer"]), OpenApiParameter("active", bool)],
        responses={200: PartnerSerializer(many=True)},
    )
    def get(self, request):
        qs = selectors.partners(role=request.query_params.get("role"), active=_active_param(request))
        return Response(PartnerSerializer(qs, many=True).data)

    @extend_schema(request=PartnerSerializer, responses={201: PartnerSerializer})
    def post(self, request):
        serializer = PartnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        partner = services.create_partner(
            tenant_id=request.user.tenant_id, user=request.user, **serializer.validated_data
        )
        return Response(PartnerSerializer(partner).data, status=status.HTTP_201_CREATED)


class PartnerDetailView(ReferentialView):
    @extend_schema(responses={200: PartnerSerializer})
    def get(self, request, pk):
        return Response(PartnerSerializer(selectors.partner_or_404(partner_id=pk)).data)

    @extend_schema(request=PartnerSerializer, responses={200: PartnerSerializer})
    def patch(self, request, pk):
        partner = selectors.partner_or_404(partner_id=pk)
        serializer = PartnerSerializer(partner, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        partner = services.update_partner(
            tenant_id=request.user.tenant_id, user=request.user, partner=partner, **serializer.validated_data
        )
        return Response(PartnerSerializer(partner).data)


class PartnerImportView(ReferentialView):
    parser_classes = [MultiPartParser]

    @extend_schema(request={"multipart/form-data": ImportFileSerializer}, responses={201: dict, 400: dict})
    def post(self, request):
        return _run_import(request, csv_import.parse_partners, services.import_partners)


def _run_import(request, parse, save):
    serializer = ImportFileSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        rows = parse(serializer.validated_data["file"])
    except csv_import.CsvFileError as exc:
        return Response(
            {"detail": "Fichier refusé : aucune ligne n'a été importée.", "errors": exc.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    created = save(tenant_id=request.user.tenant_id, user=request.user, rows=rows)
    return Response({"created": len(created)}, status=status.HTTP_201_CREATED)
