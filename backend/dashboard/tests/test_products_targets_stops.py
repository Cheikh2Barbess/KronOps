"""Suivi par produit, cible contre reel et arrets de ligne au tableau de bord.

Criteres d'acceptation :
- chaque produit (mangue, ananas, coco) se suit seul, en comparaison jour, semaine, mois et saison ;
- l'Admin saisit une cible mensuelle par produit (en kilos), le tableau de bord montre cible, reel et ecart,
  vert, jaune ou rouge selon le seuil d'atteinte (valeur par defaut marquee) ;
- les arrets de ligne declares s'affichent par cause et par equipement, planifies a part ;
- chaque role a sa version (le patron, la production, la qualite, l'operateur) ;
- une entreprise ne voit jamais les cibles ni les arrets d'une autre.
"""

import datetime

from django.utils import timezone

from audit.models import AuditLog
from conftest import make_user
from core.tenancy import tenant_context
from dashboard.indicators import BAD, OK, WARN
from events.models import OutboxEvent
from lots.tests.conftest import client_for
from shipping.tests.test_shipments_and_recall import chain, qc_ok, run, ship  # noqa: F401 (fixture)
from tenants.models import User

URL = "/api/v1/dashboard/"
TARGETS = "/api/v1/dashboard/targets/"
STOPS = "/api/v1/production/stops/"


def tiles(client, **params):
    response = client.get(URL, params)
    assert response.status_code == 200, response.json()
    return {t["code"]: t for t in response.json()["tiles"]}


def set_month_target(client, article, kg, when=None):
    when = when or timezone.localdate()
    months = [None] * 12
    months[when.month - 1] = kg
    return client.put(TARGETS, {"article": str(article.id), "year": when.year, "months": months}, format="json")


def tab(detail, label):
    tabs = next(d for d in detail if d["kind"] == "tabs")["tabs"]
    return next(t for t in tabs if t["label"] == label)


# Cibles -----------------------------------------------------------------------------


def test_admin_sets_monthly_targets_and_others_only_read_them(tenant_a, client_a, orchard):
    response = set_month_target(client_a, orchard["dried"], "200")
    assert response.status_code == 200, response.json()
    year = timezone.localdate().year
    listed = client_a.get(TARGETS, {"year": year}).json()
    row = next(a for a in listed["articles"] if a["id"] == str(orchard["dried"].id))
    assert row["months"][timezone.localdate().month - 1] == 200
    # Les emballages et les matieres premieres ne recoivent pas de cible de production.
    assert str(orchard["box"].id) not in {a["id"] for a in listed["articles"]}
    production = client_for(make_user(tenant_a, "prod_t", role=User.Role.PRODUCTION))
    assert production.get(TARGETS, {"year": year}).status_code == 200
    assert set_month_target(production, orchard["dried"], "300").status_code == 403
    with tenant_context(tenant_a.id):
        assert AuditLog.objects.filter(entity_type="dashboard.productiontarget").count() == 1
        assert OutboxEvent.objects.filter(event_type="dashboard.targets_changed").count() == 1


def test_target_can_be_removed_and_must_be_positive(client_a, orchard):
    assert set_month_target(client_a, orchard["dried"], "-5").status_code == 400
    assert set_month_target(client_a, orchard["dried"], "200").status_code == 200
    year = timezone.localdate().year
    cleared = client_a.put(TARGETS, {"article": str(orchard["dried"].id), "year": year, "months": [None] * 12},
                           format="json")
    assert cleared.status_code == 200
    assert all(v is None for v in cleared.json()["months"])


def test_target_tile_compares_actual_to_target_to_date(client_a, orchard, chain):
    # 195 kg seches aujourd'hui. Cible tres haute : rouge. Cible tres basse : vert.
    set_month_target(client_a, orchard["dried"], "10000")
    target = tiles(client_a)["targets"]
    assert target["status"] == BAD and target["threshold"]["code"] == "target_attainment_pct"
    month = next(d for d in target["detail"] if d["kind"] == "table")
    assert "Écart" in " ".join(month["columns"]) and "195 kg" in str(month["rows"])
    set_month_target(client_a, orchard["dried"], "1")
    assert tiles(client_a)["targets"]["status"] == OK
    # Vue par mois : courbe du reel et de la cible, la cible marquee comme telle.
    lines = [d for d in tab(tiles(client_a)["targets"]["detail"], "Mois")["details"] if d["kind"] == "line"]
    assert any(s.get("target") for s in lines[0]["series"])


