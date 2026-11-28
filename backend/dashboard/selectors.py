"""Tableau de bord : indicateurs calcules a partir des donnees reellement saisies dans Tracalys.

Regle : aucun indicateur sans source. Chaque tuile dit d'ou vient son chiffre (`source`). Sans donnee sur la
periode, la tuile le dit (`empty`) au lieu d'afficher un zero trompeur.
La RLS de PostgreSQL limite toutes les lectures a l'entreprise connectee.

Chaque role a sa liste de tuiles (ROLE_TILES). Le detail (courbes, barres, tableaux) est envoye avec la tuile :
l'ecran l'affiche en plein ecran au clic.
"""

import datetime
from collections import OrderedDict, defaultdict
from decimal import Decimal
from functools import cached_property

from django.db.models import Min
from django.utils import timezone

from catalog.models import Article, OrganicStatus, Parcel
from dashboard import product_selectors
from dashboard.indicators import BAD, INFO, OK, STATUS_LABELS, THRESHOLDS, WARN, defaults, status_for, worst
from dashboard.models import DashboardThreshold
from lots import selectors as lot_selectors
from lots.models import ApprovalRequest, Lot, Movement, QualityCheck
from lots.reasons import QUALITY_CRITERIA
from production import selectors as production_selectors
from production.models import ProductionInput, ProductionRun
from shipping.models import Shipment
from tenants.models import User

PERIODS = (7, 30, 90, 365)
DEFAULT_DAYS = {User.Role.OPERATEUR: 7}
STEP_LABELS = dict(ProductionRun.Step.choices)
ORGANIC_LABELS = dict(OrganicStatus.choices)
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
RECEPTION = "reception"  # libelle de « l'etape » d'origine d'un lot recu

# Tuiles par role, dans l'ordre d'affichage. Le patron voit le global, la production le flux, la qualite les
# controles, l'operateur ce qu'il a a faire. Chaque tuile ne lit que des donnees ouvertes a ce role.
ROLE_TILES = {
    User.Role.ADMIN: ["targets", "products", "produced", "received", "shipped", "yields", "qc", "line_stops",
                      "bottleneck", "stock", "blocked", "approvals", "expiry", "organic", "reception_conformity"],
    User.Role.LECTURE: ["targets", "products", "produced", "received", "shipped", "yields", "qc", "line_stops",
                        "bottleneck", "stock", "blocked", "expiry", "organic", "reception_conformity"],
    User.Role.PRODUCTION: ["targets", "products", "line_stops", "runs", "bottleneck", "wip", "yields", "produced",
                           "received", "shipped", "blocked", "approvals", "expiry", "late_entries"],
    User.Role.QUALITE: ["products", "qc", "moisture", "ready_without_qc", "blocked", "approvals",
                        "reception_conformity", "organic", "expiry", "yields", "late_entries", "line_stops"],
    User.Role.OPERATEUR: ["wip", "my_entries", "line_stops", "received", "approvals", "blocked"],
}


def _num(value, places=1):
    if value is None:
        return None
    return float(round(Decimal(value), places))


def _hours(delta):
    return Decimal(delta.total_seconds()) / Decimal(3600)


def _pct(part, total):
    return Decimal(part) * 100 / Decimal(total) if total else None


def _local_date(dt):
    return timezone.localtime(dt).date()


def thresholds():
    """Seuils de l'entreprise : sa valeur si elle l'a reglee, sinon la valeur par defaut (marquee comme telle)."""
    rows = {r.code: r for r in DashboardThreshold.objects.all()}
    result = OrderedDict()
    for code, item in THRESHOLDS.items():
        green, red = defaults(code)
        row = rows.get(code)
        result[code] = {
            "code": code, "label": item["label"], "unit": item["unit"], "direction": item["direction"],
            "help": item["help"], "default_green": green, "default_red": red,
            "green": row.green if row else green, "red": row.red if row else red, "is_default": row is None,
        }
    return result


