"""Expliquer l'ecart a la cible : du produit a l'equipement, puis a l'arret et au lot concerne.

Criteres d'acceptation :
- la liste des produits montre cible a date, reel et ecart, le plus grand retard en premier ;
- le detail d'un produit montre une cascade : cible, pertes estimees par arrets non planifies (marquees
  « estimation »), ecart non explique, reel declare, lots bloques ou detruits, reel bon. La cascade tombe juste ;
- les pertes = heures d'arret non planifie x kilos par heure de l'equipement sur la periode ;
- les arrets planifies sont montres a part, sans etre comptes comme une perte ;
- le detail d'un equipement montre la frise (marche declaree et arrets), le Pareto des causes et le lot en cours
  pendant chaque arret ;
- la tuile Arrets de ligne a une frise et un Pareto dont chaque barre ouvre la liste filtree des arrets ;
- l'operateur n'y a pas acces, une autre entreprise recoit 404.
"""

import datetime
from decimal import Decimal

from django.utils import timezone

from conftest import make_user
from core.tenancy import tenant_context
from lots.tests.conftest import client_for
from shipping.tests.test_shipments_and_recall import chain  # noqa: F401 (fixture)
from tenants.models import User

GAP = "/api/v1/dashboard/gap/"
TARGETS = "/api/v1/dashboard/targets/"
RUNS = "/api/v1/production/runs/"
STOPS = "/api/v1/production/stops/"


def at(minutes_ago):
    return (timezone.now() - datetime.timedelta(minutes=minutes_ago)).isoformat()


def set_target(client, article, kg):
    today = timezone.localdate()
    months = [None] * 12
    months[today.month - 1] = kg
    response = client.put(TARGETS, {"article": str(article.id), "year": today.year, "months": months}, format="json")
    assert response.status_code == 200, response.json()