def test_target_tile_without_target_says_so(client_a, orchard, chain):
    target = tiles(client_a)["targets"]
    assert target["empty"] is True and "cible" in target["source"].lower()


# Suivi par produit --------------------------------------------------------------------


def test_product_tracking_has_day_week_month_and_season_views(client_a, orchard, chain):
    product = tiles(client_a)["products"]
    labels = [t["label"] for t in next(d for d in product["detail"] if d["kind"] == "tabs")["tabs"]]
    assert labels == ["Jour", "Semaine", "Mois", "Saison"]
    month = tab(product["detail"], "Mois")
    table = next(d for d in month["details"] if d["kind"] == "table")
    assert "Mangue séchée vrac" in str(table["rows"]) and "195 kg" in str(table["rows"])
    season = tab(product["detail"], "Saison")
    assert any(d["kind"] == "table" for d in season["details"])


def test_quality_sees_quality_figures_per_product(tenant_a, orchard, chain):
    quality = tiles(client_for(make_user(tenant_a, "qa_p", role=User.Role.QUALITE)))["products"]
    titles = " ".join(d["title"] for d in tab(quality["detail"], "Mois")["details"])
    assert "contrôles conformes" in titles.lower()
    assert "séché" not in quality["title"].lower() or "qualité" in quality["title"].lower()


# Arrets de ligne ---------------------------------------------------------------------


def test_line_stops_tile_by_cause_and_equipment(client_a, orchard):
    now = timezone.now()
    for equipment, cause, hours_ago, length in [
        (orchard["dryer1"], "coupure_courant", 30, 3),
        (orchard["dryer2"], "nettoyage_changement", 10, 2),
    ]:
        start = now - datetime.timedelta(hours=hours_ago)
        response = client_a.post(STOPS, {"equipment": str(equipment.id), "cause_code": cause,
                                         "started_at": start.isoformat(),
                                         "ended_at": (start + datetime.timedelta(hours=length)).isoformat()},
                                 format="json")
        assert response.status_code == 201, response.json()
    stops = tiles(client_a)["line_stops"]
    assert stops["value"] == 3 and stops["unit"] == "h"  # heures non planifiees
    assert "2 h planifiées" in stops["subtitle"]
    bars = [d for d in stops["detail"] if d["kind"] == "bars"]
    assert {b["label"] for b in bars[0]["bars"]} == {"Coupure de courant", "Nettoyage ou changement de fruit (planifié)"}
    assert stops["status"] == OK


def test_ongoing_stop_turns_the_tile_yellow(client_a, orchard):
    client_a.post(STOPS, {"equipment": str(orchard["dryer1"].id), "cause_code": "panne_mecanique"}, format="json")
    stops = tiles(client_a)["line_stops"]
    assert stops["status"] == WARN and "en cours" in stops["subtitle"]


def test_every_role_sees_line_stops_and_operator_sees_no_targets(tenant_a, client_a):
    for role in (User.Role.PRODUCTION, User.Role.OPERATEUR, User.Role.LECTURE, User.Role.QUALITE):
        found = tiles(client_for(make_user(tenant_a, f"s_{role}", role=role)))
        assert "line_stops" in found
        if role == User.Role.OPERATEUR:
            assert "targets" not in found and "products" not in found
    assert {"targets", "products", "line_stops"} <= set(tiles(client_a))


def test_isolation_of_targets_and_stops(client_a, client_b, orchard, chain):
    set_month_target(client_a, orchard["dried"], "200")
    client_a.post(STOPS, {"equipment": str(orchard["dryer1"].id), "cause_code": "panne_mecanique"}, format="json")
    found = tiles(client_b)
    assert found["targets"]["empty"] is True and found["line_stops"]["value"] == 0
    assert all(a["id"] != str(orchard["dried"].id) for a in client_b.get(TARGETS).json()["articles"])
    assert set_month_target(client_b, orchard["dried"], "5").status_code == 400
