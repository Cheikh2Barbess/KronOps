from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from catalog.models import Article, UnitConversion
from core.api import TenantAPIView
from lots import reasons as lot_reasons
from lots.models import Lot
from production import reasons, selectors, services
from production.api.serializers import (
    AvailableLotSerializer,
    BalanceFilterSerializer,
    EquipmentSerializer,
    RunCancelSerializer,
    RunCreateSerializer,
    RouteSerializer,
    RouteWriteSerializer,
    RunSerializer,
    StepConfigureSerializer,
    StepSettingSerializer,
    StepTotalSerializer,
)
from production.models import Equipment, ProductionRun
from tenants.models import Site
from tenants.permissions import (
    IsTenantAdmin,
    MaterialBalancePermission,
    ProductionPermission,
    ReferentialPermission,
    RunCancelPermission,
)


def _site(site_id):
    """Site designe par son identifiant : la RLS rend « introuvable » celui d'un autre client."""
    if not site_id:
        return None
    site = Site.objects.filter(pk=site_id).first()
    if site is None:
        raise ValidationError({"site": ["Introuvable."]})
    return site


class EquipmentListView(TenantAPIView):
    permission_classes = [IsAuthenticated, ReferentialPermission]

    @extend_schema(responses={200: EquipmentSerializer(many=True)})
    def get(self, request):
        return Response(EquipmentSerializer(selectors.equipment_list(), many=True).data)

    @extend_schema(request=EquipmentSerializer, responses={201: EquipmentSerializer})
    def post(self, request):
        serializer = EquipmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data["site"] = _site(data.pop("site_id", None))
        equipment = services.create_equipment(tenant_id=request.user.tenant_id, user=request.user, **data)
        return Response(EquipmentSerializer(equipment).data, status=status.HTTP_201_CREATED)


