from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from catalog.models import Article, Partner
from lots.models import Lot
from core.api import TenantAPIView
from lots import selectors, services
from lots.api.serializers import (
    ApprovalCreateSerializer,
    ApprovalDecisionSerializer,
    ApprovalSerializer,
    ApprovalStatusFilterSerializer,
    LotDetailSerializer,
    LotSerializer,
    ReasonSerializer,
    ReceptionSerializer,
    ShipmentSerializer,
    TraceLotSerializer,
    TraceQuerySerializer,
)
from tenants.models import User
from tenants.permissions import ApprovalPermission, BlockLotPermission, LotPermission, TraceabilityPermission


def _detail(lot_id):
    return LotDetailSerializer(selectors.lot_or_404(lot_id=lot_id)).data


class LotListView(TenantAPIView):
    permission_classes = [IsAuthenticated, LotPermission]

    @extend_schema(
        parameters=[OpenApiParameter("article", str), OpenApiParameter("status", str), OpenApiParameter("search", str)],
        responses={200: LotSerializer(many=True)},
    )
    def get(self, request):
        p = request.query_params
        qs = selectors.lots(article_id=p.get("article"), status=p.get("status"), search=p.get("search"))
        return Response(LotSerializer(qs[:500], many=True).data)


class LotDetailView(TenantAPIView):
    permission_classes = [IsAuthenticated, LotPermission]

    @extend_schema(responses={200: LotDetailSerializer})
    def get(self, request, pk):
        return Response(_detail(pk))


class ReceptionView(TenantAPIView):
    permission_classes = [IsAuthenticated, LotPermission]

    @extend_schema(request=ReceptionSerializer, responses={201: LotDetailSerializer})
    def post(self, request):
        serializer = ReceptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        # La RLS ne montre que les articles et partenaires du client : ceux d'un autre client sont « introuvables ».
        article = Article.objects.filter(pk=data.pop("article")).first()
        supplier = Partner.objects.filter(pk=data.pop("supplier")).first()
        if article is None or supplier is None:
            raise ValidationError({"article" if article is None else "supplier": ["Introuvable."]})
        lot = services.receive_lot(tenant_id=request.user.tenant_id, user=request.user, article=article,
                                   supplier=supplier, **data)
        return Response(_detail(lot.id), status=status.HTTP_201_CREATED)


class BlockLotView(TenantAPIView):
    permission_classes = [IsAuthenticated, BlockLotPermission]

    @extend_schema(request=ReasonSerializer, responses={200: LotDetailSerializer})
    def post(self, request, pk):
        lot = selectors.lot_or_404(lot_id=pk)
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.block_lot(tenant_id=request.user.tenant_id, user=request.user, lot_id=lot.id,
                           reason=serializer.validated_data["reason"])
        return Response(_detail(pk))


class ReverseMovementView(TenantAPIView):
    """Annulation par contre-mouvement. Admin, Qualite, Production : tout mouvement.
    Operateur : seulement ses propres saisies."""

    permission_classes = [IsAuthenticated, LotPermission]

    @extend_schema(request=ReasonSerializer, responses={201: LotDetailSerializer})
    def post(self, request, pk):
        movement = selectors.movement_or_404(movement_id=pk)
        if request.user.role == User.Role.OPERATEUR and movement.user_id != request.user.id:
            return Response({"detail": "Un opérateur ne peut annuler que ses propres saisies."}, status=403)
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reverse_movement(tenant_id=request.user.tenant_id, user=request.user, movement_id=movement.id,
                                  reason=serializer.validated_data["reason"])
        return Response(_detail(movement.lot_id), status=status.HTTP_201_CREATED)


def _origins(request):
    query = TraceQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    origins = selectors.find_origin_lots(lot_id=query.validated_data.get("lot"),
                                         search=query.validated_data.get("search"))
    if not origins:
        raise Http404
    return origins