class Context:
    """Donnees communes aux tuiles, lues une seule fois par affichage."""

    def __init__(self, *, user, days, now=None):
        self.user, self.days = user, days
        self.now = now or timezone.now()
        self.today = timezone.localdate(self.now)
        self.start = self.now - datetime.timedelta(days=days)
        self.thresholds = thresholds()
        self.granularity = "day" if days <= 31 else "week" if days <= 120 else "month"
        self.buckets = self._buckets()

    @staticmethod
    def tile(*args, **kwargs):
        return _tile(*args, **kwargs)

    # Seuils et couleurs -------------------------------------------------------

    def status(self, code, value):
        t = self.thresholds[code]
        return status_for(value, direction=t["direction"], green=t["green"], red=t["red"])

    def threshold(self, code):
        t = self.thresholds[code]
        return {"code": code, "label": t["label"], "unit": t["unit"], "direction": t["direction"],
                "green": _num(t["green"], 2), "red": _num(t["red"], 2), "is_default": t["is_default"]}

    # Periodes des courbes ---------------------------------------------------------

    def bucket(self, day):
        if self.granularity == "day":
            return day.isoformat()
        if self.granularity == "week":
            year, week, _ = day.isocalendar()
            return f"{year}-S{week:02d}"
        return f"{day.year}-{day.month:02d}"

    def _buckets(self):
        keys = OrderedDict()
        day = _local_date(self.start)
        while day <= self.today:
            key = self.bucket(day)
            if key not in keys:
                if self.granularity == "day":
                    keys[key] = day.strftime("%d/%m")
                elif self.granularity == "week":
                    keys[key] = f"sem. {day.isocalendar()[1]}"
                else:
                    keys[key] = f"{MONTHS[day.month - 1]} {day.year % 100:02d}"
            day += datetime.timedelta(days=1)
        return keys

    def line(self, title, unit, values, *, kind="sum", bands=None):
        """Courbe : `values` = {nom de serie: {cle de periode: [valeurs]}}. Somme ou moyenne par periode."""
        series = []
        for name, by_key in values.items():
            points = []
            for key, label in self.buckets.items():
                found = by_key.get(key)
                if kind == "sum":
                    y = sum(found, Decimal("0")) if found else Decimal("0")
                else:
                    y = sum(found, Decimal("0")) / len(found) if found else None
                points.append({"x": label, "y": _num(y, 2)})
            row = {"name": name, "points": points}
            if bands and bands.get(name):
                row["band"] = bands[name]
            series.append(row)
        # `aggregate` dit a l'ecran comment lire la courbe : somme (kilos) ou moyenne (pourcentages, heures).
        return {"kind": "line", "title": title, "unit": unit, "series": series, "aggregate": kind}

    # Donnees ---------------------------------------------------------------------

    @cached_property
    def runs(self):
        found = production_selectors.runs(include_cancelled=False).filter(ended_at__gte=self.start, ended_at__lte=self.now)
        return [production_selectors.decorate(r) for r in found]

    @cached_property
    def receptions(self):
        """Receptions de matiere (hors emballages) sur la periode, sans les receptions annulees."""
        return list(
            Movement.objects.filter(movement_type=Movement.Type.RECEPTION, occurred_at__gte=self.start,
                                    occurred_at__lte=self.now,
                                    reversed_by__isnull=True)
            .exclude(lot__article__article_type=Article.Type.EMBALLAGE)
            .select_related("lot__article", "lot__parcel", "lot__supplier", "user")
            .order_by("occurred_at")
        )

    @cached_property
    def checks(self):
        return list(
            QualityCheck.objects.filter(checked_at__gte=self.start, checked_at__lte=self.now).select_related("lot__article")
            .order_by("checked_at")
        )

    @cached_property
    def shipments(self):
        return list(
            Shipment.objects.filter(shipped_at__gte=self.start, shipped_at__lte=self.now)
            .select_related("customer").prefetch_related("lines__lot__article", "lines__movement__reversed_by")
            .order_by("-shipped_at")
        )

    @cached_property
    def stock(self):
        """Lots disponibles ou bloques qui ont encore du stock, hors emballages (etat actuel)."""
        return list(
            lot_selectors.lots().filter(balance__gt=0, status__in=[Lot.Status.DISPONIBLE, Lot.Status.BLOQUE])
            .exclude(article__article_type=Article.Type.EMBALLAGE)
        )

    @cached_property
    def lot_ready_at(self):
        """Lot (id) vers l'heure ou il est devenu disponible : fin de l'etape qui l'a produit, sinon son entree."""
        ready = dict(ProductionRun.objects.values_list("output_lot_id", "ended_at"))
        entries = (
            Movement.objects.filter(movement_type__in=list(Movement.ENTRY_TYPES))
            .values("lot_id").annotate(first=Min("occurred_at"))
        )
        for row in entries:
            ready.setdefault(row["lot_id"], row["first"])
        return ready

    @cached_property
    def lot_origin_step(self):
        """Lot (id) vers l'etape qui l'a produit (absent = lot recu ou transfere)."""
        return dict(ProductionRun.objects.values_list("output_lot_id", "step"))

    @cached_property
    def step_order(self):
        return production_selectors.step_order()


def _tile(code, title, *, value=None, unit="", status=INFO, subtitle="", threshold=None, detail=(), empty=False,
          scope="period", source="", value_label=None):
    return {
        "code": code, "title": title, "value": value, "value_label": value_label, "unit": unit,
        "status": status, "status_label": STATUS_LABELS[status], "subtitle": subtitle, "threshold": threshold,
        "detail": list(detail), "empty": empty, "scope": scope, "source": source, "previous": None,
    }


def _table(title, columns, rows):
    return {"kind": "table", "title": title, "columns": columns, "rows": rows}


def _bars(title, unit, bars):
    return {"kind": "bars", "title": title, "unit": unit, "bars": bars}


def _cell(text, status=None):
    return {"text": text, "status": status} if status else text


def _fmt(value, unit=""):
    if value is None:
        return "Non renseigné"
    text = f"{Decimal(value):,.1f}".replace(",", " ").replace(".", ",")
    if text.endswith(",0"):
        text = text[:-2]
    return f"{text} {unit}".strip()


def _when(dt):
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M")


def _day(d):
    return d.strftime("%d/%m/%Y")


def _kg(lot):
    return lot.article.base_unit == Article.Unit.KG


# Tuiles ----------------------------------------------------------------------------


def tile_received(ctx):
    rows = [m for m in ctx.receptions if _kg(m.lot)]
    source = "Réceptions enregistrées (écran Réceptions), hors emballages et réceptions annulées."
    if not rows:
        return _tile("received", "Matière reçue", unit="kg", empty=True, source=source)
    total = sum((m.quantity for m in rows), Decimal("0"))
    by_article, by_status, by_producer = defaultdict(lambda: defaultdict(list)), defaultdict(Decimal), {}
    for m in rows:
        by_article[m.lot.article.name][ctx.bucket(_local_date(m.occurred_at))].append(m.quantity)
        by_status[m.lot.organic_status or ""] += m.quantity
        name = m.lot.supplier.name if m.lot.supplier else "Fournisseur non renseigné"
        p = by_producer.setdefault(name, {"kg": Decimal("0"), "n": 0, "parcels": set()})
        p["kg"] += m.quantity
        p["n"] += 1
        if m.lot.parcel:
            p["parcels"].add(m.lot.parcel.code)
    producers = sorted(by_producer.items(), key=lambda kv: -kv[1]["kg"])
    return _tile(
        "received", "Matière reçue", value=_num(total), unit="kg", source=source,
        subtitle=f"{len(rows)} livraison(s), {len(by_producer)} fournisseur(s)",
        detail=[
            ctx.line("Kilos reçus par période et par produit", "kg", by_article),
            _bars("Kilos reçus par statut bio", "kg",
                  [{"label": ORGANIC_LABELS.get(k, "Non renseigné"), "value": _num(v)} for k, v in by_status.items()]),
            _table("Kilos reçus par fournisseur", ["Fournisseur", "Parcelles", "Livraisons", "Kilos"],
                   [[n, ", ".join(sorted(p["parcels"])) or "Aucune", p["n"], _fmt(p["kg"], "kg")]
                    for n, p in producers]),
        ],
    )


