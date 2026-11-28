"""Expliquer l'ecart a la cible : produit, puis equipement, puis arret et lot concerne (trois clics).

Regles (dites a l'ecran) :
- cible a date et reel : memes calculs que la tuile « Réel contre cible » (product_selectors.Targets) ;
- perte par arret = heures d'arret non planifie x kilos par heure de l'equipement sur la periode (kilos produits
  divises par les heures de marche declarees). C'est une ESTIMATION, marquee comme telle ;
- un arret compte pour un produit selon le lot en cours sur l'equipement pendant l'arret. Sans lot en cours, il est
  reparti selon la part du produit dans les kilos de l'equipement sur la periode ;
- les arrets planifies (nettoyage, maintenance preventive) sont montres a part, jamais comptes comme une perte ;
- « écart non expliqué » = ce que les arrets declares n'expliquent pas. Il n'y a pas de barre micro-arrets ni
  ralentissements : sans compteur, ces pertes ne se mesurent pas ;
- lots bloques ou detruits = etat actuel des lots produits sur la periode.
"""

import datetime
from collections import defaultdict
from decimal import Decimal
from urllib.parse import urlencode

from django.http import Http404
from django.utils import timezone

from catalog.models import Article
from dashboard.product_selectors import Targets, _fmt, _month_start, _num, _week_start, stops_href
from lots.models import Lot
from production import selectors as production_selectors
from production.models import Equipment, ProductionRun

PERIODS = {"jour": "Aujourd'hui", "semaine": "Cette semaine", "mois": "Ce mois-ci"}
DEFAULT_PERIOD = "mois"
ESTIMATE_NOTE = ("Estimation : heures d'arrêt non planifié multipliées par les kilos par heure de l'équipement sur la "
                 "période (kilos produits divisés par les heures de marche déclarées).")
PLANNED_NOTE = "Arrêts planifiés (nettoyage, maintenance préventive) : montrés à part, pas comptés comme une perte."


def _hours(delta):
    return Decimal(delta.total_seconds()) / Decimal(3600)


def period_bounds(period, now):
    """Debut (jour local) et fin (maintenant) de la periode en cours, a date."""
    today = timezone.localdate(now)
    first = {"jour": today, "semaine": _week_start(today), "mois": _month_start(today)}[period]
    start = timezone.make_aware(datetime.datetime.combine(first, datetime.time()))
    return first, today, start


