import uuid

from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from catalog.models import Article, OrganicStatus, Parcel, Partner
from lots.models import Lot
from core.api import TenantAPIView
from lots import reasons, selectors, services
from lots.api.serializers import (
    ApprovalCreateSerializer,
    QualityCheckCreateSerializer,
    QualityCheckSerializer,
    RecallQuerySerializer,
    RecallShipmentSerializer,
    ApprovalSerializer,
    ApprovalStatusFilterSerializer,
    BlockSerializer,
    LotDetailSerializer,
    LotSerializer,
    ReceptionArticleSerializer,
    ReceptionRowSerializer,
    ReceptionSerializer,
    ReceptionSupplierSerializer,
    RejectSerializer,
    ReverseSerializer,
    ShipmentSerializer,
    TraceLotSerializer,
    TraceQuerySerializer,
)
from tenants.models import Site, User
from tenants.permissions import (
    ApprovalPermission, BlockLotPermission, LotPermission, QualityCheckPermission, ReceptionPermission,
    TraceabilityPermission,
)


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

    @extend_schema(responses={200: ReceptionRowSerializer(many=True)})
    def get(self, request):
        """Dernieres receptions (50). Un operateur ne voit que les siennes."""
        return Response(ReceptionRowSerializer(selectors.recent_receptions(user=request.user), many=True).data)

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
        site_id = data.pop("site", None)
        if site_id:
            data["site"] = Site.objects.filter(pk=site_id).first()
            if data["site"] is None:
                raise ValidationError({"site": ["Introuvable."]})
        parcel_id = data.pop("parcel", None)
        if parcel_id:
            data["parcel"] = Parcel.objects.filter(pk=parcel_id).first()
            if data["parcel"] is None:
                raise ValidationError({"parcel": ["Introuvable."]})
        lot = services.receive_lot(tenant_id=request.user.tenant_id, user=request.user, article=article,
                                   supplier=supplier, **data)
        return Response(_detail(lot.id), status=status.HTTP_201_CREATED)


class ReceptionOptionsView(TenantAPIView):
    """Listes de l'ecran de reception. Un operateur n'a pas acces aux referentiels : il recoit ici
    seulement ce qu'il faut pour enregistrer une livraison."""

    permission_classes = [IsAuthenticated, ReceptionPermission]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response({
            "articles": ReceptionArticleSerializer(selectors.reception_articles(), many=True).data,
            "suppliers": ReceptionSupplierSerializer(selectors.reception_suppliers(), many=True).data,
            "reception_reasons": reasons.as_options(reasons.RECEPTION),
            "reversal_reasons": reasons.as_options(reasons.REVERSAL),
            "late_reasons": reasons.as_options(reasons.LATE_ENTRY),
            "organic_statuses": [{"code": c, "label": label} for c, label in OrganicStatus.choices],
            "sites": [{"id": str(site.id), "name": site.name} for site in Site.objects.order_by("name")],
        })


class BlockLotView(TenantAPIView):
    permission_classes = [IsAuthenticated, BlockLotPermission]

    @extend_schema(request=BlockSerializer, responses={200: LotDetailSerializer})
    def post(self, request, pk):
        lot = selectors.lot_or_404(lot_id=pk)
        serializer = BlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.block_lot(tenant_id=request.user.tenant_id, user=request.user, lot_id=lot.id,
                           **serializer.validated_data)
        return Response(_detail(pk))


class ReverseMovementView(TenantAPIView):
    """Annulation par contre-mouvement. Admin, Qualite, Production : tout mouvement.
    Operateur : seulement ses propres saisies."""

    permission_classes = [IsAuthenticated, LotPermission]

    @extend_schema(request=ReverseSerializer, responses={201: LotDetailSerializer})
    def post(self, request, pk):
        movement = selectors.movement_or_404(movement_id=pk)
        if request.user.role == User.Role.OPERATEUR and movement.user_id != request.user.id:
            return Response({"detail": "Un opérateur ne peut annuler que ses propres saisies."}, status=403)
        serializer = ReverseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reverse_movement(tenant_id=request.user.tenant_id, user=request.user, movement_id=movement.id,
                                  **serializer.validated_data)
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


