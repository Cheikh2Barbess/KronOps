"""Lectures de la production et du bilan matiere. La RLS de PostgreSQL filtre par client."""

from collections import OrderedDict
from decimal import Decimal

from django.db.models import Prefetch, Q
from django.http import Http404

from lots import selectors as lot_selectors
from lots import services as lot_services
from lots.models import Lot, LotLink, Movement
from production.models import Equipment, ProductionInput, ProductionRun
from production.services import yield_status

PCT = Decimal("0.01")


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