class Gap:
    """Faits d'une periode : cibles, reel, declarations par equipement, arrets. Lu une fois par appel."""

    def __init__(self, period, now=None):
        self.period = period
        self.now = now or timezone.now()
        self.first, self.today, self.start = period_bounds(period, self.now)
        self.targets = Targets(self.today)
        self.names = production_selectors.product_names()
        self.runs = list(
            ProductionRun.objects.filter(ended_at__gte=self.start, ended_at__lte=self.now, cancellation__isnull=True)
            .select_related("output_lot__article", "equipment", "site")
        )
        self.stops = [production_selectors.decorate_stop(s, now=self.now, start=self.start, end=self.now)
                      for s in production_selectors.line_stops(start=self.start, end=self.now,
                                                               include_cancelled=False)]
        by_equipment = defaultdict(list)
        for r in self.runs:
            if r.equipment_id:
                by_equipment[r.equipment_id].append(r)
        self.runs_by_equipment = by_equipment

    # Produits -----------------------------------------------------------------

    def label(self, article):
        return self.names.get(article.id, article.name)

    def target_articles(self):
        """Articles qui ont une cible sur un mois touche par la periode."""
        months = {_month_start(self.first), _month_start(self.today)}
        return [a for aid, a in self.targets.articles.items()
                if any(m in self.targets.monthly[aid] for m in months)]

    def runs_of(self, article_id):
        return [r for r in self.runs if r.output_lot.article_id == article_id]

    # Equipements ----------------------------------------------------------------

    def rate(self, equipment_id, article_id):
        """Kilos de l'article par heure de marche declaree sur l'equipement. None sans heure de marche."""
        runs = [r for r in self.runs_by_equipment[equipment_id] if r.output_lot.article_id == article_id]
        hours = sum((_hours(r.ended_at - r.started_at) for r in runs), Decimal("0"))
        if not hours:
            return None
        return sum((r.output_quantity for r in runs), Decimal("0")) / hours

    def lots_during(self, stop):
        """Declarations en cours sur l'equipement pendant l'arret (le lot concerne)."""
        end = stop.ended_at or self.now
        return [r for r in self.runs_by_equipment.get(stop.equipment_id, [])
                if r.started_at < end and r.ended_at > stop.started_at]

    def share(self, stop, article_id):
        """Part de l'arret qui revient a l'article : lot en cours, sinon part des kilos de l'equipement."""
        during = self.lots_during(stop)
        pool = during or self.runs_by_equipment.get(stop.equipment_id, [])
        total = sum((r.output_quantity for r in pool), Decimal("0"))
        if not total:
            return Decimal("0")
        mine = sum((r.output_quantity for r in pool if r.output_lot.article_id == article_id), Decimal("0"))
        return mine / total

    def stop_loss(self, stop, article_id):
        if stop.planned:
            return Decimal("0")
        rate = self.rate(stop.equipment_id, article_id)
        if rate is None:
            return Decimal("0")
        return stop.duration_hours * self.share(stop, article_id) * rate

    def equipment_rows(self, article_id):
        rows = []
        equipment_ids = {r.equipment_id for r in self.runs_of(article_id) if r.equipment_id}
        for eid in equipment_ids:
            runs = [r for r in self.runs_by_equipment[eid] if r.output_lot.article_id == article_id]
            equipment = runs[0].equipment
            stops = [s for s in self.stops if s.equipment_id == eid]
            unplanned = sum((s.duration_hours * self.share(s, article_id) for s in stops if not s.planned),
                            Decimal("0"))
            planned = sum((s.duration_hours for s in stops if s.planned), Decimal("0"))
            loss = sum((self.stop_loss(s, article_id) for s in stops), Decimal("0"))
            rate = self.rate(eid, article_id)
            rows.append({
                "id": str(eid), "code": equipment.code, "name": equipment.name,
                "site": equipment.site.name if equipment.site else None,
                "produced": _num(sum((r.output_quantity for r in runs), Decimal("0"))),
                "run_hours": _num(sum((_hours(r.ended_at - r.started_at) for r in runs), Decimal("0"))),
                "rate": _num(rate), "unplanned_hours": _num(unplanned, 2), "planned_hours": _num(planned, 2),
                "stops": len(stops), "stop_loss": _num(loss),
                "ongoing": any(s.ongoing for s in stops),
            })
        return sorted(rows, key=lambda r: -(r["stop_loss"] or 0))

    def product_row(self, article, status_for):
        target = self.targets.target(article.id, self.first, self.today)
        real = self.targets.real(article.id, self.first, self.today)
        loss = sum((Decimal(str(r["stop_loss"] or 0)) for r in self.equipment_rows(article.id)), Decimal("0"))
        pct = real * 100 / target if target else None
        causes = defaultdict(Decimal)
        for s in self.stops:
            if not s.planned:
                causes[s.cause_label] += self.stop_loss(s, article.id)
        top = max(causes.items(), key=lambda kv: kv[1]) if causes and max(causes.values()) > 0 else None
        return {
            "article_id": str(article.id), "label": self.label(article), "article_name": article.name,
            "unit": article.base_unit, "target": _num(target), "real": _num(real),
            "gap": _num(real - target) if target is not None else None, "attainment": _num(pct),
            "status": status_for(pct), "stop_loss": _num(loss), "top_cause": top[0] if top else None,
        }


def _periods():
    return [{"code": code, "label": label} for code, label in PERIODS.items()]


