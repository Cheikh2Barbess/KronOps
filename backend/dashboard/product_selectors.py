"""Lectures du tableau de bord par produit : comparaisons jour, semaine, mois, saison, cible contre reel, arrets.

Memes regles que dashboard/selectors.py : chaque chiffre vient d'une saisie (source citee), rien n'est invente,
une periode sans donnee reste vide (pas de zero trompeur pour un pourcentage).

Produit = parcours de l'article (Référentiels, « Mangue séchée »), sinon l'article lui-meme.
Campagne (saison) d'un produit = mois consecutifs avec du sechage declare. Un mois entier sans sechage ouvre une
nouvelle campagne. Rien n'est saisi en plus : la campagne se lit dans les declarations.
Cible (Sollwert) = quantite mensuelle saisie par l'Admin. Pour un jour ou une semaine, la cible du mois est repartie
sur ses jours (dit a l'ecran). Reel (Istwert) = declarations qui produisent l'article, hors annulations.
"""

import calendar
import datetime
from collections import OrderedDict, defaultdict
from decimal import Decimal

from django.utils import timezone

from catalog.models import Article
from dashboard.indicators import BAD, INFO, OK, WARN, worst
from dashboard.models import ProductionTarget
from lots.models import Movement, QualityCheck
from production import selectors as production_selectors
from production.models import ProductionRun
from shipping.models import ShipmentLine
from tenants.models import User

MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
HISTORY_DAYS = 800  # deux saisons et un peu plus, pour comparer avec l'an dernier
GRANULARITIES = ("Jour", "Semaine", "Mois", "Saison")


def _num(value, places=1):
    return None if value is None else float(round(Decimal(value), places))


def _fmt(value, unit=""):
    if value is None:
        return "Aucune donnée"
    text = f"{Decimal(value):,.1f}".replace(",", " ").replace(".", ",")
    if text.endswith(",0"):
        text = text[:-2]
    return f"{text} {unit}".strip()


def _local(dt):
    return timezone.localtime(dt).date()


def _month_label(year, month):
    return f"{MONTHS[month - 1]} {year % 100:02d}"


def _month_start(day):
    return day.replace(day=1)


