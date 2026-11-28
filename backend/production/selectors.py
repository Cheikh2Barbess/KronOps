"""Lectures de la production et du bilan matiere. La RLS de PostgreSQL filtre par client."""

from collections import OrderedDict
from decimal import Decimal

from django.db.models import Prefetch, Q
from django.http import Http404
from django.utils import timezone

from lots import reasons as lot_reasons
from lots import selectors as lot_selectors
from lots import services as lot_services
from lots.models import Lot, LotLink, Movement
from production.models import (
    DEFAULT_ACTIVE_STEPS,
    Equipment,
    LineStop,
    PipelineSetting,
    ProductionInput,
    ProductionRun,
    ProductRoute,
    RouteArticle,
    RouteStep,
    StepSetting,
)
from production import reasons
from production.services import yield_status

PCT = Decimal("0.01")


def step_catalog():
    """Toutes les etapes du catalogue avec le reglage de l'entreprise : actives d'abord, dans l'ordre choisi.

    Une etape sans reglage garde son etat par defaut et sa place dans le catalogue.
    """
    settings = {s.step: s for s in StepSetting.objects.all()}
    catalog = list(ProductionRun.Step.choices)
    rows = []
    for index, (code, label) in enumerate(catalog):
        setting = settings.get(code)
        if setting is None:
            rows.append({"code": code, "label": label, "is_active": code in DEFAULT_ACTIVE_STEPS,
                         "position": index})
        else:
            rows.append({"code": code, "label": label, "is_active": setting.is_active, "position": setting.position})
    return sorted(rows, key=lambda r: (not r["is_active"], r["position"]))


def active_steps():
    """Etapes proposees a la declaration, dans l'ordre choisi par l'entreprise."""
    return [r for r in step_catalog() if r["is_active"]]


def step_order():
    """Code d'etape vers sa place dans la liste de l'entreprise (actives d'abord)."""
    return {r["code"]: i for i, r in enumerate(step_catalog())}


def routes():
    """Parcours de l'entreprise, avec leurs etapes (dans l'ordre du parcours) et leurs articles."""
    order = step_order()
    labels = dict(ProductionRun.Step.choices)
    found = list(
        ProductRoute.objects.prefetch_related(
            Prefetch("steps", queryset=RouteStep.objects.all()),
            Prefetch("articles", queryset=RouteArticle.objects.select_related("article").order_by("article__code")),
        ).order_by("name")
    )
    for route in found:
        codes = _ordered([(s.step, s.position) for s in route.steps.all()], order)
        route.step_rows = [{"code": c, "label": labels.get(c, c)} for c in codes]
        route.article_rows = [{"id": ra.article_id, "code": ra.article.code, "name": ra.article.name}
                              for ra in route.articles.all()]
    return found


def route_or_404(*, route_id):
    route = next((r for r in routes() if r.id == route_id), None)
    if route is None:
        raise Http404
    return route


def route_steps_by_article():
    """Article (id) vers les etapes permises par son parcours actif, dans l'ordre du parcours.

    Un article absent du resultat n'a pas de parcours actif : il suit les etapes de l'entreprise.
    """
    order = step_order()
    steps = {}
    for route_id, step, position in RouteStep.objects.filter(route__is_active=True).values_list(
        "route_id", "step", "position"
    ):
        steps.setdefault(route_id, []).append((step, position))
    result = {}
    for route_id, article_id, name in RouteArticle.objects.filter(route__is_active=True).values_list(
        "route_id", "article_id", "route__name"
    ):
        result[article_id] = {"route": name, "route_id": str(route_id),
                              "steps": _ordered(steps.get(route_id, []), order)}
    return result


def active_routes():
    """Parcours actifs et leurs etapes dans l'ordre du parcours (ecran de declaration)."""
    return [{"id": str(r.id), "name": r.name, "steps": [s["code"] for s in r.step_rows]}
            for r in routes() if r.is_active]


def _ordered(pairs, order):
    """Etapes (code, position) dans l'ordre du parcours. A egalite (anciennes lignes), ordre de l'entreprise."""
    return [c for c, _ in sorted(pairs, key=lambda p: (p[1], order.get(p[0], len(order))))]


