"""Lectures des lots et recherches de tracabilite. La RLS de PostgreSQL filtre par client."""

from decimal import Decimal

from django.db import connection
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import Http404

from lots.models import Lot, Movement

ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=18, decimal_places=3))
# Garde-fou contre une boucle de genealogie (ne devrait jamais arriver).
MAX_DEPTH = 20


def lots(*, article_id=None, status=None, search=None):
    qs = (
        Lot.objects.select_related("article", "supplier")
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