def tile_produced(ctx):
    rows = [r for r in ctx.runs if r.step == ProductionRun.Step.SECHAGE and _kg(r.output_lot)]
    source = "Déclarations de l'étape Séchage (écran Production), hors déclarations annulées."
    if not rows:
        return _tile("produced", "Produit séché", unit="kg", empty=True, source=source)
    total = sum((r.output_quantity for r in rows), Decimal("0"))
    by_article, per_article, by_equipment = defaultdict(lambda: defaultdict(list)), defaultdict(Decimal), {}
    for r in rows:
        by_article[r.output_lot.article.name][ctx.bucket(_local_date(r.ended_at))].append(r.output_quantity)
        per_article[r.output_lot.article.name] += r.output_quantity
        name = r.equipment.code if r.equipment else "Sans équipement"
        e = by_equipment.setdefault(name, {"n": 0, "kg": Decimal("0"), "site": r.site.name if r.site else ""})
        e["n"] += 1
        e["kg"] += r.output_quantity
    return _tile(
        "produced", "Produit séché", value=_num(total), unit="kg", source=source,
        subtitle=", ".join(f"{name} {_fmt(kg, 'kg')}" for name, kg in sorted(per_article.items(), key=lambda kv: -kv[1])),
        detail=[
            ctx.line("Kilos séchés par période et par produit", "kg", by_article),
            _bars("Kilos séchés par produit", "kg", [{"label": k, "value": _num(v)} for k, v in per_article.items()]),
            _table("Par séchoir", ["Séchoir", "Site", "Déclarations", "Kilos séchés"],
                   [[k, v["site"] or "Aucun", v["n"], _fmt(v["kg"], "kg")] for k, v in sorted(by_equipment.items())]),
        ],
    )


def shipment_documents(shipment, lines):
    """Etat des documents d'une expedition : regle fixe, sans seuil.

    Rouge : produit bio ou en conversion sans certificat d'inspection (COI TRACES, reglement (UE) 2021/2306).
    Jaune : conteneur sans plomb, ou sans connaissement (BL). Vert : tout est saisi.
    """
    organic = any(line.lot.organic_status in (OrganicStatus.BIO, OrganicStatus.CONVERSION) for line in lines)
    if organic and not shipment.export_document_ref:
        return BAD, "Certificat d'inspection (COI) non saisi pour un produit bio"
    missing = []
    if shipment.container_number and not shipment.seal_number:
        missing.append("plomb")
    if not shipment.bill_of_lading:
        missing.append("connaissement (BL)")
    if missing:
        return WARN, "Non saisi : " + ", ".join(missing)
    return OK, "Documents saisis"


def tile_shipped(ctx):
    source = "Expéditions enregistrées (écran Expéditions), hors lignes annulées."
    found = []
    for s in ctx.shipments:
        lines = [line for line in s.lines.all() if not hasattr(line.movement, "reversed_by")]
        if lines:
            found.append((s, lines))
    if not found:
        return _tile("shipped", "Expédié", unit="kg", empty=True, source=source)
    total, by_bucket, rows, statuses = Decimal("0"), defaultdict(lambda: defaultdict(list)), [], []
    for s, lines in found:
        kg = sum((line.quantity for line in lines if _kg(line.lot)), Decimal("0"))
        total += kg
        by_bucket["Kilos expédiés"][ctx.bucket(_local_date(s.shipped_at))].append(kg)
        status, reason = shipment_documents(s, lines)
        statuses.append(status)
        rows.append([_when(s.shipped_at), s.container_number or "Sans conteneur", s.customer.name,
                     ", ".join(sorted({line.lot.article.name for line in lines})), _fmt(kg, "kg"),
                     _cell(reason, status)])
    containers = {s.container_number for s, _ in found if s.container_number}
    status = worst(statuses)
    late_docs = sum(1 for x in statuses if x != OK)
    return _tile(
        "shipped", "Expédié", value=_num(total), unit="kg", status=status, source=source,
        subtitle=f"{len(containers)} conteneur(s), {len({s.customer_id for s, _ in found})} client(s)"
        + (f", {late_docs} avec un document manquant" if late_docs else ", documents complets"),
        detail=[
            ctx.line("Kilos expédiés par période", "kg", by_bucket),
            _table("Expéditions et documents", ["Départ", "Conteneur", "Client", "Produits", "Kilos", "Documents"],
                   rows),
        ],
    )