class RecallView(TenantAPIView):
    """Rapport de rappel depuis un carton, une palette (code de lot) ou un conteneur."""

    permission_classes = [IsAuthenticated, TraceabilityPermission]

    @extend_schema(parameters=[RecallQuerySerializer], responses={200: dict})
    def get(self, request):
        query = RecallQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        origins, container = selectors.find_recall_origins(search=query.validated_data["search"].strip())
        if not origins:
            raise Http404
        report = selectors.recall_report(origins=origins)
        from production.api.serializers import RunSerializer

        def lot_rows(found):
            rows = TraceLotSerializer(found, many=True).data
            for row in rows:
                check = report["quality"].get(uuid.UUID(row["id"]))
                row["last_quality_check"] = QualityCheckSerializer(check).data if check else None
            return rows

        roots = lot_rows(report["roots"])
        for row in roots:
            m = report["receptions"].get(uuid.UUID(row["id"]))
            row["received_quantity"] = str(m.quantity) if m else None
            row["received_at"] = m.occurred_at.isoformat() if m else None
        shipments = RecallShipmentSerializer(report["shipments"], many=True).data
        raw = [r for r in roots if r["article_type"] != "emballage"]
        return Response({
            "search": query.validated_data["search"],
            "container": container,
            "origins": lot_rows(report["origins"]),
            "contents": lot_rows(report["contents"]),
            "roots": roots,
            "affected": lot_rows(report["affected"]),
            "in_stock": lot_rows(report["in_stock"]),
            "runs": RunSerializer(report["runs"], many=True).data,
            "shipments": shipments,
            "summary": {
                "producers": len({r["supplier_name"] for r in raw if r["supplier_name"]}),
                "parcels": len({r["parcel_code"] for r in raw if r["parcel_code"]}),
                "affected_lots": len(report["affected"]),
                "lots_in_stock": len(report["in_stock"]),
                "customers": len({s["customer_name"] for s in shipments if s["customer_name"]}),
                "containers": len({s["container_number"] for s in shipments if s["container_number"]}),
            },
        })


class QualityCheckView(TenantAPIView):
    permission_classes = [IsAuthenticated, QualityCheckPermission]

    @extend_schema(request=QualityCheckCreateSerializer, responses={201: LotDetailSerializer})
    def post(self, request, pk):
        lot = selectors.lot_or_404(lot_id=pk)
        serializer = QualityCheckCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.record_quality_check(tenant_id=request.user.tenant_id, user=request.user, lot_id=lot.id,
                                      **serializer.validated_data)
        return Response(_detail(pk), status=status.HTTP_201_CREATED)


class QualityOptionsView(TenantAPIView):
    permission_classes = [IsAuthenticated, QualityCheckPermission]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response({
            "criteria": reasons.as_options(reasons.QUALITY_CRITERIA),
            "late_reasons": reasons.as_options(reasons.LATE_ENTRY),
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
            reason_code=data["reason_code"], comment=data["comment"], quantity=data.get("quantity"),
        )
        return Response(ApprovalSerializer(selectors.approval_or_404(user=request.user, request_id=req.id)).data,
                        status=status.HTTP_201_CREATED)


class ApprovalDetailView(TenantAPIView):
    permission_classes = [IsAuthenticated, ApprovalPermission]

    @extend_schema(responses={200: ApprovalSerializer})
    def get(self, request, pk):
        return Response(ApprovalSerializer(selectors.approval_or_404(user=request.user, request_id=pk)).data)


class ApprovalReasonsView(TenantAPIView):
    """Listes fermees des motifs, pour les menus deroulants de l'ecran."""

    permission_classes = [IsAuthenticated, ApprovalPermission]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response({
            "block": reasons.as_options(reasons.BLOCK),
            "reject": reasons.as_options(reasons.REJECT),
            "reception": reasons.as_options(reasons.RECEPTION),
            "reversal": reasons.as_options(reasons.REVERSAL),
            **{action: reasons.as_options(codes) for action, codes in reasons.APPROVAL.items()},
        })


class _ApprovalDecisionView(TenantAPIView):
    permission_classes = [IsAuthenticated, ApprovalPermission]
    body = None

    def post(self, request, pk):
        req = selectors.approval_or_404(user=request.user, request_id=pk)
        data = {}
        if self.body is not None:
            serializer = self.body(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
        self.decide(request, req, data)
        return Response(ApprovalSerializer(selectors.approval_or_404(user=request.user, request_id=pk)).data)


class ApproveView(_ApprovalDecisionView):
    @extend_schema(request=None, responses={200: ApprovalSerializer})
    def post(self, request, pk):
        return super().post(request, pk)

    def decide(self, request, req, data):
        services.approve_request(tenant_id=request.user.tenant_id, user=request.user, request_id=req.id)


class RejectView(_ApprovalDecisionView):
    body = RejectSerializer

    @extend_schema(request=RejectSerializer, responses={200: ApprovalSerializer})
    def post(self, request, pk):
        return super().post(request, pk)

    def decide(self, request, req, data):
        services.reject_request(tenant_id=request.user.tenant_id, user=request.user, request_id=req.id, **data)


class CancelView(_ApprovalDecisionView):
    @extend_schema(request=None, responses={200: ApprovalSerializer})
    def post(self, request, pk):
        return super().post(request, pk)

    def decide(self, request, req, data):
        services.cancel_request(tenant_id=request.user.tenant_id, user=request.user, request_id=req.id)