def products(ctx_status, period):
    """Niveau 1 : chaque produit avec une cible, le plus grand retard en premier."""
    gap = Gap(period)
    rows = [gap.product_row(a, ctx_status) for a in gap.target_articles()]
    rows = [r for r in rows if r["target"] is not None]
    rows.sort(key=lambda r: (r["gap"] if r["gap"] is not None else 0))
    behind = [r for r in rows if r["gap"] is not None and r["gap"] < 0]
    return {
        "period": period, "periods": _periods(), "from": gap.first, "to": gap.today,
        "products": rows, "biggest_gap": behind[0]["article_id"] if behind else None,
        "message": "" if rows else "Aucune cible sur cette période : saisissez les cibles (Tableau de bord, Cibles).",
        "estimate_note": ESTIMATE_NOTE,
    }


def _article_or_404(article_id):
    article = Article.objects.filter(pk=article_id).first()
    if article is None:
        raise Http404
    return article


def _step(code, label, value, *, total=False, estimate=False, note=""):
    return {"code": code, "label": label, "value": _num(value), "total": total, "estimate": estimate, "note": note}


def product(ctx_status, period, article_id):
    """Niveau 2 : cascade de l'ecart et equipements du produit."""
    article = _article_or_404(article_id)
    gap = Gap(period)
    row = gap.product_row(article, ctx_status)
    equipment = gap.equipment_rows(article.id)
    unit = article.base_unit
    runs = gap.runs_of(article.id)
    bad_lots = [r for r in runs if r.output_lot.status in (Lot.Status.BLOQUE, Lot.Status.DETRUIT)]
    quality = sum((r.output_quantity for r in bad_lots), Decimal("0"))
    real = gap.targets.real(article.id, gap.first, gap.today)
    target = gap.targets.target(article.id, gap.first, gap.today)
    detail = []
    if target is not None:
        loss = sum((Decimal(str(e["stop_loss"] or 0)) for e in equipment), Decimal("0"))
        unexplained = real - target + loss
        detail.append({
            "kind": "waterfall", "unit": unit,
            "title": "De la cible au réel : ce que les arrêts déclarés expliquent, et ce qu'ils n'expliquent pas",
            "steps": [
                _step("target", "Cible à date", target, total=True, note="Cible du mois répartie sur ses jours."),
                _step("stop_loss", "Arrêts non planifiés", -loss, estimate=True, note=ESTIMATE_NOTE),
                _step("unexplained", "Reste non expliqué", unexplained, note="Ce que les arrêts déclarés n'expliquent pas : matière, cadence, saisie "
                                        "manquante. Sans compteur, les micro-arrêts ne se mesurent pas."),
                _step("real", "Réel déclaré", real, total=True, note="Déclarations d'étape, hors annulations."),
                _step("quality", "Lots bloqués ou détruits", -quality,
                      note="État actuel des lots produits sur la période."),
                _step("good", "Réel bon", real - quality, total=True),
            ],
        })
    detail.append({
        "kind": "bars", "unit": unit, "title": "Kilos perdus estimés par équipement (arrêts non planifiés)",
        "bars": [{"label": f"{e['code']} {e['name']}", "value": e["stop_loss"],
                  "href": f"/dashboard/ecart?{urlencode({'period': period, 'article': article.id, 'equipment': e['id']})}"}
                 for e in equipment if e["stop_loss"]],
    })
    if bad_lots:
        detail.append({"kind": "table", "title": "Lots bloqués ou détruits sur la période",
                       "columns": ["Lot", "Quantité", "État", "Équipement"],
                       "rows": [[r.output_lot.code, _fmt(r.output_quantity, unit), r.output_lot.get_status_display(),
                                 r.equipment.code if r.equipment else "Aucun"] for r in bad_lots]})
    return {
        "period": period, "periods": _periods(), "from": gap.first, "to": gap.today, "product": row,
        "equipment": equipment, "detail": detail, "estimate_note": ESTIMATE_NOTE, "planned_note": PLANNED_NOTE,
        "unequipped": _num(sum((r.output_quantity for r in runs if not r.equipment_id), Decimal("0"))),
    }