class EquipmentDetailView(TenantAPIView):
    permission_classes = [IsAuthenticated, ReferentialPermission]

    @extend_schema(responses={200: EquipmentSerializer})
    def get(self, request, pk):
        return Response(EquipmentSerializer(selectors.equipment_or_404(equipment_id=pk)).data)

    @extend_schema(request=EquipmentSerializer, responses={200: EquipmentSerializer})
    def patch(self, request, pk):
        equipment = selectors.equipment_or_404(equipment_id=pk)
        serializer = EquipmentSerializer(equipment, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "site_id" in data:
            data["site"] = _site(data.pop("site_id"))
        equipment = services.update_equipment(tenant_id=request.user.tenant_id, user=request.user,
                                              equipment=equipment, **data)
        return Response(EquipmentSerializer(equipment).data)


class RunListView(TenantAPIView):
    permission_classes = [IsAuthenticated, ProductionPermission]

    @extend_schema(responses={200: RunSerializer(many=True)})
    def get(self, request):
        """Dernieres declarations (100)."""
        found = selectors.mark_cancellable([selectors.decorate(r) for r in selectors.runs()[:100]])
        return Response(RunSerializer(found, many=True).data)

    @extend_schema(request=RunCreateSerializer, responses={201: RunSerializer})
    def post(self, request):
        serializer = RunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        article = Article.objects.filter(pk=data.pop("output_article")).first()
        if article is None:
            raise ValidationError({"output_article": ["Introuvable."]})
        equipment_id = data.pop("equipment", None)
        equipment = Equipment.objects.filter(pk=equipment_id).first() if equipment_id else None
        if equipment_id and equipment is None:
            raise ValidationError({"equipment": ["Introuvable."]})
        rows = data.pop("inputs")
        found = {lot.id: lot for lot in Lot.objects.select_related("article").filter(pk__in=[r["lot"] for r in rows])}
        if len(found) != len({r["lot"] for r in rows}):
            raise ValidationError({"inputs": ["Lot introuvable."]})
        run = services.declare_run(
            tenant_id=request.user.tenant_id, user=request.user, output_article=article, equipment=equipment,
            site=_site(data.pop("site", None)), inputs=[(found[r["lot"]], r["quantity"]) for r in rows],
            output_unit=data.pop("output_unit") or None, **data,
        )
        return Response(RunSerializer(selectors.decorate(selectors.run_or_404(run_id=run.id))).data,
                        status=status.HTTP_201_CREATED)


class RunDetailView(TenantAPIView):
    permission_classes = [IsAuthenticated, ProductionPermission]

    @extend_schema(responses={200: RunSerializer})
    def get(self, request, pk):
        return Response(RunSerializer(selectors.decorate(selectors.run_or_404(run_id=pk))).data)


class RunCancelView(TenantAPIView):
    """Annuler une declaration (motif code). Le lot produit ne doit avoir servi a rien."""

    permission_classes = [IsAuthenticated, RunCancelPermission]

    @extend_schema(request=RunCancelSerializer, responses={200: RunSerializer})
    def post(self, request, pk):
        run = selectors.run_or_404(run_id=pk)
        serializer = RunCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.cancel_run(tenant_id=request.user.tenant_id, user=request.user, run_id=run.id,
                            **serializer.validated_data)
        return Response(RunSerializer(selectors.decorate(selectors.run_or_404(run_id=pk))).data)


class ProductionOptionsView(TenantAPIView):
    """Listes de l'ecran « Déclarer une étape » : etapes, equipements, lots disponibles, articles produits."""

    permission_classes = [IsAuthenticated, ProductionPermission]

    @extend_schema(responses={200: dict})
    def get(self, request):
        articles = (
            Article.objects.filter(is_active=True).exclude(article_type=Article.Type.EMBALLAGE)
            .prefetch_related(Prefetch("conversions", queryset=UnitConversion.objects.order_by("unit_name")))
            .order_by("article_type", "code")
        )
        routes = selectors.route_steps_by_article()
        available = selectors.production_options()
        lots = AvailableLotSerializer(available, many=True).data
        for lot, row in zip(available, lots):
            row["route_steps"] = (routes.get(lot.article_id) or {}).get("steps")
            row["route_id"] = (routes.get(lot.article_id) or {}).get("route_id")
        return Response({
            "steps": [{"code": s["code"], "label": s["label"]} for s in selectors.active_steps()],
            "routes": selectors.active_routes(),
            "equipment": EquipmentSerializer(selectors.equipment_list(active=True), many=True).data,
            "sites": [{"id": str(s.id), "name": s.name} for s in Site.objects.order_by("name")],
            "lots": lots,
            "output_articles": [
                {"id": str(a.id), "code": a.code, "name": a.name, "article_type": a.article_type,
                 "base_unit": a.base_unit, "yield_min_pct": a.yield_min_pct, "yield_max_pct": a.yield_max_pct,
                 "conversions": [{"unit_name": c.unit_name, "factor": c.factor} for c in a.conversions.all()],
                 "route_steps": (routes.get(a.id) or {}).get("steps"),
                 "route_id": (routes.get(a.id) or {}).get("route_id")}
                for a in articles
            ],
            "waste_reasons": lot_reasons.as_options(reasons.WASTE),
            "late_reasons": lot_reasons.as_options(lot_reasons.LATE_ENTRY),
            "cancel_reasons": lot_reasons.as_options(reasons.RUN_CANCEL),
        })


class MaterialBalanceView(TenantAPIView):
    """Bilan matiere : rendement de chaque declaration, ecarts signales, total par etape."""

    permission_classes = [IsAuthenticated, MaterialBalancePermission]

    @extend_schema(parameters=[BalanceFilterSerializer], responses={200: dict})
    def get(self, request):
        query = BalanceFilterSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        f = query.validated_data
        found, totals = selectors.material_balance(
            date_from=f.get("date_from"), date_to=f.get("date_to"), step=f.get("step"), site_id=f.get("site"),
        )
        return Response({
            "runs": RunSerializer(found, many=True).data,
            "totals": StepTotalSerializer(totals, many=True).data,
            "steps": [{"code": c, "label": label} for c, label in ProductionRun.Step.choices],
            "sites": [{"id": str(s.id), "name": s.name} for s in Site.objects.order_by("name")],
        })


class StepSettingsView(TenantAPIView):
    """Etapes de production de l'entreprise : lecture pour les roles des referentiels, reglage par l'Admin."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), ReferentialPermission()]
        return [IsAuthenticated(), IsTenantAdmin()]

    @extend_schema(responses={200: StepSettingSerializer(many=True)})
    def get(self, request):
        return Response(StepSettingSerializer(selectors.step_catalog(), many=True).data)

    @extend_schema(request=StepConfigureSerializer, responses={200: StepSettingSerializer(many=True)})
    def put(self, request):
        serializer = StepConfigureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.configure_steps(tenant_id=request.user.tenant_id, user=request.user,
                                 steps=serializer.validated_data["steps"])
        return Response(StepSettingSerializer(selectors.step_catalog(), many=True).data)


def _route_articles(ids):
    """Articles designes par leurs identifiants : la RLS rend introuvables ceux d'un autre client."""
    found = list(Article.objects.filter(pk__in=ids))
    if len(found) != len(set(ids)):
        raise ValidationError({"articles": ["Article introuvable."]})
    return found


class RouteListView(TenantAPIView):
    """Parcours par produit : lecture pour les roles des referentiels, creation par l'Admin."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), ReferentialPermission()]
        return [IsAuthenticated(), IsTenantAdmin()]

    @extend_schema(responses={200: RouteSerializer(many=True)})
    def get(self, request):
        return Response(RouteSerializer(selectors.routes(), many=True).data)

    @extend_schema(request=RouteWriteSerializer, responses={201: RouteSerializer})
    def post(self, request):
        serializer = RouteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data["articles"] = _route_articles(data["articles"])
        route = services.create_route(tenant_id=request.user.tenant_id, user=request.user, **data)
        return Response(RouteSerializer(selectors.route_or_404(route_id=route.id)).data,
                        status=status.HTTP_201_CREATED)


class RouteDetailView(TenantAPIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), ReferentialPermission()]
        return [IsAuthenticated(), IsTenantAdmin()]

    @extend_schema(responses={200: RouteSerializer})
    def get(self, request, pk):
        return Response(RouteSerializer(selectors.route_or_404(route_id=pk)).data)

    @extend_schema(request=RouteWriteSerializer, responses={200: RouteSerializer})
    def put(self, request, pk):
        route = selectors.route_or_404(route_id=pk)
        serializer = RouteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data["articles"] = _route_articles(data["articles"])
        services.update_route(tenant_id=request.user.tenant_id, user=request.user, route=route, **data)
        return Response(RouteSerializer(selectors.route_or_404(route_id=pk)).data)


class PipelineView(TenantAPIView):
    """Pipeline en 8 blocs : lecture pour tous les roles (l'accueil masque les ecrans desactives), reglage Admin."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), ProductionPermission()]
        return [IsAuthenticated(), IsTenantAdmin()]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response(selectors.pipeline())

    @extend_schema(request=StepConfigureSerializer, responses={200: dict})
    def put(self, request):
        serializer = StepConfigureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.configure_pipeline(tenant_id=request.user.tenant_id, user=request.user,
                                    steps=serializer.validated_data["steps"])
        return Response(selectors.pipeline())
