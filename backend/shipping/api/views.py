from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from catalog.models import Partner
from core.api import TenantAPIView
from lots import reasons as lot_reasons
from lots import selectors as lot_selectors
from lots import services as lot_services
from lots.models import Lot
from production.api.serializers import AvailableLotSerializer
from shipping import selectors, services
from shipping.api.serializers import ShipmentCreateSerializer, ShipmentSerializer
from tenants.models import Site
from tenants.permissions import ShippingPermission


class ShipmentListView(TenantAPIView):
    permission_classes = [IsAuthenticated, ShippingPermission]

    @extend_schema(responses={200: ShipmentSerializer(many=True)})
    def get(self, request):
        """Dernieres expeditions (100). Filtre : ?container=MSCU..."""
        qs = selectors.shipments(container=request.query_params.get("container"))
        return Response(ShipmentSerializer(qs[:100], many=True).data)

    @extend_schema(request=ShipmentCreateSerializer, responses={201: ShipmentSerializer})
    def post(self, request):
        serializer = ShipmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        customer = Partner.objects.filter(pk=data.pop("customer")).first()
        if customer is None:
            raise ValidationError({"customer": ["Introuvable."]})
        site_id = data.pop("site", None)
        site = Site.objects.filter(pk=site_id).first() if site_id else None
        if site_id and site is None:
            raise ValidationError({"site": ["Introuvable."]})
        rows = data.pop("lines")
        found = {lot.id: lot for lot in Lot.objects.select_related("article").filter(pk__in=[r["lot"] for r in rows])}
        if len(found) != len({r["lot"] for r in rows}):
            raise ValidationError({"lines": ["Lot introuvable."]})
        shipment = services.create_shipment(
            tenant_id=request.user.tenant_id, user=request.user, customer=customer, site=site,
            lines=[(found[r["lot"]], r["quantity"], r["unit"] or None) for r in rows], **data,
        )
        return Response(ShipmentSerializer(selectors.shipment_or_404(shipment_id=shipment.id)).data,
                        status=status.HTTP_201_CREATED)


class ShipmentDetailView(TenantAPIView):
    permission_classes = [IsAuthenticated, ShippingPermission]

    @extend_schema(responses={200: ShipmentSerializer})
    def get(self, request, pk):
        return Response(ShipmentSerializer(selectors.shipment_or_404(shipment_id=pk)).data)


class ShipmentOptionsView(TenantAPIView):
    """Listes de l'ecran d'expedition : clients, sites, lots expediables (avec leur dernier controle qualite)."""

    permission_classes = [IsAuthenticated, ShippingPermission]

    @extend_schema(responses={200: dict})
    def get(self, request):
        lots = [
            lot for lot in lot_selectors.lots(status=Lot.Status.DISPONIBLE).filter(balance__gt=0)
            .exclude(article__article_type="matiere").exclude(article__article_type="emballage")
            if not lot_services.is_expired(lot)
        ]
        checks = lot_selectors.last_quality_checks([lot.id for lot in lots])
        rows = AvailableLotSerializer(lots, many=True).data
        for row, lot in zip(rows, lots):
            check = checks.get(lot.id)
            row["quality_result"] = check.result if check else None
            row["conversions"] = [{"unit_name": c.unit_name, "factor": c.factor} for c in lot.article.conversions.all()]
        customers = Partner.objects.filter(is_customer=True, is_active=True).order_by("name")
        return Response({
            "customers": [{"id": str(c.id), "name": c.name, "city": c.city} for c in customers],
            "sites": [{"id": str(s.id), "name": s.name} for s in Site.objects.order_by("name")],
            "lots": rows,
            "late_reasons": lot_reasons.as_options(lot_reasons.LATE_ENTRY),
        })