def _add_months(day, n):
    month = day.month - 1 + n
    return datetime.date(day.year + month // 12, month % 12 + 1, 1)


def _days_in_month(day):
    return calendar.monthrange(day.year, day.month)[1]


def _week_start(day):
    return day - datetime.timedelta(days=day.weekday())


# Fenetres et comparaisons -------------------------------------------------------------


def windows(today):
    """Pour chaque vue : les periodes de la courbe (debut, fin, libelle) et les trois periodes du tableau.

    Le tableau compare la periode en cours (a date) a la precedente de meme duree et a la meme periode un an
    plus tot, pour ne jamais comparer un mois commence a un mois complet.
    """
    days = [(today - datetime.timedelta(days=k),) * 2 for k in range(29, -1, -1)]
    day_points = [(a, b, a.strftime("%d/%m")) for a, b in days]
    week0 = _week_start(today)
    week_points = []
    for k in range(11, -1, -1):
        a = week0 - datetime.timedelta(weeks=k)
        week_points.append((a, min(a + datetime.timedelta(days=6), today), f"sem. {a.isocalendar()[1]}"))
    month0 = _month_start(today)
    month_points = []
    for k in range(11, -1, -1):
        a = _add_months(month0, -k)
        b = min(_add_months(a, 1) - datetime.timedelta(days=1), today)
        month_points.append((a, b, _month_label(a.year, a.month)))

    def year_before(d):
        try:
            return d.replace(year=d.year - 1)
        except ValueError:  # 29 fevrier
            return d.replace(year=d.year - 1, day=28)

    elapsed_week = today - week0
    elapsed_month = today.day - 1
    last_month = _add_months(month0, -1)
    return {
        "Jour": {
            "points": day_points,
            "gaps": ("Écart avec hier", "Écart avec la semaine dernière"),
            "compare": [
                ("Aujourd'hui (en cours)", today, today),
                ("Hier", today - datetime.timedelta(days=1), today - datetime.timedelta(days=1)),
                ("Même jour, semaine dernière", today - datetime.timedelta(days=7), today - datetime.timedelta(days=7)),
            ],
        },
        "Semaine": {
            "points": week_points,
            "gaps": ("Écart avec la semaine dernière", "Écart sur un an"),
            "compare": [
                ("Cette semaine (à date)", week0, today),
                ("Semaine dernière, même durée", week0 - datetime.timedelta(weeks=1),
                 week0 - datetime.timedelta(weeks=1) + elapsed_week),
                ("Même semaine l'an dernier", year_before(week0), year_before(week0) + elapsed_week),
            ],
        },
        "Mois": {
            "points": month_points,
            "gaps": ("Écart avec le mois dernier", "Écart sur un an"),
            "compare": [
                ("Ce mois-ci (à date)", month0, today),
                ("Mois dernier, même durée", last_month,
                 last_month + datetime.timedelta(days=min(elapsed_month, _days_in_month(last_month) - 1))),
                ("Même mois l'an dernier", year_before(month0), year_before(month0) + datetime.timedelta(days=elapsed_month)),
            ],
        },
    }


# Donnees par produit --------------------------------------------------------------------


class Rows:
    """Faits elementaires d'un indicateur : (jour, produit, numerateur, denominateur)."""

    def __init__(self, code, label, unit, kind, rows, source, band=None):
        self.code, self.label, self.unit, self.kind, self.source = code, label, unit, kind, source
        self.rows = rows
        self.band = band or {}  # produit -> (min, max) pour colorer un rendement
        self.by_product = defaultdict(list)
        for row in rows:
            self.by_product[row[1]].append(row)

    def value(self, product, start, end):
        found = [r for r in self.by_product.get(product, ()) if start <= r[0] <= end]
        if self.kind == "sum":
            return sum((r[2] for r in found), Decimal("0"))
        if not found:
            return None
        if self.kind == "ratio":
            den = sum((r[3] for r in found), Decimal("0"))
            return sum((r[2] for r in found), Decimal("0")) * 100 / den if den else None
        return sum((r[2] for r in found), Decimal("0")) / len(found)

    def status(self, product, value, ctx):
        """Couleur d'une valeur quand une regle existe : fourchette de l'article ou seuil de l'entreprise."""
        if value is None:
            return None
        if self.code == "yield" and product in self.band:
            low, high = self.band[product]
            return OK if low <= value <= high else BAD
        if self.code == "qc":
            return ctx.status("qc_conformity_pct", value)
        if self.code == "reception_ok":
            return ctx.status("reception_conform_pct", value)
        return None


class ProductData:
    """Toutes les saisies utiles de l'historique, rangees par produit. Lues une fois par affichage."""

    def __init__(self, today):
        self.today = today
        self.start = timezone.make_aware(datetime.datetime.combine(today - datetime.timedelta(days=HISTORY_DAYS),
                                                                   datetime.time()))
        self.names = production_selectors.product_names()
        self._drying = None

    def product(self, article):
        return self.names.get(article.id, article.name)

    @property
    def drying(self):
        if self._drying is None:
            self._drying = list(
                ProductionRun.objects.filter(step=ProductionRun.Step.SECHAGE, ended_at__gte=self.start,
                                             cancellation__isnull=True, output_lot__article__base_unit=Article.Unit.KG)
                .select_related("output_lot__article")
            )
        return self._drying

    def dried(self):
        return Rows("dried", "Kilos séchés", "kg", "sum",
                    [(_local(r.ended_at), self.product(r.output_lot.article), r.output_quantity, None)
                     for r in self.drying],
                    "Déclarations de l'étape Séchage, hors annulations.")

    def yields(self):
        band = {}
        for r in self.drying:
            a = r.output_lot.article
            if a.yield_min_pct is not None:
                band[self.product(a)] = (a.yield_min_pct, a.yield_max_pct)
        return Rows("yield", "Rendement du séchage", "%", "ratio",
                    [(_local(r.ended_at), self.product(r.output_lot.article), r.output_quantity, r.input_quantity)
                     for r in self.drying if r.input_quantity],
                    "Kilos séchés divisés par les kilos mis au séchoir. Vert dans la fourchette de l'article, "
                    "rouge en dehors.", band=band)

    def _receptions(self):
        return (
            Movement.objects.filter(movement_type=Movement.Type.RECEPTION, occurred_at__gte=self.start,
                                    reversed_by__isnull=True, lot__article__base_unit=Article.Unit.KG)
            .exclude(lot__article__article_type=Article.Type.EMBALLAGE).select_related("lot__article")
        )

    def received(self):
        return Rows("received", "Kilos reçus", "kg", "sum",
                    [(_local(m.occurred_at), self.product(m.lot.article), m.quantity, None) for m in self._receptions()],
                    "Réceptions, hors emballages et réceptions annulées.")

    def reception_ok(self):
        rows = [(_local(m.occurred_at), self.product(m.lot.article), Decimal(100 if m.lot.reception_visual_ok else 0),
                 None) for m in self._receptions() if m.lot.reception_visual_ok is not None]
        return Rows("reception_ok", "Réceptions conformes", "%", "mean", rows,
                    "Contrôle visuel saisi à la réception.")

    def shipped(self):
        lines = (
            ShipmentLine.objects.filter(shipment__shipped_at__gte=self.start, movement__reversed_by__isnull=True,
                                        lot__article__base_unit=Article.Unit.KG)
            .select_related("shipment", "lot__article")
        )
        return Rows("shipped", "Kilos expédiés", "kg", "sum",
                    [(_local(line.shipment.shipped_at), self.product(line.lot.article), line.quantity, None)
                     for line in lines],
                    "Lignes d'expédition, hors lignes annulées.")

    def _checks(self):
        return QualityCheck.objects.filter(checked_at__gte=self.start).select_related("lot__article")

    def qc(self):
        return Rows("qc", "Part des contrôles conformes", "%", "mean",
                    [(_local(c.checked_at), self.product(c.lot.article),
                      Decimal(100 if c.result == QualityCheck.Result.CONFORME else 0), None) for c in self._checks()],
                    "Contrôles qualité. Vert ou rouge selon le seuil de l'entreprise.")

    def moisture(self):
        return Rows("moisture", "Humidité moyenne mesurée", "%", "mean",
                    [(_local(c.checked_at), self.product(c.lot.article), c.moisture_pct, None)
                     for c in self._checks() if c.moisture_pct is not None],
                    "Humidité saisie au contrôle qualité (pas de limite chiffrée enregistrée : sans couleur).")

    def campaigns(self):
        """Produit -> campagnes [(premier mois, dernier mois)], de la plus ancienne a la plus recente."""
        months = defaultdict(set)
        for r in self.drying:
            months[self.product(r.output_lot.article)].add(_month_start(_local(r.ended_at)))
        result = {}
        for product, found in months.items():
            spans = []
            for m in sorted(found):
                if spans and _add_months(spans[-1][1], 1) == m:
                    spans[-1][1] = m
                else:
                    spans.append([m, m])
            result[product] = [tuple(s) for s in spans]
        return result


# Metriques par role : le patron suit volumes et qualite, la production le flux, la qualite ses controles.
ROLE_METRICS = {
    User.Role.ADMIN: ("dried", "shipped", "yields", "qc"),
    User.Role.LECTURE: ("dried", "shipped", "yields", "qc"),
    User.Role.PRODUCTION: ("dried", "received", "yields"),
    User.Role.QUALITE: ("qc", "moisture", "reception_ok", "yields"),
}
ROLE_TITLES = {
    User.Role.ADMIN: "Suivi par produit", User.Role.LECTURE: "Suivi par produit",
    User.Role.PRODUCTION: "Production par produit", User.Role.QUALITE: "Qualité par produit",
}


def campaign_label(span):
    a, b = span
    return _month_label(a.year, a.month) if a == b else f"{_month_label(a.year, a.month)} à {_month_label(b.year, b.month)}"


def _change(now, before, unit):
    """Ecart lisible : en points pour un pourcentage, en % sinon. Avec un mot, pas seulement un signe."""
    if now is None or before is None:
        return "Pas de comparaison"
    if unit == "%":
        diff = Decimal(now) - Decimal(before)
        if abs(diff) < Decimal("0.1"):
            return "stable"
        return f"{'en hausse' if diff > 0 else 'en baisse'} de {_fmt(abs(diff))} pt"
    if not before:
        return "rien avant" if now else "stable"
    diff = (Decimal(now) - Decimal(before)) * 100 / Decimal(before)
    if abs(diff) < Decimal("0.5"):
        return "stable"
    return f"{'en hausse' if diff > 0 else 'en baisse'} de {_fmt(abs(diff).quantize(Decimal('1')))} %"


def _cell(text, status=None):
    return {"text": text, "status": status} if status else text


def _series_line(title, unit, series, aggregate):
    return {"kind": "line", "title": title, "unit": unit, "series": series, "aggregate": aggregate}


def _compare_tab(label, spec, metrics, products, ctx):
    (c1, _, _), (c2, _, _), (c3, _, _) = spec["compare"]
    columns = ["Produit", "Indicateur", c1, c2, spec["gaps"][0], c3, spec["gaps"][1]]
    rows, statuses = [], []
    for metric in metrics:
        for product in products:
            values = [metric.value(product, a, b) for _, a, b in spec["compare"]]
            if all(v is None or (metric.kind == "sum" and v == 0) for v in values):
                continue
            current_status = metric.status(product, values[0], ctx)
            if current_status:
                statuses.append(current_status)
            cells = [_cell(_fmt(v, metric.unit), metric.status(product, v, ctx)) for v in values]
            rows.append([product, metric.label, cells[0], cells[1], _change(values[0], values[1], metric.unit),
                         cells[2], _change(values[0], values[2], metric.unit)])
    details = [{"kind": "table", "title": f"{label} : comparaison par produit", "columns": columns, "rows": rows}]
    for metric in metrics:
        series = []
        for product in products:
            points = []
            for a, b, x in spec["points"]:
                v = metric.value(product, a, b)
                points.append({"x": x, "y": _num(v, 2) if not (metric.kind != "sum" and v is None) else None})
            if any(p["y"] for p in points):
                series.append({"name": product, "points": points})
        if series:
            details.append(_series_line(f"{metric.label} par {label.lower()} et par produit", metric.unit, series,
                                        "sum" if metric.kind == "sum" else "mean"))
    return {"label": label, "details": details}, statuses


def _season_tab(metrics, products, data, ctx):
    campaigns = data.campaigns()
    rows, details = [], []
    main = metrics[0]
    for product in products:
        spans = campaigns.get(product, [])
        previous_total = None
        for index, span in enumerate(spans):
            start, end = span[0], min(_add_months(span[1], 1) - datetime.timedelta(days=1), data.today)
            current = end >= data.today - datetime.timedelta(days=31)
            values = [m.value(product, start, end) for m in metrics]
            cells = [_cell(_fmt(v, m.unit), m.status(product, v, ctx)) for m, v in zip(metrics, values)]
            # Comparaison a la meme etape : la campagne d'avant sur le meme nombre de jours depuis son debut.
            same_stage = "Première campagne"
            if index:
                before_start = spans[index - 1][0]
                before_end = before_start + (end - start)
                previous_total = main.value(product, before_start, before_end)
                same_stage = _change(values[0], previous_total, main.unit)
            rows.append([product, campaign_label(span) + (" (en cours)" if current else ""),
                         (end - start).days // 7 + 1, *cells, same_stage])
        # Courbe : cumul de la metrique principale par semaine de campagne, une ligne par campagne (3 dernieres).
        if main.kind == "sum" and spans:
            series = []
            weeks = 0
            recent = spans[-3:]
            for span in recent:
                weeks = max(weeks, ((min(_add_months(span[1], 1), data.today) - span[0]).days // 7) + 1)
            for span in recent:
                points, total = [], Decimal("0")
                stop = min(_add_months(span[1], 1) - datetime.timedelta(days=1), data.today)
                for w in range(weeks):
                    a = span[0] + datetime.timedelta(weeks=w)
                    if a > stop:
                        points.append({"x": f"S{w + 1}", "y": None})
                        continue
                    total += main.value(product, a, min(a + datetime.timedelta(days=6), stop))
                    points.append({"x": f"S{w + 1}", "y": _num(total)})
                series.append({"name": campaign_label(span), "points": points})
            details.append(_series_line(f"{product} : {main.label.lower()} cumulés par semaine de campagne",
                                        main.unit, series, "cumul"))
    columns = ["Produit", "Campagne", "Semaines", *[m.label for m in metrics],
               f"{main.label} contre la campagne d'avant, à la même semaine"]
    table = {"kind": "table", "title": "Campagnes par produit (mois consécutifs avec du séchage)", "columns": columns,
             "rows": rows}
    return {"label": "Saison", "details": [table, *details]}


def tile_products(ctx):
    data = ProductData(ctx.today)
    metric_codes = ROLE_METRICS.get(ctx.user.role, ROLE_METRICS[User.Role.ADMIN])
    metrics = [getattr(data, code)() for code in metric_codes]
    products = sorted({p for m in metrics for p in m.by_product})
    title = ROLE_TITLES.get(ctx.user.role, "Suivi par produit")
    source = ("Comparaisons tirées des saisies : " + " ".join(m.source for m in metrics)
              + " Une campagne = mois consécutifs avec du séchage.")
    if not products:
        return ctx.tile("products", title, empty=True, source=source, scope="compare")
    spec = windows(ctx.today)
    tabs, statuses = [], []
    for label in GRANULARITIES[:3]:
        tab, found = _compare_tab(label, spec[label], metrics, products, ctx)
        tabs.append(tab)
        if label == "Mois":
            statuses = found
    tabs.append(_season_tab(metrics, products, data, ctx))
    main = metrics[0]
    month = spec["Mois"]["compare"]
    parts = []
    for product in products:
        now, before = main.value(product, month[0][1], month[0][2]), main.value(product, month[1][1], month[1][2])
        if now or before:
            parts.append(f"{product} {_fmt(now, main.unit)} ({_change(now, before, main.unit)})")
    return ctx.tile(
        "products", title, value=len(products), unit="produits", value_label="suivis", status=worst(statuses),
        scope="compare", source=source,
        subtitle=(f"{main.label} ce mois-ci contre le mois dernier à la même date : " + " · ".join(parts)) if parts
        else f"Rien ce mois-ci ni le mois dernier ({main.label.lower()})",
        detail=[{"kind": "tabs", "title": "Comparer par jour, semaine, mois ou saison", "tabs": tabs}],
    )


# Cible contre reel ---------------------------------------------------------------------


def target_articles():
    """Articles qui peuvent recevoir une cible : produits (semi-finis et finis) actifs."""
    return Article.objects.filter(is_active=True, article_type__in=[Article.Type.SEMI_FINI, Article.Type.FINI]).order_by(
        "article_type", "code")


def targets_for_year(year):
    found = defaultdict(lambda: [None] * 12)
    for t in ProductionTarget.objects.filter(month__year=year):
        found[t.article_id][t.month.month - 1] = t.quantity
    names = production_selectors.product_names()
    return [
        {"id": a.id, "code": a.code, "name": a.name, "unit": a.base_unit, "article_type": a.article_type,
         "product": names.get(a.id, a.name), "months": [_num(v, 3) for v in found.get(a.id, [None] * 12)]}
        for a in target_articles()
    ]


class Targets:
    """Cibles mensuelles et reel par jour, article par article."""

    def __init__(self, today):
        self.today = today
        self.monthly = defaultdict(dict)  # article -> {premier jour du mois: cible}
        self.articles = {}
        for t in ProductionTarget.objects.select_related("article"):
            self.monthly[t.article_id][t.month] = t.quantity
            self.articles[t.article_id] = t.article
        start = today - datetime.timedelta(days=HISTORY_DAYS)
        self.actual = defaultdict(lambda: defaultdict(Decimal))  # article -> jour -> quantite
        runs = ProductionRun.objects.filter(output_lot__article_id__in=list(self.articles), cancellation__isnull=True,
                                            ended_at__date__gte=start).select_related("output_lot")
        for r in runs:
            self.actual[r.output_lot.article_id][_local(r.ended_at)] += r.output_quantity

    def target(self, article_id, start, end):
        """Cible de la periode : chaque jour recoit sa part de la cible de son mois. None sans aucune cible."""
        total, found = Decimal("0"), False
        day = start
        while day <= end:
            month_target = self.monthly[article_id].get(_month_start(day))
            if month_target is not None:
                found = True
                total += month_target / _days_in_month(day)
            day += datetime.timedelta(days=1)
        return total if found else None

    def real(self, article_id, start, end):
        return sum((q for d, q in self.actual[article_id].items() if start <= d <= end), Decimal("0"))


def _attainment(real, target):
    return real * 100 / target if target else None


def tile_targets(ctx):
    source = ("Cibles mensuelles saisies par l'Admin (Tableau de bord, Cibles) comparées aux déclarations d'étape "
              "qui produisent l'article, hors annulations. Cible à date = cible du mois répartie sur ses jours.")
    threshold = ctx.threshold("target_attainment_pct")
    data = Targets(ctx.today)
    if not data.articles:
        return ctx.tile("targets", "Réel contre cible", unit="%", empty=True, source=source, threshold=threshold,
                        scope="now")
    month0 = _month_start(ctx.today)
    names = production_selectors.product_names()
    per_product = defaultdict(int)
    for a in data.articles:
        per_product[names.get(a)] += 1
    # Nom du produit (parcours) quand il n'a qu'un article cible, sinon le nom de l'article.
    label = {a: names[a] if a in names and per_product[names[a]] == 1 else art.name
             for a, art in data.articles.items()}
    unit = {a: art.base_unit for a, art in data.articles.items()}
    rows, statuses, total_real, total_target = [], [], Decimal("0"), Decimal("0")
    for a in sorted(data.articles, key=lambda k: label[k]):
        month_target = data.monthly[a].get(month0)
        if month_target is None:
            continue
        to_date = data.target(a, month0, ctx.today)
        real = data.real(a, month0, ctx.today)
        pct = _attainment(real, to_date)
        status = ctx.status("target_attainment_pct", pct)
        statuses.append(status)
        total_real += real
        total_target += to_date
        rows.append([label[a], _fmt(month_target, unit[a]), _fmt(to_date, unit[a]), _fmt(real, unit[a]),
                     _fmt(real - to_date, unit[a]), _cell(_fmt(pct, "%"), status)])
    month_table = {"kind": "table", "title": f"Ce mois-ci ({_month_label(month0.year, month0.month)}), à la date du jour",
                   "columns": ["Produit", "Cible du mois", "Cible à date", "Réel à date", "Écart", "Atteinte"],
                   "rows": rows}
    spec = windows(ctx.today)
    tabs = []
    for name in ("Jour", "Semaine", "Mois"):
        details = []
        table_rows = []
        for a in sorted(data.articles, key=lambda k: label[k]):
            real_points, target_points = [], []
            for start, end, x in spec[name]["points"]:
                t = data.target(a, start, end)
                r = data.real(a, start, end)
                real_points.append({"x": x, "y": _num(r)})
                target_points.append({"x": x, "y": _num(t)})
                if t is not None and name == "Mois":
                    pct = _attainment(r, t)
                    table_rows.append([label[a], x, _fmt(t, unit[a]), _fmt(r, unit[a]), _fmt(r - t, unit[a]),
                                       _cell(_fmt(pct, "%"), ctx.status("target_attainment_pct", pct))])
            if any(p["y"] for p in real_points) or any(p["y"] for p in target_points):
                details.append(_series_line(
                    f"{label[a]} : réel et cible par {name.lower()}" + ("" if name == "Mois" else
                                                                       " (cible du mois répartie sur ses jours)"),
                    unit[a], [{"name": "Réel", "points": real_points},
                              {"name": "Cible", "points": target_points, "target": True}], "sum"))
        if table_rows:
            details.append({"kind": "table", "title": "Mois par mois : cible, réel et écart",
                            "columns": ["Produit", "Mois", "Cible", "Réel", "Écart", "Atteinte"], "rows": table_rows})
        tabs.append({"label": name, "details": details})
    # Saison : cible et reel cumules sur chaque campagne du produit.
    campaigns = ProductData(ctx.today).campaigns()
    season_rows = []
    for a in sorted(data.articles, key=lambda k: label[k]):
        for span in campaigns.get(names.get(a, data.articles[a].name), []):
            start, end = span[0], min(_add_months(span[1], 1) - datetime.timedelta(days=1), ctx.today)
            t, r = data.target(a, start, end), data.real(a, start, end)
            if t is None:
                continue
            pct = _attainment(r, t)
            season_rows.append([label[a], campaign_label(span), _fmt(t, unit[a]), _fmt(r, unit[a]),
                                _fmt(r - t, unit[a]), _cell(_fmt(pct, "%"), ctx.status("target_attainment_pct", pct))])
    tabs.append({"label": "Saison", "details": [{
        "kind": "table", "title": "Par campagne : cible et réel cumulés",
        "columns": ["Produit", "Campagne", "Cible", "Réel", "Écart", "Atteinte"], "rows": season_rows}]})
    if not rows:
        return ctx.tile("targets", "Réel contre cible", unit="%", value_label="Pas de cible ce mois-ci", source=source,
                        threshold=threshold, scope="now", subtitle="Les mois précédents restent consultables.",
                        detail=[month_table, {"kind": "tabs", "title": "Comparer", "tabs": tabs}])
    pct = _attainment(total_real, total_target)
    behind = [r[0] for r, s in zip(rows, statuses) if s != OK]
    return ctx.tile(
        "targets", "Réel contre cible", value=_num(pct), unit="%", value_label="de la cible à date",
        status=worst(statuses), threshold=threshold, scope="now", source=source,
        subtitle=(f"En retard : {', '.join(behind)}" if behind else "Tous les produits sont dans la cible à date"),
        detail=[month_table, {"kind": "tabs", "title": "Comparer par jour, semaine, mois ou saison", "tabs": tabs}],
    )


# Arrets de ligne -------------------------------------------------------------------------


def tile_line_stops(ctx):
    source = "Arrêts de ligne déclarés (écran Arrêts de ligne), hors arrêts annulés. Durée bornée à la période."
    threshold = ctx.threshold("unplanned_stop_hours_week")
    stops = [production_selectors.decorate_stop(s, now=ctx.now, start=ctx.start, end=ctx.now)
             for s in production_selectors.line_stops(start=ctx.start, end=ctx.now, include_cancelled=False)]
    ongoing = [s for s in stops if s.ongoing and s.started_at <= ctx.now]
    unplanned = sum((s.duration_hours for s in stops if not s.planned), Decimal("0"))
    planned = sum((s.duration_hours for s in stops if s.planned), Decimal("0"))
    weekly = unplanned * 7 / Decimal(ctx.days)
    status = ctx.status("unplanned_stop_hours_week", weekly)
    if ongoing:
        status = worst([status, WARN])
    if not stops:
        return ctx.tile("line_stops", "Arrêts de ligne", value=0, unit="h", value_label="d'arrêt non planifié",
                        status=OK, threshold=threshold, source=source, subtitle="Aucun arrêt déclaré sur la période")
    by_cause, by_equipment = defaultdict(Decimal), defaultdict(Decimal)
    by_bucket = defaultdict(lambda: defaultdict(list))
    for s in stops:
        by_cause[(s.cause_label, s.planned)] += s.duration_hours
        by_equipment[f"{s.equipment.code} {s.equipment.name}"] += s.duration_hours
        bucket = ctx.bucket(_local(max(s.started_at, ctx.start)))
        by_bucket["Planifié" if s.planned else "Non planifié"][bucket].append(s.duration_hours)
    rows = [[timezone.localtime(s.started_at).strftime("%d/%m/%Y %H:%M"),
             _cell("En cours", WARN) if s.ongoing else timezone.localtime(s.ended_at).strftime("%d/%m/%Y %H:%M"),
             _fmt(s.duration_hours, "h"), f"{s.equipment.code} {s.equipment.name}",
             s.site.name if s.site else "Aucun", s.cause_label,
             "Planifié" if s.planned else _cell("Non planifié", INFO),
             s.user.get_full_name() or s.user.username if s.user else "Inconnu"] for s in stops]
    parts = [f"{len(stops)} arrêt(s)", f"{_fmt(planned, 'h')} planifiées"]
    if ongoing:
        parts.append(f"{len(ongoing)} en cours ({', '.join(s.equipment.code for s in ongoing)})")
    return ctx.tile(
        "line_stops", "Arrêts de ligne", value=_num(unplanned), unit="h", value_label="d'arrêt non planifié",
        status=status, threshold=threshold, source=source, subtitle=" · ".join(parts),
        detail=[
            {"kind": "bars", "title": "Heures d'arrêt par cause (la plus lourde d'abord)", "unit": "h",
             "bars": [{"label": k[0], "value": _num(v)} for k, v in sorted(by_cause.items(), key=lambda kv: -kv[1])]},
            {"kind": "bars", "title": "Heures d'arrêt par équipement", "unit": "h",
             "bars": [{"label": k, "value": _num(v)} for k, v in sorted(by_equipment.items(), key=lambda kv: -kv[1])]},
            ctx.line("Heures d'arrêt par période, planifiées ou non", "h", by_bucket),
            {"kind": "table", "title": "Arrêts de la période",
             "columns": ["Début", "Fin", "Durée", "Équipement", "Site", "Cause", "Type", "Déclaré par"], "rows": rows},
        ],
    )


# Comparaison des saisies de l'operateur ---------------------------------------------------------


def my_entries_compare(user, today):
    """Mes saisies aujourd'hui, hier et le meme jour la semaine derniere (receptions et declarations)."""
    days = [("Aujourd'hui", today), ("Hier", today - datetime.timedelta(days=1)),
            ("Même jour, semaine dernière", today - datetime.timedelta(days=7))]
    start = timezone.make_aware(datetime.datetime.combine(days[-1][1], datetime.time()))
    receptions = defaultdict(int)
    for at in Movement.objects.filter(movement_type=Movement.Type.RECEPTION, user=user, occurred_at__gte=start,
                                      reversed_by__isnull=True).values_list("occurred_at", flat=True):
        receptions[_local(at)] += 1
    runs = defaultdict(int)
    for at in ProductionRun.objects.filter(user=user, ended_at__gte=start, cancellation__isnull=True).values_list(
            "ended_at", flat=True):
        runs[_local(at)] += 1
    return {"kind": "table", "title": "Mes saisies : aujourd'hui, hier et le même jour la semaine dernière",
            "columns": ["Jour", "Réceptions", "Déclarations d'étape"],
            "rows": [[f"{name} ({d.strftime('%d/%m')})", receptions[d], runs[d]] for name, d in days]}
