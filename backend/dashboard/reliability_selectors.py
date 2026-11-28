"""Matieres et fiabilite des chiffres : couverture matiere, pannes (MTTR, MTBF), producteurs, derniere saisie par
tuile et qualite des donnees.

Meme regle que les autres tuiles : chaque chiffre vient d'une saisie, et ce qui ne se mesure pas le dit.
"""

import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import F

from catalog.models import Article, Partner
from dashboard.indicators import BAD, INFO, OK, WARN, worst
from dashboard.product_selectors import _fmt
from lots import selectors as lot_selectors
from lots.models import ApprovalRequest, Lot, Movement, QualityCheck
from production import reasons as production_reasons
from production import selectors as production_selectors
from production.models import LineStop, ProductionRun
from shipping.models import Shipment

COVERAGE_WINDOW_DAYS = 14
DUPLICATE_MINUTES = 30
FORGOTTEN_STOP_HOURS = 24
FUTURE_TOLERANCE = datetime.timedelta(minutes=5)
H = Decimal(3600)
UNITS = {"kg": "kg", "l": "L", "unite": "unités"}


def _name(user):
    return (user.get_full_name() or user.username) if user else None


# Derniere saisie ----------------------------------------------------------------------------------------------------

# Saisies qui nourrissent chaque tuile. La plus recente est affichee sur la tuile (quand, par qui, quoi).
SOURCES = {
    "reception": ("Réception", lambda: Movement.objects.filter(movement_type=Movement.Type.RECEPTION), "user"),
    "movement": ("Mouvement de stock", lambda: Movement.objects.all(), "user"),
    "run": ("Déclaration d'étape", lambda: ProductionRun.objects.all(), "user"),
    "qc": ("Contrôle qualité", lambda: QualityCheck.objects.all(), "user"),
    "stop": ("Arrêt de ligne", lambda: LineStop.objects.all(), "user"),
    "shipment": ("Expédition", lambda: Shipment.objects.all(), "user"),
    "approval": ("Demande de validation", lambda: ApprovalRequest.objects.all(), "requested_by"),
    "action": ("Action", lambda: _actions(), "created_by"),
}
TILE_SOURCES = {
    "received": ["reception"], "organic": ["reception"], "reception_conformity": ["reception"],
    "suppliers": ["reception", "run"], "produced": ["run"], "yields": ["run"], "bottleneck": ["run"],
    "wip": ["run"], "runs": ["run"], "products": ["run"], "targets": ["run"], "shipped": ["shipment"],
    "qc": ["qc"], "moisture": ["qc"], "ready_without_qc": ["qc", "run"], "blocked": ["movement", "qc"],
    "stock": ["movement"], "expiry": ["movement"], "coverage": ["movement"], "late_entries": ["movement", "run"],
    "my_entries": ["movement", "run"], "approvals": ["approval"], "line_stops": ["stop"], "mttr": ["stop"],
    "actions": ["action"], "alerts": ["action", "stop", "run"], "data_quality": ["movement", "stop"],
}


def _actions():
    from actions.models import Action

    return Action.objects.all()


def last_entries():
    """Derniere saisie de chaque source (une requete par source, pas par tuile)."""
    found = {}
    for key, (label, queryset, user_field) in SOURCES.items():
        row = queryset().select_related(user_field).order_by("-created_at").first()
        found[key] = None if row is None else {"at": row.created_at, "by": _name(getattr(row, user_field)),
                                                "what": label}
    return found


def last_entry_for(code, entries):
    rows = [entries[s] for s in TILE_SOURCES.get(code, []) if entries.get(s)]
    return max(rows, key=lambda r: r["at"]) if rows else None


# Couverture matiere ---------------------------------------------------------------------------------------------------

