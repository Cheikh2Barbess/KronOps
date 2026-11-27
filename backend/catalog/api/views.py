from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from catalog import csv_import, selectors, services
from catalog.api.serializers import (
    AllergenSerializer,
    ArticleFilterSerializer,
    ArticleSerializer,
    CitySerializer,
    ImportFileSerializer,
    ParcelFilterSerializer,
    ParcelSerializer,
    PartnerFilterSerializer,
    PartnerSerializer,
    UnitConversionSerializer,
)
from core.api import TenantAPIView
from catalog.models import Partner
from tenants.permissions import ReferentialPermission


class ReferentialView(TenantAPIView):
    permission_classes = [IsAuthenticated, ReferentialPermission]


class ReferentialPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


def _paginated(request, view, qs, serializer_class):
    paginator = ReferentialPagination()
    page = paginator.paginate_queryset(qs, request, view=view)
    return paginator.get_paginated_response(serializer_class(page, many=True).data)


def _filters(request, serializer_class):
    filters = serializer_class(data=request.query_params)
    filters.is_valid(raise_exception=True)
    return filters.validated_data


class AllergenListView(ReferentialView):
    @extend_schema(responses={200: AllergenSerializer(many=True)})
    def get(self, request):
        return Response(AllergenSerializer(selectors.allergen_list(), many=True).data)


class ArticleListView(ReferentialView):
    @extend_schema(parameters=[ArticleFilterSerializer], responses={200: ArticleSerializer(many=True)})
    def get(self, request):
        data = _filters(request, ArticleFilterSerializer)
        qs = selectors.articles(
            q=data.get("q"), article_type=data.get("type"), storage=data.get("storage"), active=data.get("active"),
            allergen=data.get("allergen"), presence=data["presence"], allergen_free=data.get("allergen_free"),
            has_allergen=data.get("has_allergen"),
        )
        return _paginated(request, self, qs, ArticleSerializer)

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
    @extend_schema(parameters=[PartnerFilterSerializer], responses={200: PartnerSerializer(many=True)})
    def get(self, request):
        data = _filters(request, PartnerFilterSerializer)
        qs = selectors.partners(q=data.get("q"), role=data.get("role"), city=data.get("city"), active=data.get("active"))
        return _paginated(request, self, qs, PartnerSerializer)

    @extend_schema(request=PartnerSerializer, responses={201: PartnerSerializer})
    def post(self, request):
        serializer = PartnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        partner = services.create_partner(
            tenant_id=request.user.tenant_id, user=request.user, **serializer.validated_data
        )
        return Response(PartnerSerializer(partner).data, status=status.HTTP_201_CREATED)


class PartnerCityListView(ReferentialView):
    """Villes deja saisies, pour le choix du filtre « ville » de l'ecran."""

    @extend_schema(responses={200: CitySerializer(many=True)})
    def get(self, request):
        return Response(CitySerializer(selectors.partner_cities(), many=True).data)


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


def _producer(data):
    """Le producteur vient d'un identifiant : la RLS rend « introuvable » celui d'un autre client."""
    producer_id = data.pop("producer_id", None)
    if producer_id is None:
        return {}
    producer = Partner.objects.filter(pk=producer_id).first()
    if producer is None:
        raise ValidationError({"producer": ["Introuvable."]})
    return {"producer": producer}


class ParcelListView(ReferentialView):
    @extend_schema(parameters=[ParcelFilterSerializer], responses={200: ParcelSerializer(many=True)})
    def get(self, request):
        data = _filters(request, ParcelFilterSerializer)
        qs = selectors.parcels(q=data.get("q"), producer_id=data.get("producer"),
                               organic_status=data.get("organic_status"), active=data.get("active"))
        return _paginated(request, self, qs, ParcelSerializer)

    @extend_schema(request=ParcelSerializer, responses={201: ParcelSerializer})
    def post(self, request):
        serializer = ParcelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.update(_producer(data))
        parcel = services.create_parcel(tenant_id=request.user.tenant_id, user=request.user, **data)
        return Response(ParcelSerializer(parcel).data, status=status.HTTP_201_CREATED)


class ParcelDetailView(ReferentialView):
    @extend_schema(responses={200: ParcelSerializer})
    def get(self, request, pk):
        return Response(ParcelSerializer(selectors.parcel_or_404(parcel_id=pk)).data)

    @extend_schema(request=ParcelSerializer, responses={200: ParcelSerializer})
    def patch(self, request, pk):
        parcel = selectors.parcel_or_404(parcel_id=pk)
        serializer = ParcelSerializer(parcel, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.update(_producer(data))
        parcel = services.update_parcel(tenant_id=request.user.tenant_id, user=request.user, parcel=parcel, **data)
        return Response(ParcelSerializer(parcel).data)


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