class DownstreamView(TenantAPIView):
    """US-14 : du lot fournisseur vers les lots produits et les clients livres."""

    permission_classes = [IsAuthenticated, TraceabilityPermission]

    @extend_schema(parameters=[TraceQuerySerializer], responses={200: dict})
    def get(self, request):
        origins = _origins(request)
        found, shipments = selectors.downstream(origins=origins)
        return Response({
            "origins": LotSerializer(origins, many=True).data,
            "lots": TraceLotSerializer(found, many=True).data,
            "shipments": ShipmentSerializer(shipments, many=True).data,
        })


class UpstreamView(TenantAPIView):
    """US-15 : du lot fini vers les lots de matieres et leurs fournisseurs."""

    permission_classes = [IsAuthenticated, TraceabilityPermission]

    @extend_schema(parameters=[TraceQuerySerializer], responses={200: dict})
    def get(self, request):
        origins = _origins(request)
        return Response({
            "origins": LotSerializer(origins, many=True).data,
            "lots": TraceLotSerializer(selectors.upstream(origins=origins), many=True).data,
        })


# Double validation (US-20) -------------------------------------------------


class ApprovalListView(TenantAPIView):
    """Demandes de deblocage, destruction, rebut et ajustement. Les regles de role sont dans services.py."""

    permission_classes = [IsAuthenticated, ApprovalPermission]

    @extend_schema(parameters=[ApprovalStatusFilterSerializer], responses={200: ApprovalSerializer(many=True)})
    def get(self, request):
        filters = ApprovalStatusFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        qs = selectors.approval_requests(user=request.user, status=filters.validated_data.get("status"))
        return Response(ApprovalSerializer(qs[:500], many=True).data)

    @extend_schema(request=ApprovalCreateSerializer, responses={201: ApprovalSerializer})
    def post(self, request):
        serializer = ApprovalCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # Lot d'un autre client : invisible (RLS), donc « introuvable ».
        lot = Lot.objects.filter(pk=data["lot"]).first()
        if lot is None:
            raise ValidationError({"lot": ["Lot introuvable."]})
        req = services.request_approval(
            tenant_id=request.user.tenant_id, user=request.user, lot_id=lot.id, action=data["action"],
            reason=data["reason"], quantity=data.get("quantity"),
        )
        return Response(ApprovalSerializer(selectors.approval_or_404(user=request.user, request_id=req.id)).data,
                        status=status.HTTP_201_CREATED)


class ApprovalDetailView(TenantAPIView):
    permission_classes = [IsAuthenticated, ApprovalPermission]

    @extend_schema(responses={200: ApprovalSerializer})
    def get(self, request, pk):
        return Response(ApprovalSerializer(selectors.approval_or_404(user=request.user, request_id=pk)).data)


class _ApprovalDecisionView(TenantAPIView):
    permission_classes = [IsAuthenticated, ApprovalPermission]
    decide = None

    @extend_schema(request=ApprovalDecisionSerializer, responses={200: ApprovalSerializer})
    def post(self, request, pk):
        req = selectors.approval_or_404(user=request.user, request_id=pk)
        serializer = ApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        type(self).decide(request, req, serializer.validated_data["comment"])
        return Response(ApprovalSerializer(selectors.approval_or_404(user=request.user, request_id=pk)).data)


class ApproveView(_ApprovalDecisionView):
    @staticmethod
    def decide(request, req, comment):
        services.approve_request(tenant_id=request.user.tenant_id, user=request.user, request_id=req.id,
                                 comment=comment)


class RejectView(_ApprovalDecisionView):
    @staticmethod
    def decide(request, req, comment):
        services.reject_request(tenant_id=request.user.tenant_id, user=request.user, request_id=req.id,
                                comment=comment)


class CancelView(_ApprovalDecisionView):
    @staticmethod
    def decide(request, req, comment):
        services.cancel_request(tenant_id=request.user.tenant_id, user=request.user, request_id=req.id)