def _timeline_item(start, end, kind, label, href=""):
    return {"start": start.isoformat(), "end": end.isoformat(), "kind": kind, "label": label, "href": href}


def timeline(gap, equipment_list, *, with_runs):
    """Frise : une ligne par equipement, marche declaree (si demandee) et arrets, sur toute la periode (un mois au
    plus)."""
    begin = gap.start
    lanes = []
    for equipment in equipment_list:
        items = []
        if with_runs:
            for r in gap.runs_by_equipment.get(equipment.id, []):
                if r.ended_at > begin:
                    items.append(_timeline_item(max(r.started_at, begin), r.ended_at, "run",
                                                f"{r.output_lot.code} ({gap.label(r.output_lot.article)})"))
        for s in gap.stops:
            if s.equipment_id != equipment.id or (s.ended_at and s.ended_at < begin):
                continue
            kind = "ongoing" if s.ongoing else "planned" if s.planned else "unplanned"
            items.append(_timeline_item(max(s.started_at, begin), s.ended_at or gap.now, kind,
                                        f"{s.cause_label}, {_fmt(s.duration_hours, 'h')}",
                                        stops_href(equipment=equipment.id, cause=s.cause_code)))
        if items:
            lanes.append({"label": f"{equipment.code} {equipment.name}", "items": sorted(items, key=lambda i: i["start"])})
    return {"kind": "timeline", "title": "Frise : marche déclarée et arrêts" if with_runs else "Frise des arrêts",
            "start": begin.isoformat(), "end": gap.now.isoformat(), "lanes": lanes,
            "legend": {"run": "Marche déclarée", "unplanned": "Arrêt non planifié", "planned": "Arrêt planifié",
                       "ongoing": "Arrêt en cours"}}


def pareto(stops, unit="h", **href_params):
    by_cause = defaultdict(Decimal)
    codes = {}
    for s in stops:
        by_cause[s.cause_label] += s.duration_hours
        codes[s.cause_label] = s.cause_code
    return {"kind": "bars", "unit": unit, "title": "Pareto des causes : heures d'arrêt, la plus lourde d'abord",
            "bars": [{"label": label, "value": _num(v), "href": stops_href(cause=codes[label], **href_params)}
                     for label, v in sorted(by_cause.items(), key=lambda kv: -kv[1])]}


def equipment(ctx_status, period, article_id, equipment_id):
    """Niveau 3 : un equipement pour un produit. Frise, Pareto, arrets avec le lot en cours et la perte estimee."""
    article = _article_or_404(article_id)
    found = Equipment.objects.filter(pk=equipment_id).select_related("site").first()
    if found is None:
        raise Http404
    gap = Gap(period)
    stops = [s for s in gap.stops if s.equipment_id == found.id]
    rows = []
    for s in stops:
        during = gap.lots_during(s)
        rows.append({
            "id": str(s.id), "started_at": s.started_at, "ended_at": s.ended_at, "ongoing": s.ongoing,
            "duration_hours": _num(s.duration_hours, 2), "cause_code": s.cause_code, "cause_label": s.cause_label,
            "planned": s.planned, "lots": [r.output_lot.code for r in during],
            "stop_loss": _num(gap.stop_loss(s, article.id)),
            "declared_by": (s.user.get_full_name() or s.user.username) if s.user else None,
        })
    return {
        "period": period, "periods": _periods(), "from": gap.first, "to": gap.today,
        "product": gap.product_row(article, ctx_status),
        "equipment": {"id": str(found.id), "code": found.code, "name": found.name,
                      "site": found.site.name if found.site else None,
                      "rate": _num(gap.rate(found.id, article.id))},
        "stops": rows, "estimate_note": ESTIMATE_NOTE, "planned_note": PLANNED_NOTE,
        "stops_href": stops_href(equipment=found.id),
        "detail": [timeline(gap, [found], with_runs=True), pareto(stops, equipment=found.id)],
    }
