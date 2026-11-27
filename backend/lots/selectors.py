"""Lectures des lots et recherches de tracabilite. La RLS de PostgreSQL filtre par client."""

from decimal import Decimal

from django.db import connection
from django.db.models import (
    BooleanField, Case, Count, DecimalField, Exists, IntegerField, OuterRef, Prefetch, Q, Subquery, Sum, Value, When,
)
from django.db.models.functions import Coalesce
from django.http import Http404

from catalog.models import Article, Parcel, Partner
from lots.models import ApprovalRequest, Lot, LotLink, Movement
from tenants.models import User

ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=18, decimal_places=3))
# Garde-fou contre une boucle de genealogie (ne devrait jamais arriver).
MAX_DEPTH = 20


def lots(*, article_id=None, status=None, search=None):
    qs = (
        Lot.objects.select_related("article", "supplier", "parcel", "site")
        .annotate(balance=Coalesce(Sum("movements__quantity"), ZERO))
        .order_by("-created_at")
    )
    if article_id:
        qs = qs.filter(article_id=article_id)
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(Q(code__icontains=search) | Q(supplier_lot_code__icontains=search))
    return qs


def lot_or_404(*, lot_id):
    lot = lots().filter(pk=lot_id).first()
    if lot is None:  # inexistant OU appartenant a un autre client
        raise Http404
    return lot


def lot_balance(lot_id):
    return Movement.objects.filter(lot_id=lot_id).aggregate(total=Coalesce(Sum("quantity"), ZERO))["total"]


def movements_of(*, lot):
    return Movement.objects.filter(lot=lot).select_related("user", "partner").order_by("created_at", "id")


def movement_or_404(*, movement_id):
    movement = Movement.objects.select_related("lot").filter(pk=movement_id).first()
    if movement is None:
        raise Http404
    return movement


def find_origin_lots(*, lot_id=None, search=None):
    """Lot(s) de depart d'une recherche : par identifiant, ou par code interne / n° de lot fournisseur exact."""
    if lot_id:
        return list(lots().filter(pk=lot_id))
    return list(lots().filter(Q(code__iexact=search) | Q(supplier_lot_code__iexact=search)))


def _related_lot_ids(origin_ids, direction):
    """Requete recursive sur LotLink. direction = 'down' (enfants) ou 'up' (parents)."""
    start, follow = ("parent_lot_id", "child_lot_id") if direction == "down" else ("child_lot_id", "parent_lot_id")
    sql = f"""
        WITH RECURSIVE related(lot_id, depth) AS (
            SELECT {follow}, 1 FROM lots_lotlink WHERE {start} = ANY(%s::uuid[])
            UNION
            SELECT l.{follow}, r.depth + 1
            FROM lots_lotlink l JOIN related r ON l.{start} = r.lot_id
            WHERE r.depth < %s
        )
        SELECT lot_id, MIN(depth) FROM related GROUP BY lot_id
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [[str(i) for i in origin_ids], MAX_DEPTH])
        return {row[0]: row[1] for row in cursor.fetchall()}


def downstream(*, origins):
    """US-14 : lots produits a partir des lots d'origine, puis expeditions (clients, quantites, dates)."""
    depths = _related_lot_ids([o.id for o in origins], "down")
    found = list(lots().filter(pk__in=depths.keys()))
    for lot in found:
        lot.depth = depths[lot.id]
    all_ids = [o.id for o in origins] + [lot.id for lot in found]
    shipments = (
        Movement.objects.filter(lot_id__in=all_ids, movement_type=Movement.Type.EXPEDITION, reversed_by__isnull=True)
        .select_related("lot", "partner")
        .order_by("occurred_at")
    )
    return found, list(shipments)


def upstream(*, origins):
    """US-15 : lots de matieres entres dans les lots d'origine, avec leurs fournisseurs."""
    depths = _related_lot_ids([o.id for o in origins], "up")
    found = list(lots().filter(pk__in=depths.keys()))
    for lot in found:
        lot.depth = depths[lot.id]
    return found


def approval_requests(*, user, status=None):
    """Demandes de double validation. Un operateur ne voit que les siennes."""
    qs = ApprovalRequest.objects.select_related("lot__article", "requested_by", "decided_by").order_by("-created_at")
    if user.role == User.Role.OPERATEUR:
        qs = qs.filter(requested_by=user)
    if status:
        qs = qs.filter(status=status)
    return qs


def approval_or_404(*, user, request_id):
    req = approval_requests(user=user).filter(pk=request_id).first()
    if req is None:
        raise Http404
    return req


# Ecran de reception ---------------------------------------------------------


def reception_articles():
    """Articles actifs, avec leurs conditionnements, pour la liste deroulante de l'ecran de reception."""
    return Article.objects.filter(is_active=True).prefetch_related("conversions").order_by("article_type", "code")


def reception_suppliers():
    active = Parcel.objects.filter(is_active=True).order_by("code")
    return (
        Partner.objects.filter(is_supplier=True, is_active=True)
        .prefetch_related(Prefetch("parcels", queryset=active, to_attr="active_parcels"))
        .order_by("name")
    )