def pipeline():
    """Les 8 blocs du pipeline et leurs etapes, avec l'etat pour l'entreprise et le verrou (non modifiable)."""
    from production.pipeline import BLOCKS, CATALOG, Kind

    production = {r["code"]: r for r in step_catalog()}
    modules = dict(PipelineSetting.objects.values_list("code", "is_active"))
    blocks = {n: {"number": n, "label": label, "steps": []} for n, label in BLOCKS}
    for item in CATALOG:
        row = {"code": item["code"], "kind": item["kind"], "kind_label": Kind(item["kind"]).label,
               "path": item.get("path"), "phase": item.get("phase")}
        if item["kind"] == Kind.TRANSFORMATION:
            step = production[item["code"]]
            row.update(label=step["label"], is_active=step["is_active"], locked=False)
        elif item["kind"] == Kind.MODULE:
            row.update(label=item["label"], is_active=modules.get(item["code"], True), locked=False)
        else:
            row.update(label=item["label"], is_active=item["kind"] == Kind.OBLIGATOIRE, locked=True)
        blocks[item["block"]]["steps"].append(row)
    return [blocks[n] for n, _ in BLOCKS]


def equipment_list(*, active=None, site_id=None):
    qs = Equipment.objects.select_related("site").order_by("code")
    if active is not None:
        qs = qs.filter(is_active=active)
    if site_id:
        qs = qs.filter(site_id=site_id)
    return qs


def equipment_or_404(*, equipment_id):
    equipment = equipment_list().filter(pk=equipment_id).first()
    if equipment is None:
        raise Http404
    return equipment


