"""Matieres et fiabilite des chiffres.

Criteres d'acceptation :
- couverture matiere : stock disponible divise par la consommation moyenne des 14 derniers jours, en jours.
  Moins de jours que le seuil : jaune puis rouge (risque de rupture). Sans consommation : « pas de consommation » ;
- MTTR : duree moyenne des pannes declarees et terminees (mecanique, electrique), par equipement, avec le MTBF
  (heures de marche declarees divisees par le nombre de pannes) ;
- producteurs : livraisons, kilos recus, receptions non conformes et rendement de la premiere transformation par
  producteur ;
- chaque tuile dit quand a eu lieu la derniere saisie qui la nourrit, et par qui ;
- qualite des donnees : receptions en double probables, matiere recue sans parcelle, arret en cours depuis plus de
  24 h, cause « Autre », dates dans le futur, produit hors kilos. Ce qui n'est pas mesurable le dit ;
- changer ou retirer une cible deja saisie demande un motif dans une liste fermee, ecrit au journal d'audit ;
- une entreprise ne voit jamais les donnees d'une autre.
"""

import datetime
from decimal import Decimal

from django.utils import timezone

from audit.models import AuditLog
from core.tenancy import tenant_context
from dashboard.tests.test_gap import RUNS, STOPS, TARGETS, at
from lots import services as lots
from tenants.models import User

DASH = "/api/v1/dashboard/"


def receive(orchard, tenant, user, minutes_ago, kg="500", parcel="p_bio", visual_ok=True, article="fresh"):
    p = orchard[parcel] if parcel else None
    with tenant_context(tenant.id):
        return lots.receive_lot(
            tenant_id=tenant.id, user=user, article=orchard[article],
            supplier=p.producer if p else orchard["producer"], supplier_lot_code="", quantity=Decimal(kg),
            unit="kg", date_type="ddm", expiry_date=datetime.date.today() + datetime.timedelta(days=10), parcel=p,
            organic_status="" if p else "conventionnel", visual_ok=visual_ok,
            reason_code="" if visual_ok else "contamination", late_reason_code="ressaisie_papier",
            occurred_at=timezone.now() - datetime.timedelta(minutes=minutes_ago),
        )


def tiles(client):
    return {t["code"]: t for t in client.get(DASH).json()["tiles"]}


def table(tile, title_start):
    return next(d for d in tile["detail"] if d["kind"] == "table" and d["title"].startswith(title_start))


def run(client, orchard, inputs, kg, start, end, equipment="dryer1"):
    response = client.post(RUNS, {"step": "sechage", "output_article": str(orchard["dried"].id), "output_quantity": kg,
                                  "inputs": [{"lot": str(lot.id), "quantity": q} for lot, q in inputs],
                                  "equipment": str(orchard[equipment].id), "started_at": at(start),
                                  "ended_at": at(end), "late_reason_code": "ressaisie_papier"}, format="json")
    assert response.status_code == 201, response.json()


def test_coverage_days_and_rupture_risk(tenant_a, client_a, admin_a, orchard):
    first = receive(orchard, tenant_a, admin_a, 300)
    receive(orchard, tenant_a, admin_a, 290)
    run(client_a, orchard, [(first, "500")], "30", 200, 100)
    coverage = tiles(client_a)["coverage"]
    rows = {r[0]: r for r in table(coverage, "Couverture par matière")["rows"]}
    fresh = rows["Mangue fraîche"]
    # 500 kg en stock, 500 kg consommes en 14 jours : 35,7 kg par jour, 14 jours de couverture.
    assert "14" in str(fresh[3]["text"] if isinstance(fresh[3], dict) else fresh[3])
    assert coverage["status"] == "ok"


def test_coverage_turns_red_when_stock_runs_out(tenant_a, client_a, admin_a, orchard):
    lot = receive(orchard, tenant_a, admin_a, 300)
    run(client_a, orchard, [(lot, "500")], "30", 200, 100)
    coverage = tiles(client_a)["coverage"]
    assert coverage["status"] == "bad"
    fresh = {r[0]: r for r in table(coverage, "Couverture par matière")["rows"]}["Mangue fraîche"]
    assert fresh[3]["status"] == "bad"


def test_mttr_and_mtbf_from_declared_breakdowns(client_a, orchard, tenant_a, admin_a):
    lot = receive(orchard, tenant_a, admin_a, 900)
    run(client_a, orchard, [(lot, "500")], "30", 800, 200)  # 10 h de marche declaree
    for cause, start, end in (("panne_mecanique", 600, 540), ("panne_electrique", 500, 380),
                              ("coupure_courant", 300, 290), ("nettoyage_changement", 280, 220)):
        r = client_a.post(STOPS, {"equipment": str(orchard["dryer1"].id), "cause_code": cause, "started_at": at(start),
                                  "ended_at": at(end)}, format="json")
        assert r.status_code == 201, r.json()
    mttr = tiles(client_a)["mttr"]
    assert mttr["value"] == 1.5 and mttr["unit"] == "h"  # (1 h + 2 h) / 2 pannes
    row = table(mttr, "Par équipement")["rows"][0]
    assert row[0].startswith("SEC-1") and row[1] == 2  # deux pannes, la coupure et le nettoyage ne comptent pas
    assert "5" in str(row[3])  # MTBF : 10 h de marche / 2 pannes