def recent_receptions(*, user, limit=50):
    """Dernieres receptions. Un operateur ne voit que les siennes, les seules qu'il peut annuler.

    `can_reverse` reprend les regles de services.reverse_movement : pas deja annulee, lot ni detruit ni
    utilise depuis (aucun autre mouvement, aucun lot fabrique a partir de lui).
    """
    others = (
        Movement.objects.filter(lot_id=OuterRef("lot_id")).exclude(pk=OuterRef("pk"))
        .values("lot_id").annotate(n=Count("id")).values("n")
    )
    reversal = Movement.objects.filter(reverses=OuterRef("pk"))
    qs = (
        Movement.objects.filter(movement_type=Movement.Type.RECEPTION)
        .select_related("lot__article", "lot__parcel", "partner", "user")
        .annotate(
            other_movements=Coalesce(Subquery(others, output_field=IntegerField()), 0),
            reversed=Exists(reversal),
            reversal_reason=Subquery(reversal.values("reason")[:1]),
            used_in_production=Exists(LotLink.objects.filter(parent_lot_id=OuterRef("lot_id"))),
        )
        .annotate(can_reverse=Case(
            When(Q(reversed=False, other_movements=0, used_in_production=False) & ~Q(lot__status=Lot.Status.DETRUIT),
                 then=Value(True)),
            default=Value(False), output_field=BooleanField(),
        ))
        .order_by("-created_at", "-id")
    )
    if user.role == User.Role.OPERATEUR:
        qs = qs.filter(user=user)
    return qs[:limit]


# Rapport de rappel ------------------------------------------------------------


def find_recall_origins(*, search):
    """Point de depart d'un rappel : un code de lot (carton, palette), un n° de lot fournisseur, ou un n° de
    conteneur (tous les lots charges dedans)."""
    from shipping.models import ShipmentLine
    from shipping.services import normalize_container

    found = find_origin_lots(search=search)
    if found:
        return found, None
    container = normalize_container(search)
    lot_ids = list(
        ShipmentLine.objects.filter(shipment__container_number=container).values_list("lot_id", flat=True)
    ) if container else []
    return list(lots().filter(pk__in=lot_ids)), (container if lot_ids else None)


def last_quality_checks(lot_ids):
    from lots.models import QualityCheck

    latest = {}
    for check in QualityCheck.objects.filter(lot_id__in=lot_ids).order_by("lot_id", "-checked_at", "-created_at"):
        latest.setdefault(check.lot_id, check)
    return latest


def recall_report(*, origins):
    """Rappel depuis un carton, une palette ou un conteneur.

    1. Contenu : de quoi sont faits les lots de depart (remontee jusqu'aux receptions, parcelles, producteurs).
    2. Perimetre : tout ce qui a ete fabrique avec les memes matieres d'origine (le rappel prudent).
    3. Ou c'est : stock a bloquer, et expeditions (client, conteneur, document d'export).
    """
    from production.selectors import runs_using_lots
    from shipping.models import ShipmentLine

    contents = upstream(origins=origins)
    known = {lot.id: lot for lot in [*origins, *contents]}
    with_parents = set(LotLink.objects.filter(child_lot_id__in=known.keys()).values_list("child_lot_id", flat=True))
    roots = [lot for lot in known.values() if lot.id not in with_parents]
    # Les emballages restent dans le contenu, mais n'elargissent pas le perimetre (un lot de cartons vides
    # touche toutes les productions de la saison).
    scope = [lot for lot in roots if lot.article.article_type != Article.Type.EMBALLAGE]
    derived, _ = downstream(origins=scope)
    affected = {lot.id: lot for lot in [*scope, *derived]}
    for lot in [*origins, *contents]:
        if lot.article.article_type != Article.Type.EMBALLAGE:
            affected.setdefault(lot.id, lot)
    ids = list(affected.keys())

    movements = (
        Movement.objects.filter(lot_id__in=ids, movement_type=Movement.Type.EXPEDITION, reversed_by__isnull=True)
        .select_related("lot__article", "partner").order_by("occurred_at")
    )
    lines = {
        line.movement_id: line.shipment
        for line in ShipmentLine.objects.filter(movement__in=movements).select_related("shipment")
    }
    shipments = [(m, lines.get(m.id)) for m in movements]
    receptions = {
        m.lot_id: m for m in Movement.objects.filter(lot_id__in=[r.id for r in roots],
                                                     movement_type=Movement.Type.RECEPTION)
    }
    in_stock = [lot for lot in affected.values() if lot.balance > 0 and lot.status != Lot.Status.DETRUIT]
    return {
        "origins": origins,
        "contents": sorted(contents, key=lambda lot: (lot.depth, lot.code)),
        "roots": sorted(roots, key=lambda lot: lot.code),
        "receptions": receptions,
        "affected": sorted(affected.values(), key=lambda lot: lot.code),
        "in_stock": sorted(in_stock, key=lambda lot: lot.code),
        "runs": sorted(runs_using_lots(ids), key=lambda r: r.ended_at),
        "shipments": shipments,
        "quality": last_quality_checks(ids),
    }