def runs(*, date_from=None, date_to=None, step=None, site_id=None, equipment_id=None, include_cancelled=True):
    inputs = ProductionInput.objects.select_related("lot__article", "lot__parcel").order_by("lot__code")
    qs = (
        ProductionRun.objects.select_related("equipment", "site", "output_lot__article", "user", "cancellation__user")
        .prefetch_related(Prefetch("inputs", queryset=inputs))
        .order_by("-ended_at", "-created_at")
    )
    if date_from:
        qs = qs.filter(ended_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(ended_at__date__lte=date_to)
    if step:
        qs = qs.filter(step=step)
    if site_id:
        qs = qs.filter(site_id=site_id)
    if equipment_id:
        qs = qs.filter(equipment_id=equipment_id)
    if not include_cancelled:
        qs = qs.filter(cancellation__isnull=True)
    return qs


def run_or_404(*, run_id):
    run = runs().filter(pk=run_id).first()
    if run is None:
        raise Http404
    return run


def decorate(run):
    """Ajoute rendement, ecart et saisie tardive, calcules (jamais stockes en double)."""
    run.yield_pct = (run.output_quantity * 100 / run.input_quantity).quantize(PCT) if run.input_quantity else None
    run.yield_status = yield_status(run)
    # Matiere qui n'est ni dans le produit ni dans les dechets declares : eau evaporee au sechage, ou perte
    # non expliquee aux autres etapes.
    run.unexplained_quantity = (
        run.input_quantity - run.output_quantity - run.waste_quantity if run.input_quantity else None
    )
    run.cancelled = getattr(run, "cancellation", None)  # RelatedObjectDoesNotExist herite d'AttributeError
    run.late = bool(run.late_reason_code) or lot_services.is_late(occurred_at=run.ended_at, created_at=run.created_at)
    return run


def material_balance(*, date_from=None, date_to=None, step=None, site_id=None):
    """Bilan matiere : chaque declaration avec son rendement, puis un total par etape.
    Les declarations annulees n'y entrent pas (leurs mouvements sont defaits)."""
    found = [decorate(r) for r in runs(date_from=date_from, date_to=date_to, step=step, site_id=site_id,
                                       include_cancelled=False)]
    totals = OrderedDict()
    for step_code, label in ProductionRun.Step.choices:
        rows = [r for r in found if r.step == step_code]
        if not rows:
            continue
        unit = rows[0].output_lot.article.base_unit
        same_unit = [r for r in rows if r.output_lot.article.base_unit == unit]
        inp = sum((r.input_quantity for r in same_unit), Decimal("0"))
        out = sum((r.output_quantity for r in same_unit), Decimal("0"))
        waste = sum((r.waste_quantity for r in same_unit), Decimal("0"))
        totals[step_code] = {
            "step": step_code, "step_label": label, "unit": unit, "runs": len(rows),
            "input_quantity": inp, "output_quantity": out, "waste_quantity": waste,
            "yield_pct": (out * 100 / inp).quantize(PCT) if inp else None,
            "deviations": sum(1 for r in rows if r.yield_status in ("bas", "haut")),
            "late_entries": sum(1 for r in rows if r.late),
        }
    return found, list(totals.values())


def production_options():
    """Ce qu'il faut pour declarer une etape : lots disponibles, articles produits, equipements."""
    available = [
        lot for lot in lot_selectors.lots(status=Lot.Status.DISPONIBLE).filter(balance__gt=0)
        if not lot_services.is_expired(lot)
    ]
    return available


def runs_using_lots(lot_ids):
    """Declarations qui ont produit l'un de ces lots (pour le rapport de rappel)."""
    return [decorate(r) for r in runs().filter(Q(output_lot_id__in=lot_ids))]


def mark_cancellable(found):
    """Une declaration s'annule tant que son lot produit n'a servi a rien (aucun autre mouvement, aucun enfant)."""
    ids = [r.output_lot_id for r in found]
    used = set(
        Movement.objects.filter(lot_id__in=ids).exclude(movement_type=Movement.Type.PRODUCTION)
        .values_list("lot_id", flat=True)
    ) | set(LotLink.objects.filter(parent_lot_id__in=ids).values_list("parent_lot_id", flat=True))
    for r in found:
        r.cancellable = r.cancelled is None and r.output_lot_id not in used
    return found


# Arrets de ligne ------------------------------------------------------------------


def line_stops(*, start=None, end=None, include_cancelled=True, equipment_id=None, site_id=None):
    """Arrets qui touchent la periode [start, end] (un arret en cours touche toujours le present)."""
    qs = LineStop.objects.select_related("equipment", "site", "user", "ended_by", "cancelled_by").order_by(
        "-started_at")
    if start is not None:
        qs = qs.filter(Q(ended_at__isnull=True) | Q(ended_at__gte=start))
    if end is not None:
        qs = qs.filter(started_at__lte=end)
    if not include_cancelled:
        qs = qs.filter(cancelled_at__isnull=True)
    if equipment_id:
        qs = qs.filter(equipment_id=equipment_id)
    if site_id:
        qs = qs.filter(site_id=site_id)
    return qs


def decorate_stop(stop, *, now=None, start=None, end=None):
    """Duree (en heures, bornee a la periode si elle est donnee), cause lisible, planifie ou non, en cours ou non."""
    now = now or timezone.now()
    stop.ongoing = stop.ended_at is None and stop.cancelled_at is None
    stop.planned = stop.cause_code in reasons.PLANNED_STOPS
    stop.cause_label = lot_reasons.text(reasons.STOP_CAUSES, stop.cause_code, stop.comment)
    finish = stop.ended_at or now
    begin = max(stop.started_at, start) if start else stop.started_at
    finish = min(finish, end) if end else finish
    stop.duration_hours = max(Decimal((finish - begin).total_seconds()) / Decimal(3600), Decimal("0"))
    stop.cancel_reason = (lot_reasons.text(reasons.STOP_CANCEL, stop.cancel_reason_code, stop.cancel_comment)
                          if stop.cancelled_at else "")
    return stop


def stop_or_404(*, stop_id):
    stop = line_stops().filter(pk=stop_id).first()
    if stop is None:
        raise Http404
    return decorate_stop(stop)


def product_names():
    """Article (id) vers le nom de son produit : le parcours ou il est rattache (« Mangue séchée »).

    Un article hors parcours est son propre produit (son nom).
    """
    return {a: name for a, name in RouteArticle.objects.values_list("article_id", "route__name")}
