"""Aval : controle qualite, expedition par conteneur, rapport de rappel carton, palette, conteneur, client."""

from decimal import Decimal

import pytest

from core.tenancy import tenant_context

RUNS = "/api/v1/production/runs/"
SHIP = "/api/v1/shipments/"
RECALL = "/api/v1/traceability/recall/"


def run(client, step, article, kg, inputs, unit="", equipment=None):
    data = {"step": step, "output_article": str(article.id), "output_quantity": kg, "output_unit": unit,
            "inputs": [{"lot": str(lot_id), "quantity": q} for lot_id, q in inputs]}
    if equipment is not None:
        data["equipment"] = str(equipment.id)
    response = client.post(RUNS, data, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def qc_ok(client, lot_id):
    response = client.post(f"/api/v1/lots/{lot_id}/quality-checks/", {"checks": {"humidite": "ok"}}, format="json")
    assert response.status_code == 201, response.json()


@pytest.fixture
def chain(client_a, orchard, receive_fresh):
    """Deux parcelles bio, un lot mis en commun, reparti sur deux sechoirs, cartons, une palette."""
    a = receive_fresh(orchard["p_bio"], "1300")
    b = receive_fresh(orchard["p_bio2"], "1300")
    d1 = run(client_a, "sechage", orchard["dried"], "100", [(a.id, "1300")], equipment=orchard["dryer1"])
    d2 = run(client_a, "sechage", orchard["dried"], "95", [(b.id, "1300")], equipment=orchard["dryer2"])
    c1 = run(client_a, "conditionnement", orchard["carton"], "10", [(d1["output_lot_id"], "100")], unit="carton")
    c2 = run(client_a, "conditionnement", orchard["carton"], "9", [(d2["output_lot_id"], "90")], unit="carton")
    for c in (c1, c2):
        qc_ok(client_a, c["output_lot_id"])
    return {"a": a, "b": b, "d1": d1, "d2": d2, "c1": c1, "c2": c2}


def ship(client, orchard, lots, **extra):
    data = {"customer": str(orchard["customer"].id), "container_number": "mscu 123456-6", "seal_number": "S-889",
            "export_document_ref": "COI.CI.2026.0001",
            "lines": [{"lot": lot_id, "quantity": q, "unit": "carton"} for lot_id, q in lots]}
    data.update(extra)
    return client.post(SHIP, data, format="json")


# Controle qualite -------------------------------------------------------------


def test_failed_quality_check_blocks_the_lot(client_a, chain, tenant_a):
    url = f"/api/v1/lots/{chain['c1']['output_lot_id']}/quality-checks/"
    response = client_a.post(url, {"checks": {"humidite": "ok", "corps_etrangers": "nok"}, "moisture_pct": "17.5"},
                             format="json")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "bloque"
    assert body["quality_checks"][0]["result"] == "non_conforme"
    assert "corps étrangers" in body["block_reason"]


def test_passed_quality_check_keeps_the_lot_available(client_a, chain):
    url = f"/api/v1/lots/{chain['c1']['output_lot_id']}/quality-checks/"
    body = client_a.post(url, {"checks": {"humidite": "ok", "etiquetage": "ok"}}, format="json").json()
    assert body["status"] == "disponible"
    assert body["quality_checks"][0]["result"] == "conforme"


def test_unknown_criterion_is_refused(client_a, chain):
    url = f"/api/v1/lots/{chain['c1']['output_lot_id']}/quality-checks/"
    assert client_a.post(url, {"checks": {"couleur_du_ciel": "ok"}}, format="json").status_code == 400


def test_isolation_quality_check_on_other_company_lot(client_b, chain):
    url = f"/api/v1/lots/{chain['c1']['output_lot_id']}/quality-checks/"
    assert client_b.post(url, {"checks": {"humidite": "ok"}}, format="json").status_code == 404


# Expedition --------------------------------------------------------------------


def test_shipment_by_container_creates_exit_movements(client_a, orchard, chain, tenant_a):
    response = ship(client_a, orchard, [(chain["c1"]["output_lot_id"], "10"), (chain["c2"]["output_lot_id"], "4")])
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["container_number"] == "MSCU1234566"
    assert {Decimal(line["quantity"]) for line in body["lines"]} == {Decimal("100"), Decimal("40")}
    with tenant_context(tenant_a.id):
        from lots.selectors import lot_balance
        assert lot_balance(chain["c2"]["output_lot_id"]) == Decimal("50")


def test_container_number_format_is_checked(client_a, orchard, chain):
    response = ship(client_a, orchard, [(chain["c1"]["output_lot_id"], "1")], container_number="ABC12")
    assert response.status_code == 400


def test_blocked_lot_cannot_be_shipped(client_a, orchard, chain):
    client_a.post(f"/api/v1/lots/{chain['c1']['output_lot_id']}/quality-checks/",
                  {"checks": {"nuisibles": "nok"}}, format="json")
    assert ship(client_a, orchard, [(chain["c1"]["output_lot_id"], "1")]).status_code == 400


def test_isolation_shipments(client_a, client_b, orchard, chain):
    shipment = ship(client_a, orchard, [(chain["c1"]["output_lot_id"], "1")]).json()
    assert client_b.get(f"{SHIP}{shipment['id']}/").status_code == 404
    assert client_b.get(SHIP).json() == []
    other = client_b.post(SHIP, {"customer": str(orchard["customer"].id), "lines": []}, format="json")
    assert other.status_code == 400


# Rappel ---------------------------------------------------------------------------


def test_recall_from_a_carton_reaches_parcel_and_container(client_a, orchard, chain):
    ship(client_a, orchard, [(chain["c1"]["output_lot_id"], "6")])
    code = chain["c1"]["output_lot_code"]
    body = client_a.get(RECALL, {"search": code}).json()
    assert [r["parcel_code"] for r in body["roots"]] == ["P-BIO"]
    assert body["roots"][0]["organic_status"] == "bio"
    assert Decimal(body["roots"][0]["received_quantity"]) == 1300
    assert [s["container_number"] for s in body["shipments"]] == ["MSCU1234566"]
    assert body["shipments"][0]["export_document_ref"] == "COI.CI.2026.0001"
    assert body["summary"]["customers"] == 1
    steps = [r["step"] for r in body["runs"]]
    assert steps == ["sechage", "conditionnement"]
    in_stock = {r["code"] for r in body["in_stock"]}
    assert code in in_stock  # 4 cartons restent : a bloquer
    assert chain["c2"]["output_lot_code"] not in in_stock  # autre parcelle, autre sechoir : hors perimetre


def test_recall_scope_includes_every_load_from_the_same_raw_lot(client_a, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "2000")
    d1 = run(client_a, "sechage", orchard["dried"], "100", [(fresh.id, "1300")], equipment=orchard["dryer1"])
    d2 = run(client_a, "sechage", orchard["dried"], "50", [(fresh.id, "700")], equipment=orchard["dryer2"])
    body = client_a.get(RECALL, {"search": d1["output_lot_code"]}).json()
    affected = {r["code"] for r in body["affected"]}
    assert d2["output_lot_code"] in affected
    assert [r["code"] for r in body["contents"]] == [fresh.code]


def test_recall_from_a_container_number(client_a, orchard, chain):
    ship(client_a, orchard, [(chain["c1"]["output_lot_id"], "2"), (chain["c2"]["output_lot_id"], "2")])
    body = client_a.get(RECALL, {"search": "MSCU1234566"}).json()
    assert body["container"] == "MSCU1234566"
    assert {r["parcel_code"] for r in body["roots"]} == {"P-BIO", "P-BIO2"}
    assert body["summary"]["parcels"] == 2


def test_recall_unknown_code_and_isolation(client_a, client_b, chain):
    assert client_a.get(RECALL, {"search": "INCONNU"}).status_code == 404
    assert client_b.get(RECALL, {"search": chain["c1"]["output_lot_code"]}).status_code == 404


def test_operator_has_no_access_to_recall(tenant_a, chain):
    from rest_framework.test import APIClient

    from conftest import make_user
    from tenants.models import User

    client = APIClient()
    client.force_authenticate(make_user(tenant_a, "op2", role=User.Role.OPERATEUR))
    assert client.get(RECALL, {"search": chain["c1"]["output_lot_code"]}).status_code == 403


# Controle qualite obligatoire, conteneur ----------------------------------------


def test_never_checked_lot_cannot_be_shipped(client_a, orchard, chain, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "1300")
    dried = run(client_a, "sechage", orchard["dried"], "90", [(fresh.id, "1300")], equipment=orchard["dryer1"])
    carton = run(client_a, "conditionnement", orchard["carton"], "9", [(dried["output_lot_id"], "90")], unit="carton")
    response = ship(client_a, orchard, [(carton["output_lot_id"], "9")])
    assert response.status_code == 400
    assert "jamais été contrôlé" in response.json()["lines"][0]
    qc_ok(client_a, carton["output_lot_id"])
    assert ship(client_a, orchard, [(carton["output_lot_id"], "9")]).status_code == 201


def test_pallet_of_checked_cartons_can_be_shipped(client_a, orchard, chain):
    pallet = run(client_a, "palettisation", orchard["carton"], "190",
                 [(chain["c1"]["output_lot_id"], "100"), (chain["c2"]["output_lot_id"], "90")])
    response = ship(client_a, orchard, [(pallet["output_lot_id"], "19")])
    assert response.status_code == 201, response.json()


def test_container_check_digit_is_verified(client_a, orchard, chain):
    from shipping.services import container_check_digit

    assert container_check_digit("CSQU305438") == 3
    wrong = ship(client_a, orchard, [(chain["c1"]["output_lot_id"], "1")], container_number="MSCU1234567")
    assert wrong.status_code == 400 and "chiffre de contrôle" in wrong.json()["container_number"][0]