def tile_yields(ctx):
    source = "Déclarations d'étape comparées à la fourchette de rendement de l'article (Référentiels)."
    rated = [r for r in ctx.runs if r.yield_status in ("conforme", "bas", "haut")]
    threshold = ctx.threshold("yield_in_range_pct")
    if not ctx.runs:
        return _tile("yields", "Rendements", unit="%", empty=True, source=source, threshold=threshold)
    in_range = sum(1 for r in rated if r.yield_status == "conforme")
    pct = _pct(in_range, len(rated))
    drying = [r for r in ctx.runs if r.step == ProductionRun.Step.SECHAGE and r.input_quantity]
    per_article, curve, bands = defaultdict(lambda: [Decimal("0"), Decimal("0")]), defaultdict(lambda: defaultdict(list)), {}
    for r in drying:
        article = r.output_lot.article
        per_article[article.name][0] += r.input_quantity
        per_article[article.name][1] += r.output_quantity
        curve[article.name][ctx.bucket(_local_date(r.ended_at))].append(r.yield_pct)
        if article.yield_min_pct is not None:
            bands[article.name] = {"min": _num(article.yield_min_pct, 2), "max": _num(article.yield_max_pct, 2)}
    parts = []
    for name, (inp, out) in per_article.items():
        if out:
            parts.append(f"{name} {_fmt(out * 100 / inp)} % ({_fmt(inp / out)} pour 1)")
    _, totals = production_selectors.material_balance(date_from=_local_date(ctx.start), date_to=_local_date(ctx.now))
    steps = []
    for t in totals:
        step_rated = [r for r in rated if r.step == t["step"]]
        st = OK if step_rated and t["deviations"] == 0 else BAD if t["deviations"] else None
        steps.append([t["step_label"], t["runs"], _fmt(t["input_quantity"], t["unit"]),
                      _fmt(t["output_quantity"], t["unit"]), _fmt(t["yield_pct"], "%") if t["yield_pct"] is not None else "Sans objet",
                      _cell(f"{t['deviations']} hors fourchette", st) if st else "Pas de fourchette"])
    outside = [r for r in rated if r.yield_status != "conforme"]
    status = ctx.status("yield_in_range_pct", pct) if pct is not None else INFO
    return _tile(
        "yields", "Rendements", value=_num(pct), unit="%", status=status, threshold=threshold, source=source,
        value_label="dans la fourchette" if pct is not None else "Aucune fourchette renseignée",
        subtitle=" · ".join(parts) if parts else f"{len(ctx.runs)} déclaration(s), aucune au séchage",
        detail=[
            # Une courbe par produit : chacun a son echelle (la coco seche a 50 %, la mangue a 6 %).
            *[ctx.line(f"Rendement du séchage, {name} (bande : fourchette de l'article)" if name in bands
                       else f"Rendement du séchage, {name} (pas de fourchette dans l'article)", "%", {name: curve[name]},
                       kind="mean", bands=bands) for name in sorted(curve)],
            _table("Par étape", ["Étape", "Déclarations", "Consommé", "Produit", "Rendement", "Écarts"], steps),
            _table("Déclarations hors fourchette", ["Fin", "Étape", "Équipement", "Lot produit", "Rendement", "Fourchette"],
                   [[_when(r.ended_at), STEP_LABELS[r.step], r.equipment.code if r.equipment else "Aucun",
                     r.output_lot.code, _cell(_fmt(r.yield_pct, "%"), BAD),
                     f"{_fmt(r.yield_min_pct)} à {_fmt(r.yield_max_pct)} %"] for r in outside]),
        ],
    )


def _failed_criteria(check):
    return [QUALITY_CRITERIA.get(code, code) for code, v in check.checks.items() if v == "nok"]


def tile_qc(ctx):
    source = "Contrôles qualité enregistrés (écran Contrôle qualité)."
    threshold = ctx.threshold("qc_conformity_pct")
    if not ctx.checks:
        return _tile("qc", "Contrôles qualité conformes", unit="%", empty=True, source=source, threshold=threshold)
    ok = [c for c in ctx.checks if c.result == QualityCheck.Result.CONFORME]
    pct = _pct(len(ok), len(ctx.checks))
    by_bucket = defaultdict(lambda: defaultdict(list))
    for c in ctx.checks:
        by_bucket["Conformes (%)"][ctx.bucket(_local_date(c.checked_at))].append(
            Decimal(100 if c.result == QualityCheck.Result.CONFORME else 0))
    bad = [c for c in ctx.checks if c.result != QualityCheck.Result.CONFORME]
    return _tile(
        "qc", "Contrôles qualité conformes", value=_num(pct), unit="%", threshold=threshold, source=source,
        status=ctx.status("qc_conformity_pct", pct),
        subtitle=f"{len(ctx.checks)} contrôle(s), {len(bad)} non conforme(s)",
        detail=[
            ctx.line("Part des contrôles conformes par période", "%", by_bucket, kind="mean"),
            _table("Contrôles non conformes", ["Date", "Lot", "Article", "Critères non conformes", "Humidité"],
                   [[_when(c.checked_at), c.lot.code, c.lot.article.name,
                     _cell(", ".join(_failed_criteria(c)) or "Aucun", BAD),
                     _fmt(c.moisture_pct, "%") if c.moisture_pct is not None else "Non mesurée"] for c in reversed(bad)]),
        ],
    )