def dry(client, orchard, lot, kg, equipment, start, end):
    response = client.post(RUNS, {"step": "sechage", "output_article": str(orchard["dried"].id), "output_quantity": kg,
                                  "inputs": [{"lot": str(lot.id), "quantity": "500"}],
                                  "equipment": str(equipment.id), "started_at": at(start), "ended_at": at(end)},
                           format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def stop(client, equipment, cause, start, end):
    response = client.post(STOPS, {"equipment": str(equipment.id), "cause_code": cause, "started_at": at(start),
                                   "ended_at": at(end)}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def received_before(orchard, tenant, user, minutes_ago):
    from lots import services as lots

    with tenant_context(tenant.id):
        return lots.receive_lot(
            tenant_id=tenant.id, user=user, article=orchard["fresh"], supplier=orchard["p_bio"].producer,
            supplier_lot_code="", quantity=Decimal("500"), unit="kg", date_type="ddm",
            expiry_date=datetime.date.today() + datetime.timedelta(days=10), parcel=orchard["p_bio"],
            occurred_at=timezone.now() - datetime.timedelta(minutes=minutes_ago),
        )


def scenario(client, orchard, receive_fresh):
    """Sechoir 1 : 30 kg en 90 minutes (20 kg/h), coupure de 30 minutes pendant le sechage (10 kg perdus),
    nettoyage planifie d'une heure avant. Cible du mois tres haute : en retard."""
    owner = orchard["dried"]
    fresh = received_before(orchard, owner.tenant, User.objects.filter(tenant=owner.tenant, role="admin").first(), 110)
    run = dry(client, orchard, fresh, "30", orchard["dryer1"], 100, 10)
    stop(client, orchard["dryer1"], "coupure_courant", 60, 30)
    stop(client, orchard["dryer1"], "nettoyage_changement", 170, 110)
    set_target(client, orchard["dried"], "100000")
    return run


def step(waterfall, code):
    return next(s for s in waterfall["steps"] if s["code"] == code)


def test_product_list_shows_target_real_and_gap_biggest_first(client_a, orchard, receive_fresh):
    scenario(client_a, orchard, receive_fresh)
    response = client_a.get(GAP, {"period": "mois"})
    assert response.status_code == 200, response.json()
    body = response.json()
    assert [p["label"] for p in body["periods"]] == ["Aujourd'hui", "Cette semaine", "Ce mois-ci"]
    row = body["products"][0]
    assert row["article_id"] == str(orchard["dried"].id)
    assert row["real"] == 30 and row["target"] > 30 and row["gap"] == round(row["real"] - row["target"], 1)
    assert row["status"] == "bad" and row["stop_loss"] == 10
    assert body["biggest_gap"] == str(orchard["dried"].id)


def test_product_waterfall_adds_up_and_marks_the_estimate(client_a, orchard, receive_fresh):
    scenario(client_a, orchard, receive_fresh)
    body = client_a.get(f"{GAP}{orchard['dried'].id}/", {"period": "mois"}).json()
    waterfall = next(d for d in body["detail"] if d["kind"] == "waterfall")
    target, loss = step(waterfall, "target"), step(waterfall, "stop_loss")
    unexplained, real = step(waterfall, "unexplained"), step(waterfall, "real")
    assert loss["value"] == -10 and loss["estimate"] is True
    assert real["value"] == 30 and real["total"] is True
    assert round(target["value"] + loss["value"] + unexplained["value"], 1) == real["value"]
    assert step(waterfall, "good")["value"] == 30
    equipment = body["equipment"][0]
    assert equipment["code"] == "SEC-1"
    assert equipment["rate"] == 20 and equipment["unplanned_hours"] == 0.5 and equipment["planned_hours"] == 1
    assert equipment["stop_loss"] == 10
    assert "planifié" in body["planned_note"]


def test_blocked_lots_lower_the_good_quantity(client_a, orchard, receive_fresh):
    run = scenario(client_a, orchard, receive_fresh)
    nok = client_a.post(f"/api/v1/lots/{run['output_lot_id']}/quality-checks/",
                        {"checks": {"humidite": "ok", "corps_etrangers": "nok"}}, format="json")
    assert nok.status_code == 201, nok.json()
    body = client_a.get(f"{GAP}{orchard['dried'].id}/", {"period": "mois"}).json()
    waterfall = next(d for d in body["detail"] if d["kind"] == "waterfall")
    assert step(waterfall, "quality")["value"] == -30
    assert step(waterfall, "good")["value"] == 0


def test_equipment_view_has_timeline_pareto_and_the_lot_in_progress(client_a, orchard, receive_fresh):
    run = scenario(client_a, orchard, receive_fresh)
    url = f"{GAP}{orchard['dried'].id}/equipment/{orchard['dryer1'].id}/"
    response = client_a.get(url, {"period": "mois"})
    assert response.status_code == 200, response.json()
    body = response.json()
    timeline = next(d for d in body["detail"] if d["kind"] == "timeline")
    kinds = {item["kind"] for lane in timeline["lanes"] for item in lane["items"]}
    assert {"run", "unplanned", "planned"} <= kinds
    pareto = next(d for d in body["detail"] if d["kind"] == "bars")
    assert pareto["bars"][0]["label"] == "Nettoyage ou changement de fruit (planifié)"
    assert pareto["bars"][0]["href"].startswith("/arrets?")
    cut = next(s for s in body["stops"] if s["cause_code"] == "coupure_courant")
    assert cut["lots"] == [run["output_lot_code"]] and cut["stop_loss"] == 10
    cleaning = next(s for s in body["stops"] if s["cause_code"] == "nettoyage_changement")
    assert cleaning["lots"] == [] and cleaning["stop_loss"] == 0


def test_without_target_the_list_says_so(client_a, orchard, chain):
    body = client_a.get(GAP).json()
    assert body["products"] == [] and "cible" in body["message"].lower()


def test_targets_tile_links_to_the_gap_view(client_a, orchard, receive_fresh):
    scenario(client_a, orchard, receive_fresh)
    tiles = {t["code"]: t for t in client_a.get("/api/v1/dashboard/").json()["tiles"]}
    assert tiles["targets"]["link"]["href"].startswith("/dashboard/ecart")


def test_line_stops_tile_has_timeline_and_clickable_pareto(client_a, orchard, receive_fresh):
    scenario(client_a, orchard, receive_fresh)
    tiles = {t["code"]: t for t in client_a.get("/api/v1/dashboard/").json()["tiles"]}
    detail = tiles["line_stops"]["detail"]
    assert any(d["kind"] == "timeline" for d in detail)
    bars = next(d for d in detail if d["kind"] == "bars")
    assert all(b["href"].startswith("/arrets?cause=") for b in bars["bars"])


def test_stop_list_filters_by_cause_and_equipment(client_a, orchard, receive_fresh):
    scenario(client_a, orchard, receive_fresh)
    stop(client_a, orchard["dryer2"], "coupure_courant", 60, 30)
    found = client_a.get(STOPS, {"cause": "coupure_courant"}).json()
    assert len(found) == 2 and {s["cause_code"] for s in found} == {"coupure_courant"}
    found = client_a.get(STOPS, {"cause": "coupure_courant", "equipment": str(orchard["dryer1"].id)}).json()
    assert len(found) == 1


def test_operator_has_no_gap_view(tenant_a, orchard):
    operator = client_for(make_user(tenant_a, "op_gap", role=User.Role.OPERATEUR))
    assert operator.get(GAP).status_code == 403
    for role in (User.Role.PRODUCTION, User.Role.QUALITE, User.Role.LECTURE):
        assert client_for(make_user(tenant_a, f"gap_{role}", role=role)).get(GAP).status_code == 200


def test_bad_period_is_refused(client_a):
    assert client_a.get(GAP, {"period": "siecle"}).status_code == 400


def test_isolation_between_companies(client_a, client_b, orchard, receive_fresh):
    scenario(client_a, orchard, receive_fresh)
    assert client_b.get(GAP).json()["products"] == []
    assert client_b.get(f"{GAP}{orchard['dried'].id}/").status_code == 404
    url = f"{GAP}{orchard['dried'].id}/equipment/{orchard['dryer1'].id}/"
    assert client_b.get(url).status_code == 404