def test_suppliers_conformity_and_first_transformation_yield(client_a, orchard, tenant_a, admin_a):
    good = receive(orchard, tenant_a, admin_a, 300, parcel="p_bio")
    bad = receive(orchard, tenant_a, admin_a, 290, parcel="p_bio2", visual_ok=False)
    run(client_a, orchard, [(good, "500")], "35", 200, 150)
    suppliers = tiles(client_a)["suppliers"]
    rows = {r[0]: r for r in table(suppliers, "Par producteur")["rows"]}
    assert set(rows) == {"Producteur Un", "Producteur Deux"}
    assert rows["Producteur Un"][1] == "Mangue fraîche"
    assert rows["Producteur Deux"][4]["status"] == "bad"  # 1 livraison non conforme sur 1
    assert "7 %" in str(rows["Producteur Un"][5]) and "séchage" in rows["Producteur Un"][5]  # 35 kg pour 500 kg
    assert bad.supplier.name == "Producteur Deux"


def test_every_tile_says_when_its_last_entry_was(client_a, orchard, tenant_a, admin_a):
    receive(orchard, tenant_a, admin_a, 30)
    shown = tiles(client_a)
    assert all("last_entry" in t for t in shown.values())
    received = shown["received"]["last_entry"]
    assert received is not None and received["by"] and received["at"]
    assert shown["shipped"]["last_entry"] is None  # aucune expedition saisie


def test_data_quality_flags_duplicates_missing_parcel_and_forgotten_stop(client_a, client_b, orchard, tenant_a,
                                                                         admin_a):
    receive(orchard, tenant_a, admin_a, 30)
    receive(orchard, tenant_a, admin_a, 25)  # meme producteur, meme article, meme quantite, 5 minutes apres
    receive(orchard, tenant_a, admin_a, 20, parcel=None, kg="120")
    r = client_a.post(STOPS, {"equipment": str(orchard["dryer2"].id), "cause_code": "panne_mecanique",
                              "started_at": at(30 * 60)}, format="json")
    assert r.status_code == 201, r.json()
    quality = tiles(client_a)["data_quality"]
    checks = {row[0]: row for row in table(quality, "Contrôles")["rows"]}
    assert checks["Réceptions en double probables"][1] == 1
    assert checks["Matière reçue sans parcelle"][1] == 1
    assert checks["Arrêt en cours depuis plus de 24 h"][1] == 1
    assert "Non mesurable" in str(checks["Décalage d'horloge"][2])
    assert quality["status"] == "warn" and quality["value"] == 3
    other = tiles(client_b)["data_quality"]
    assert other["value"] == 0 and other["status"] == "ok"


def test_changing_a_target_needs_a_coded_reason(client_a, orchard, tenant_a):
    today = timezone.localdate()
    months = [None] * 12
    months[today.month - 1] = "1000"
    body = {"article": str(orchard["dried"].id), "year": today.year, "months": months}
    assert client_a.put(TARGETS, body, format="json").status_code == 200  # premiere saisie : pas de motif
    months[today.month - 1] = "800"
    refused = client_a.put(TARGETS, body, format="json")
    assert refused.status_code == 400 and "reason_code" in refused.json()
    assert client_a.put(TARGETS, {**body, "reason_code": "inconnu"}, format="json").status_code == 400
    ok = client_a.put(TARGETS, {**body, "reason_code": "prevision_revue"}, format="json")
    assert ok.status_code == 200, ok.json()
    with tenant_context(tenant_a.id):
        last = AuditLog.objects.filter(entity_type="dashboard.productiontarget", action="update").latest("created_at")
    assert last.new_values["reason"] == "Prévision revue"
    reasons = client_a.get(TARGETS).json()["change_reasons"]
    assert "prevision_revue" in {r["code"] for r in reasons}


def test_new_tiles_by_role(tenant_a, client_a):
    from conftest import make_user
    from lots.tests.conftest import client_for

    for role, expected in ((User.Role.ADMIN, {"coverage", "mttr", "suppliers", "data_quality"}),
                           (User.Role.PRODUCTION, {"coverage", "mttr", "data_quality"}),
                           (User.Role.QUALITE, {"suppliers", "data_quality"})):
        client = client_a if role == User.Role.ADMIN else client_for(make_user(tenant_a, f"r_{role}", role=role))
        assert expected <= set(tiles(client))