def tile_moisture(ctx):
    source = "Humidité saisie au contrôle qualité. Le vert ou le rouge vient du critère « humidité » coché par la Qualité."
    measured = [c for c in ctx.checks if c.moisture_pct is not None]
    if not measured:
        return _tile("moisture", "Humidité mesurée", unit="%", empty=True, source=source)
    curve, per_article = defaultdict(lambda: defaultdict(list)), defaultdict(list)
    for c in measured:
        curve[c.lot.article.name][ctx.bucket(_local_date(c.checked_at))].append(c.moisture_pct)
        per_article[c.lot.article.name].append(c.moisture_pct)
    statuses = [BAD if c.checks.get("humidite") == "nok" else OK for c in measured]
    return _tile(
        "moisture", "Humidité mesurée", value=len(measured), unit="mesures", status=worst(statuses), source=source,
        subtitle=" · ".join(f"{name} : moyenne {_fmt(sum(v) / len(v), '%')}" for name, v in per_article.items()),
        detail=[
            ctx.line("Humidité moyenne par période et par produit", "%", curve, kind="mean"),
            _table("Dernières mesures", ["Date", "Lot", "Article", "Humidité", "Critère humidité"],
                   [[_when(c.checked_at), c.lot.code, c.lot.article.name, _fmt(c.moisture_pct, "%"),
                     _cell("Non conforme", BAD) if c.checks.get("humidite") == "nok" else _cell("Conforme", OK)]
                    for c in list(reversed(measured))[:20]]),
        ],
    )


def tile_blocked(ctx):
    source = "Lots au statut « bloqué » qui ont encore du stock (état actuel)."
    blocked = [lot for lot in ctx.stock if lot.status == Lot.Status.BLOQUE]
    threshold = ctx.threshold("blocked_lots")
    by_reason = defaultdict(int)
    for lot in blocked:
        by_reason[(lot.block_reason or lot.block_code or "Motif non renseigné").split(" : ")[0]] += 1
    return _tile(
        "blocked", "Lots bloqués", value=len(blocked), unit="lots", status=ctx.status("blocked_lots", len(blocked)),
        threshold=threshold, scope="now", source=source,
        subtitle="Aucun lot bloqué" if not blocked else ", ".join(sorted({lot.article.name for lot in blocked})),
        detail=[
            _bars("Lots bloqués par motif", "lots", [{"label": k, "value": v} for k, v in by_reason.items()]),
            _table("Lots bloqués", ["Lot", "Article", "Site", "Stock", "Motif"],
                   [[lot.code, lot.article.name, lot.site.name if lot.site else "Aucun",
                     _fmt(lot.balance, lot.article.base_unit), _cell(lot.block_reason or lot.block_code, BAD)]
                    for lot in blocked]),
        ],
    )


def tile_approvals(ctx):
    mine = ctx.user.role == User.Role.OPERATEUR
    title = "Mes demandes en attente" if mine else "Validations en attente"
    source = "Demandes de double validation (écran Validations) encore en attente."
    pending = list(lot_selectors.approval_requests(user=ctx.user, status=ApprovalRequest.Status.PENDING))
    threshold = ctx.threshold("pending_approval_hours")
    ages = [_hours(ctx.now - r.created_at) for r in pending]
    oldest = max(ages) if ages else None
    status = ctx.status("pending_approval_hours", oldest) if pending else OK
    actions = dict(ApprovalRequest.Action.choices)
    return _tile(
        "approvals", title, value=len(pending), unit="demandes", status=status, threshold=threshold, scope="now",
        source=source,
        subtitle=f"La plus ancienne attend depuis {_fmt(oldest, 'h')}" if pending else "Aucune demande en attente",
        detail=[
            _table("Demandes en attente", ["Demandée le", "Action", "Lot", "Demandée par", "Attente"],
                   [[_when(r.created_at), actions.get(r.action, r.action), r.lot.code,
                     r.requested_by.get_full_name() or r.requested_by.username,
                     _cell(_fmt(age, "h"), ctx.status("pending_approval_hours", age))]
                    for r, age in zip(pending, ages)]),
        ],
    )


def _waits(ctx):
    """Attente avant chaque etape : debut de l'etape moins l'heure ou le lot consomme est devenu disponible."""
    run_ids = [r.id for r in ctx.runs]
    waits = defaultdict(list)
    inputs = (
        ProductionInput.objects.filter(run_id__in=run_ids)
        .exclude(lot__article__article_type=Article.Type.EMBALLAGE)
        .select_related("run").values_list("run__step", "run__started_at", "lot_id")
    )
    for step, started_at, lot_id in inputs:
        ready = ctx.lot_ready_at.get(lot_id)
        if ready is not None:
            waits[step].append(max(_hours(started_at - ready), Decimal("0")))
    return waits


def _waiting_stock(ctx):
    """Stock disponible en attente, regroupe par l'etape d'ou il sort (« Réception » pour un lot recu).

    Les produits finis (cartons, palettes) n'y sont pas : ils attendent une expedition, pas une etape.
    """
    groups = OrderedDict()
    for lot in ctx.stock:
        if lot.status != Lot.Status.DISPONIBLE or lot.article.article_type == Article.Type.FINI:
            continue
        origin = ctx.lot_origin_step.get(lot.id, RECEPTION)
        ready = ctx.lot_ready_at.get(lot.id)
        age = _hours(ctx.now - ready) if ready else None
        groups.setdefault(origin, []).append((lot, age))
    order = ctx.step_order
    return OrderedDict(sorted(groups.items(), key=lambda kv: -1 if kv[0] == RECEPTION else order.get(kv[0], 99)))


def _origin_label(code):
    return "Réception" if code == RECEPTION else STEP_LABELS.get(code, code)