def tile_coverage(ctx):
    source = (f"Stock disponible des matières et emballages divisé par leur consommation moyenne des "
              f"{COVERAGE_WINDOW_DAYS} derniers jours (déclarations d'étape).")
    threshold = ctx.threshold("coverage_days")
    articles = list(Article.objects.filter(is_active=True, article_type__in=[Article.Type.MATIERE,
                                                                               Article.Type.EMBALLAGE]).order_by("name"))
    stock = defaultdict(Decimal)
    for lot in lot_selectors.lots().filter(balance__gt=0, status=Lot.Status.DISPONIBLE,
                                           article__in=articles):
        stock[lot.article_id] += lot.balance
    since = ctx.now - datetime.timedelta(days=COVERAGE_WINDOW_DAYS)
    used = defaultdict(Decimal)
    for article_id, quantity in Movement.objects.filter(
            movement_type=Movement.Type.CONSOMMATION, occurred_at__gte=since, occurred_at__lte=ctx.now,
            reversed_by__isnull=True, lot__article__in=articles).values_list("lot__article_id", "quantity"):
        used[article_id] -= quantity
    rows, rated = [], []
    for a in articles:
        if not stock[a.id] and not used[a.id]:
            continue
        unit = UNITS.get(a.base_unit, a.base_unit)
        daily = used[a.id] / COVERAGE_WINDOW_DAYS if used[a.id] > 0 else None
        if daily is None:
            rows.append([a.name, _fmt(stock[a.id], unit), "Aucune", _cell(ctx, "Pas de consommation", INFO), ""])
            continue
        days = stock[a.id] / daily
        status = ctx.status("coverage_days", days)
        rated.append((days, a, status))
        rupture = (ctx.today + datetime.timedelta(days=int(days))).strftime("%d/%m/%Y")
        rows.append([a.name, _fmt(stock[a.id], unit), _fmt(daily, unit),
                     _cell(ctx, f"{_fmt(days)} jours", status),
                     "Rupture aujourd'hui" if days < 1 else f"Vers le {rupture}"])
    if not rows:
        return ctx.tile("coverage", "Couverture matière", unit="jours", empty=True, scope="now", source=source,
                        threshold=threshold)
    if not rated:
        return ctx.tile("coverage", "Couverture matière", unit="jours", status=INFO, scope="now", source=source,
                        threshold=threshold, subtitle=f"Aucune consommation sur {COVERAGE_WINDOW_DAYS} jours",
                        detail=[_table("Couverture par matière", COLUMNS, rows)])
    days, article, _ = min(rated, key=lambda r: r[0])
    at_risk = [a.name for d, a, s in rated if s != OK]
    return ctx.tile(
        "coverage", "Couverture matière", value=float(round(days, 1)), unit="jours", value_label="au plus bas",
        status=worst([s for _, _, s in rated]), threshold=threshold, scope="now", source=source,
        subtitle=(f"Au plus bas : {article.name}. " + (f"Risque de rupture : {', '.join(at_risk)}" if at_risk else
                  f"Toutes les matières couvrent plus de {_fmt(threshold['green'])} jours")),
        detail=[_table("Couverture par matière", COLUMNS, rows)],
    )


COLUMNS = ["Matière", "Stock disponible", f"Consommé par jour ({COVERAGE_WINDOW_DAYS} j)", "Couverture",
           "Rupture estimée"]


def _cell(ctx, text, status):
    return {"text": text, "status": status}


def _table(title, columns, rows):
    return {"kind": "table", "title": title, "columns": columns, "rows": rows}


# Pannes : MTTR et MTBF ------------------------------------------------------------------------------------------------

def tile_mttr(ctx):
    source = ("Pannes déclarées et terminées (panne mécanique, panne électrique) sur la période. MTTR : durée moyenne "
              "d'une panne. MTBF : heures de marche déclarées divisées par le nombre de pannes.")
    threshold = ctx.threshold("mttr_hours")
    breakdowns = [production_selectors.decorate_stop(s, now=ctx.now)
                  for s in production_selectors.line_stops(start=ctx.start, end=ctx.now, include_cancelled=False)
                  .filter(ended_at__isnull=False, ended_at__gte=ctx.start,
                          cause_code__in=production_reasons.BREAKDOWNS)]
    if not breakdowns:
        return ctx.tile("mttr", "Pannes : temps de réparation", unit="h", status=OK, threshold=threshold,
                        source=source, value_label="aucune panne", subtitle="Aucune panne terminée sur la période")
    run_hours = defaultdict(Decimal)
    for r in ctx.runs:
        if r.equipment_id:
            run_hours[r.equipment_id] += Decimal((r.ended_at - r.started_at).total_seconds()) / H
    per_equipment, per_cause = defaultdict(list), defaultdict(list)
    for s in breakdowns:
        per_equipment[s.equipment].append(s.duration_hours)
        per_cause[s.cause_label].append(s.duration_hours)
    mttr = sum((s.duration_hours for s in breakdowns), Decimal("0")) / len(breakdowns)
    rows, bars = [], []
    for equipment, hours in sorted(per_equipment.items(), key=lambda e: -len(e[1])):
        mean = sum(hours, Decimal("0")) / len(hours)
        bars.append({"label": equipment.code, "value": float(round(mean, 2))})
        mtbf = run_hours[equipment.id] / len(hours) if run_hours[equipment.id] else None
        rows.append([f"{equipment.code} {equipment.name}", len(hours),
                     _cell(ctx, _fmt(mean, "h"), ctx.status("mttr_hours", mean)),
                     _fmt(mtbf, "h") if mtbf is not None else "Pas d'heure de marche déclarée"])
    return ctx.tile(
        "mttr", "Pannes : temps de réparation", value=float(round(mttr, 1)), unit="h", value_label="en moyenne (MTTR)",
        status=ctx.status("mttr_hours", mttr), threshold=threshold, source=source,
        subtitle=f"{len(breakdowns)} panne(s) sur {len(per_equipment)} équipement(s)",
        detail=[
            {"kind": "bars", "title": "Temps moyen de réparation par équipement", "unit": "h", "bars": bars},
            _table("Par équipement", ["Équipement", "Pannes", "MTTR", "MTBF"], rows),
            _table("Par cause", ["Cause", "Pannes", "Durée moyenne"],
                   [[c, len(h), _fmt(sum(h, Decimal("0")) / len(h), "h")] for c, h in per_cause.items()]),
        ],
    )