def tile_bottleneck(ctx):
    source = ("Heures entre la sortie d'un lot (réception ou étape précédente) et le début de l'étape qui le "
              "consomme, d'après les déclarations de production.")
    threshold = ctx.threshold("step_wait_hours")
    waits = _waits(ctx)
    if not waits:
        return _tile("bottleneck", "Goulot d'étranglement", empty=True, source=source, threshold=threshold, unit="h")
    order = ctx.step_order
    steps = sorted(waits, key=lambda s: order.get(s, 99))
    avg = {s: sum(waits[s]) / len(waits[s]) for s in steps}
    worst_step = max(steps, key=lambda s: avg[s])
    durations = defaultdict(list)
    counts = defaultdict(int)
    for r in ctx.runs:
        durations[r.step].append(_hours(r.ended_at - r.started_at))
        counts[r.step] += 1
    stock = _waiting_stock(ctx)
    stock_kg = {k: sum((lot.balance for lot, _ in v if _kg(lot)), Decimal("0")) for k, v in stock.items()}
    return _tile(
        "bottleneck", "Goulot d'étranglement", value=_num(avg[worst_step]), unit="h",
        value_label=f"d'attente avant {STEP_LABELS[worst_step]}", threshold=threshold, source=source,
        status=ctx.status("step_wait_hours", avg[worst_step]),
        subtitle=f"Étape la plus attendue : {STEP_LABELS[worst_step]}",
        detail=[
            _bars("Attente moyenne avant chaque étape", "h",
                  [{"label": STEP_LABELS[s], "value": _num(avg[s]), "status": ctx.status("step_wait_hours", avg[s])}
                   for s in steps]),
            _bars("Durée moyenne de chaque étape", "h",
                  [{"label": STEP_LABELS[s], "value": _num(sum(durations[s]) / len(durations[s]))}
                   for s in sorted(durations, key=lambda s: order.get(s, 99))]),
            _bars("Stock en attente maintenant, par étape d'où il sort", "kg",
                  [{"label": _origin_label(k), "value": _num(v)} for k, v in stock_kg.items()]),
            _table("Détail par étape", ["Étape", "Déclarations", "Attente moyenne", "Attente la plus longue",
                                        "Durée moyenne"],
                   [[STEP_LABELS[s], counts[s], _cell(_fmt(avg[s], "h"), ctx.status("step_wait_hours", avg[s])),
                     _fmt(max(waits[s]), "h"), _fmt(sum(durations[s]) / len(durations[s]), "h")] for s in steps]),
        ],
    )


def tile_wip(ctx):
    mine = ctx.user.role == User.Role.OPERATEUR
    title = "À traiter" if mine else "Stock en attente entre étapes"
    source = "Lots disponibles avec du stock, hors produits finis et emballages (état actuel)."
    threshold = ctx.threshold("step_wait_hours")
    stock = _waiting_stock(ctx)
    rows, statuses, total = [], [], Decimal("0")
    for origin, lots in stock.items():
        for lot, age in sorted(lots, key=lambda x: -(x[1] or 0)):
            status = ctx.status("step_wait_hours", age) if age is not None else INFO
            statuses.append(status)
            if _kg(lot):
                total += lot.balance
            rows.append([_origin_label(origin), lot.code, lot.article.name, lot.site.name if lot.site else "Aucun",
                         _fmt(lot.balance, lot.article.base_unit),
                         _cell(_fmt(age, "h") if age is not None else "Inconnue", status)])
    count = len(rows)
    return _tile(
        "wip", title, value=count, unit="lots", status=worst(statuses) if rows else OK, threshold=threshold,
        scope="now", source=source,
        subtitle=f"{_fmt(total, 'kg')} en attente" if rows else "Rien en attente",
        detail=[
            _bars("Kilos en attente par étape d'où ils sortent", "kg",
                  [{"label": _origin_label(k), "value": _num(sum((lot.balance for lot, _ in v if _kg(lot)), Decimal("0")))}
                   for k, v in stock.items()]),
            _table("Lots en attente", ["Sort de", "Lot", "Article", "Site", "Stock", "Attend depuis"], rows),
        ],
    )


def tile_stock(ctx):
    source = "Lots de produits finis (cartons, palettes) avec du stock (état actuel)."
    finished = [lot for lot in ctx.stock if lot.article.article_type == Article.Type.FINI]
    if not finished:
        return _tile("stock", "Produits finis en stock", unit="kg", empty=True, scope="now", source=source)
    available = defaultdict(Decimal)
    blocked = defaultdict(Decimal)
    for lot in finished:
        if _kg(lot):
            (available if lot.status == Lot.Status.DISPONIBLE else blocked)[lot.article.name] += lot.balance
    total = sum(available.values(), Decimal("0"))
    names = sorted(set(available) | set(blocked))
    return _tile(
        "stock", "Produits finis en stock", value=_num(total), unit="kg", scope="now", source=source,
        value_label="disponibles",
        subtitle=f"{_fmt(sum(blocked.values(), Decimal('0')), 'kg')} bloqués" if blocked else "Aucun produit fini bloqué",
        detail=[
            _bars("Kilos disponibles par produit", "kg", [{"label": k, "value": _num(v)} for k, v in available.items()]),
            _table("Par produit", ["Produit", "Disponible", "Bloqué"],
                   [[n, _fmt(available.get(n, 0), "kg"), _cell(_fmt(blocked[n], "kg"), BAD) if blocked.get(n) else "0 kg"]
                    for n in names]),
        ],
    )


def lot_expiry_status(ctx, lot):
    days = (lot.expiry_date - ctx.today).days
    return days, ctx.status("expiry_days", days)


def tile_expiry(ctx):
    source = "DLC ou DDM des lots disponibles avec du stock (état actuel)."
    threshold = ctx.threshold("expiry_days")
    dated = [lot for lot in ctx.stock if lot.status == Lot.Status.DISPONIBLE and lot.expiry_date]
    if not dated:
        return _tile("expiry", "Dates limites", empty=True, scope="now", source=source, threshold=threshold, unit="lots")
    rated = sorted(((lot, *lot_expiry_status(ctx, lot)) for lot in dated), key=lambda x: x[1])
    alerts = [x for x in rated if x[2] != OK]
    types = dict(Lot.DateType.choices)
    return _tile(
        "expiry", "Dates limites", value=len(alerts), unit="lots", value_label="à surveiller ou dépassés",
        status=worst([x[2] for x in rated]), threshold=threshold, scope="now", source=source,
        subtitle=f"{len(dated)} lot(s) daté(s) en stock, le plus proche dans {rated[0][1]} jour(s)",
        detail=[
            _table("Lots en stock par date", ["Lot", "Article", "Type", "Date", "Jours restants", "Stock"],
                   [[lot.code, lot.article.name, types.get(lot.date_type, "Non renseigné").split(" (")[0],
                     _day(lot.expiry_date), _cell(f"{days} j", status), _fmt(lot.balance, lot.article.base_unit)]
                    for lot, days, status in rated[:50]]),
        ],
    )


def tile_organic(ctx):
    source = "Statut bio des lots reçus sur la période (recopié de la parcelle) et des parcelles actives."
    rows = [m for m in ctx.receptions if _kg(m.lot)]
    parcels = defaultdict(int)
    for status in Parcel.objects.filter(is_active=True).values_list("organic_status", flat=True):
        parcels[status] += 1
    if not rows:
        return _tile("organic", "Part bio reçue", unit="%", empty=True, source=source)
    by_status = defaultdict(Decimal)
    for m in rows:
        by_status[m.lot.organic_status or ""] += m.quantity
    total = sum(by_status.values(), Decimal("0"))
    pct = _pct(by_status.get(OrganicStatus.BIO, 0), total)
    return _tile(
        "organic", "Part bio reçue", value=_num(pct), unit="%", source=source, value_label="des kilos reçus",
        subtitle=", ".join(f"{ORGANIC_LABELS.get(k, 'Non renseigné')} {_fmt(v, 'kg')}" for k, v in by_status.items()),
        detail=[
            _bars("Kilos reçus par statut", "kg",
                  [{"label": ORGANIC_LABELS.get(k, "Non renseigné"), "value": _num(v)} for k, v in by_status.items()]),
            _bars("Parcelles actives par statut", "parcelles",
                  [{"label": ORGANIC_LABELS.get(k, k), "value": v} for k, v in parcels.items()]),
        ],
    )


def tile_reception_conformity(ctx):
    source = "Contrôle visuel saisi à la réception (conforme ou non conforme)."
    threshold = ctx.threshold("reception_conform_pct")
    rated = [m for m in ctx.receptions if m.lot.reception_visual_ok is not None]
    if not rated:
        return _tile("reception_conformity", "Réceptions conformes", unit="%", empty=True, source=source,
                     threshold=threshold)
    bad = [m for m in rated if m.lot.reception_visual_ok is False]
    pct = _pct(len(rated) - len(bad), len(rated))
    return _tile(
        "reception_conformity", "Réceptions conformes", value=_num(pct), unit="%", threshold=threshold,
        status=ctx.status("reception_conform_pct", pct), source=source,
        subtitle=f"{len(rated)} livraison(s), {len(bad)} refusée(s) ou non conforme(s)",
        detail=[
            _table("Réceptions non conformes", ["Date", "Lot", "Fournisseur", "Parcelle", "Motif"],
                   [[_when(m.occurred_at), m.lot.code, m.lot.supplier.name if m.lot.supplier else "Non renseigné",
                     m.lot.parcel.code if m.lot.parcel else "Aucune", _cell(m.lot.block_reason or "Non renseigné", BAD)]
                    for m in reversed(bad)]),
        ],
    )


def _late_rows(ctx):
    from lots.services import is_late

    rows = []
    for m in ctx.receptions:
        rows.append(("Réceptions", bool(m.late_reason_code) or is_late(occurred_at=m.occurred_at, created_at=m.created_at)))
    for r in ctx.runs:
        rows.append(("Déclarations d'étape", r.late))
    return rows


def tile_late_entries(ctx):
    source = "Réceptions et déclarations saisies plus de 2 heures après le geste (règle de saisie tardive)."
    threshold = ctx.threshold("late_entries_pct")
    rows = _late_rows(ctx)
    if not rows:
        return _tile("late_entries", "Saisies tardives", unit="%", empty=True, source=source, threshold=threshold)
    late = sum(1 for _, x in rows if x)
    pct = _pct(late, len(rows))
    by_kind = defaultdict(lambda: [0, 0])
    for kind, x in rows:
        by_kind[kind][0] += 1
        by_kind[kind][1] += int(x)
    return _tile(
        "late_entries", "Saisies tardives", value=_num(pct), unit="%", threshold=threshold, source=source,
        status=ctx.status("late_entries_pct", pct), subtitle=f"{late} saisie(s) tardive(s) sur {len(rows)}",
        detail=[
            _bars("Part de saisies tardives par type", "%",
                  [{"label": k, "value": _num(_pct(v[1], v[0])), "status": ctx.status("late_entries_pct", _pct(v[1], v[0]))}
                   for k, v in by_kind.items()]),
        ],
    )