# Producteurs ----------------------------------------------------------------------------------------------------------

def tile_suppliers(ctx):
    source = ("Réceptions de la période par producteur (contrôle visuel), et rendement des déclarations d'étape qui "
              "consomment directement leurs lots (première transformation, au prorata des kilos de chaque producteur).")
    threshold = ctx.threshold("reception_conform_pct")
    if not ctx.receptions:
        return ctx.tile("suppliers", "Producteurs", unit="producteurs", empty=True, source=source, threshold=threshold)
    # Une ligne par producteur et par matiere : le rendement d'une premiere transformation depend de la matiere
    # (lavage de la mangue, rapage de la coco), il ne se compare qu'a matiere egale.
    stats = defaultdict(lambda: {"deliveries": 0, "kg": Decimal("0"), "rated": 0, "bad": 0, "in": Decimal("0"),
                                 "out": Decimal("0"), "steps": set()})
    articles = {}
    for m in ctx.receptions:
        if m.lot.supplier_id is None:
            continue
        key = (m.lot.supplier_id, m.lot.article_id)
        articles[m.lot.article_id] = m.lot.article
        row = stats[key]
        row["deliveries"] += 1
        row["kg"] += m.quantity
        if m.lot.reception_visual_ok is not None:
            row["rated"] += 1
            row["bad"] += m.lot.reception_visual_ok is False
    for r in ctx.runs:
        inputs = [i for i in r.inputs.all() if i.lot.article.article_type != Article.Type.EMBALLAGE]
        total = sum((i.quantity for i in inputs), Decimal("0"))
        if not total:
            continue
        for i in inputs:
            key = (i.lot.supplier_id, i.lot.article_id)
            if key in stats:
                stats[key]["in"] += i.quantity
                stats[key]["out"] += r.output_quantity * i.quantity / total
                stats[key]["steps"].add(r.get_step_display().lower())
    names = dict(Partner.objects.filter(pk__in={k[0] for k in stats}).values_list("id", "name"))
    rows, statuses = [], []
    for (supplier_id, article_id), s in sorted(stats.items(), key=lambda e: -e[1]["kg"]):
        article = articles[article_id]
        pct = (Decimal(s["rated"] - s["bad"]) * 100 / s["rated"]) if s["rated"] else None
        status = ctx.status("reception_conform_pct", pct) if pct is not None else INFO
        statuses.append(status)
        first = (f"{_fmt(s['out'] * 100 / s['in'], '%')} ({', '.join(sorted(s['steps']))})" if s["in"]
                 else "Pas encore transformé")
        rows.append([names.get(supplier_id, "Inconnu"), article.name, s["deliveries"],
                     _fmt(s["kg"], UNITS.get(article.base_unit, article.base_unit)),
                     _cell(ctx, f"{s['bad']} sur {s['rated']}" if s["rated"] else "Non contrôlé", status), first])
    suppliers = {r[0] for r in rows}
    bad = sorted({r[0] for r, st in zip(rows, statuses) if st == BAD})
    rated = sum(v["rated"] for v in stats.values())
    overall = Decimal(rated - sum(v["bad"] for v in stats.values())) * 100 / rated if rated else None
    return ctx.tile(
        "suppliers", "Producteurs", value=len(suppliers), unit="producteurs", value_label="ont livré",
        # Couleur de la tuile : conformite de toutes les livraisons (un seul refus ne met pas tout en rouge).
        status=ctx.status("reception_conform_pct", overall) if overall is not None else INFO, threshold=threshold,
        source=source,
        subtitle=f"En rouge : {', '.join(bad)}" if bad else "Aucun producteur en rouge",
        detail=[_table("Par producteur et par matière", ["Producteur", "Matière", "Livraisons", "Reçu",
                                                         "Non conformes", "1re transformation"],
                       rows)],
    )