def tile_runs(ctx):
    source = "Déclarations d'étape (écran Production), hors déclarations annulées."
    if not ctx.runs:
        return _tile("runs", "Déclarations d'étape", unit="déclarations", empty=True, source=source)
    order = ctx.step_order
    by_step, by_bucket, by_equipment = defaultdict(int), defaultdict(lambda: defaultdict(list)), {}
    for r in ctx.runs:
        by_step[r.step] += 1
        by_bucket["Déclarations"][ctx.bucket(_local_date(r.ended_at))].append(Decimal(1))
        name = r.equipment.code if r.equipment else "Sans équipement"
        e = by_equipment.setdefault(name, {"n": 0, "h": Decimal("0"), "name": r.equipment.name if r.equipment else ""})
        e["n"] += 1
        e["h"] += _hours(r.ended_at - r.started_at)
    return _tile(
        "runs", "Déclarations d'étape", value=len(ctx.runs), unit="déclarations", source=source,
        subtitle=f"{len(by_step)} étape(s), {len(by_equipment)} équipement(s)",
        detail=[
            ctx.line("Déclarations par période", "déclarations", by_bucket),
            _bars("Déclarations par étape", "déclarations",
                  [{"label": STEP_LABELS[s], "value": by_step[s]} for s in sorted(by_step, key=lambda s: order.get(s, 99))]),
            _table("Utilisation des équipements", ["Équipement", "Nom", "Déclarations", "Heures déclarées"],
                   [[k, v["name"] or "Aucun", v["n"], _fmt(v["h"], "h")] for k, v in sorted(by_equipment.items())]),
        ],
    )


def tile_my_entries(ctx):
    source = "Vos réceptions et vos déclarations d'étape sur la période."
    mine = [("Réception", m.occurred_at, m.lot.code, m.lot.article.name, _fmt(m.quantity, m.lot.article.base_unit))
            for m in ctx.receptions if m.user_id == ctx.user.id]
    mine += [(STEP_LABELS[r.step], r.ended_at, r.output_lot.code, r.output_lot.article.name,
              _fmt(r.output_quantity, r.output_lot.article.base_unit)) for r in ctx.runs if r.user_id == ctx.user.id]
    mine.sort(key=lambda x: x[1], reverse=True)
    if not mine:
        return _tile("my_entries", "Mes saisies", unit="saisies", empty=True, source=source)
    return _tile(
        "my_entries", "Mes saisies", value=len(mine), unit="saisies", source=source,
        subtitle=f"Dernière : {mine[0][0].lower()} le {_when(mine[0][1])}",
        detail=[product_selectors.my_entries_compare(ctx.user, ctx.today),
                _table("Mes saisies", ["Type", "Date", "Lot", "Article", "Quantité"],
                       [[k, _when(at), code, name, qty] for k, at, code, name, qty in mine])],
    )


def _has_conforming_check(lot_id, conforming, parents):
    if lot_id in conforming:
        return True
    found = parents.get(lot_id)
    return bool(found) and all(p in conforming for p in found)


def tile_ready_without_qc(ctx):
    """Produits finis disponibles sans controle conforme : l'expedition les refuserait (regle de PR 17)."""
    from lots.models import LotLink

    source = "Produits finis disponibles sans contrôle qualité conforme (une palette compte si tous ses cartons le sont)."
    finished = [lot for lot in ctx.stock if lot.status == Lot.Status.DISPONIBLE
                and lot.article.article_type == Article.Type.FINI]
    ids = [lot.id for lot in finished]
    conforming = set(QualityCheck.objects.filter(result=QualityCheck.Result.CONFORME).values_list("lot_id", flat=True))
    parents = defaultdict(list)
    for parent, child, kind in LotLink.objects.filter(child_lot_id__in=ids).values_list(
        "parent_lot_id", "child_lot_id", "parent_lot__article__article_type"
    ):
        if kind != Article.Type.EMBALLAGE:
            parents[child].append(parent)
    todo = [lot for lot in finished if not _has_conforming_check(lot.id, conforming, parents)]
    return _tile(
        "ready_without_qc", "À contrôler avant expédition", value=len(todo), unit="lots", scope="now", source=source,
        status=WARN if todo else OK,
        subtitle="Tous les produits finis ont un contrôle conforme" if not todo else ", ".join(lot.code for lot in todo[:3]),
        detail=[_table("Produits finis sans contrôle conforme", ["Lot", "Article", "Site", "Stock"],
                       [[lot.code, lot.article.name, lot.site.name if lot.site else "Aucun",
                         _cell(_fmt(lot.balance, lot.article.base_unit), WARN)] for lot in todo])],
    )


TILES = {
    "targets": product_selectors.tile_targets, "products": product_selectors.tile_products,
    "line_stops": product_selectors.tile_line_stops,
    "received": tile_received, "produced": tile_produced, "shipped": tile_shipped, "yields": tile_yields,
    "qc": tile_qc, "moisture": tile_moisture, "blocked": tile_blocked, "approvals": tile_approvals,
    "bottleneck": tile_bottleneck, "wip": tile_wip, "stock": tile_stock, "expiry": tile_expiry,
    "organic": tile_organic, "reception_conformity": tile_reception_conformity, "late_entries": tile_late_entries,
    "runs": tile_runs, "my_entries": tile_my_entries, "ready_without_qc": tile_ready_without_qc,
}


def default_days(role):
    return DEFAULT_DAYS.get(role, 365)


def dashboard(*, user, days=None, now=None):
    days = days or default_days(user.role)
    ctx = Context(user=user, days=days, now=now)
    tiles = [TILES[code](ctx) for code in ROLE_TILES.get(user.role, [])]
    # Comparaison : meme calcul sur la periode juste avant (meme duree). Seulement pour les tuiles « sur la
    # periode » : un etat actuel (stock, lots bloques) n'a pas d'historique stocke, donc pas de comparaison.
    previous_ctx = Context(user=user, days=days, now=ctx.now - datetime.timedelta(days=days))
    for tile in tiles:
        if tile["scope"] == "period" and not tile["empty"]:
            before = TILES[tile["code"]](previous_ctx)
            tile["previous"] = None if before["empty"] else before["value"]
    return {
        "role": user.role,
        "days": days,
        "periods": list(PERIODS),
        "generated_at": ctx.now,
        "granularity": ctx.granularity,
        "tiles": tiles,
    }