# Qualite des donnees --------------------------------------------------------------------------------------------------

def _duplicates(ctx):
    pairs, last = [], {}
    for m in ctx.receptions:
        key = (m.lot.supplier_id, m.lot.article_id, m.quantity)
        before = last.get(key)
        if before is not None and m.occurred_at - before.occurred_at <= datetime.timedelta(minutes=DUPLICATE_MINUTES):
            pairs.append(f"{before.lot.code} et {m.lot.code}")
        last[key] = m
    return pairs


def tile_data_quality(ctx):
    source = ("Contrôles automatiques sur les saisies : ils signalent ce qui semble faux ou incomplet, sans rien "
              "modifier. À vérifier puis corriger (annulation et nouvelle saisie).")
    stops = [production_selectors.decorate_stop(s, now=ctx.now)
             for s in production_selectors.line_stops(start=ctx.start, end=ctx.now, include_cancelled=False)]
    forgotten = [s for s in stops if s.ongoing and s.duration_hours > FORGOTTEN_STOP_HOURS]
    other = [s for s in stops if s.cause_code == production_reasons.OTHER]
    no_parcel = [m for m in ctx.receptions if m.lot.article.article_type == Article.Type.MATIERE and not m.lot.parcel_id]
    future = list(Movement.objects.filter(created_at__gte=ctx.start,
                                          occurred_at__gt=F("created_at") + FUTURE_TOLERANCE).select_related("lot")[:20])
    not_kg = list(Article.objects.filter(is_active=True, article_type__in=[Article.Type.SEMI_FINI, Article.Type.FINI])
                  .exclude(base_unit=Article.Unit.KG).order_by("name"))
    checks = [
        ("Réceptions en double probables", _duplicates(ctx), WARN,
         f"Même producteur, même article, même quantité, à moins de {DUPLICATE_MINUTES} minutes d'écart"),
        ("Matière reçue sans parcelle", [m.lot.code for m in no_parcel], WARN,
         "La traçabilité s'arrête au producteur, sans la parcelle (exigence bio)"),
        (f"Arrêt en cours depuis plus de {FORGOTTEN_STOP_HOURS} h", [s.equipment.code for s in forgotten], WARN,
         "Probablement un arrêt oublié : la ligne est sans doute repartie"),
        ("Arrêts avec la cause « Autre »", [f"{s.equipment.code} : {s.comment}" for s in other], WARN,
         "Cause imprécise : à reclasser si une cause de la liste convient"),
        ("Dates de mouvement dans le futur", [m.lot.code for m in future], WARN,
         "Date réelle plus tard que l'heure de saisie"),
        ("Produits comptés hors kilos", [a.name for a in not_kg], INFO,
         "Normal pour un produit vendu à l'unité, mais il n'est pas additionné aux kilos des tuiles"),
    ]
    rows, todo = [], []
    for label, found, level, meaning in checks:
        rows.append([label, len(found), meaning, ", ".join(found[:3]) + (" ..." if len(found) > 3 else "")
                     if found else "Aucun"])
        todo += [[_cell(ctx, label, level), item] for item in found if level == WARN]
    rows.append(["Décalage d'horloge", "Sans objet",
                 "Non mesurable : aucune machine n'est connectée, toutes les heures viennent du serveur Tracalys", ""])
    issues = sum(len(found) for _, found, level, _ in checks if level == WARN)
    return ctx.tile(
        "data_quality", "Qualité des données", value=issues, unit="points", value_label="à vérifier",
        status=WARN if issues else OK, scope="period", source=source,
        subtitle="Aucun point à vérifier" if not issues else
        ", ".join(f"{label.lower()} ({len(found)})" for label, found, level, _ in checks if found and level == WARN),
        detail=[_table("À vérifier", ["Contrôle", "Saisie concernée"], todo),
                _table("Contrôles", ["Contrôle", "Nombre", "Ce que ça veut dire", "Exemples"], rows)],
    )
