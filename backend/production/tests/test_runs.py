"""Declaration d'etape : lots consommes par morceaux, un lot sur plusieurs sechoirs, pas de melange bio,
bilan matiere avec rendement et ecarts signales."""

import datetime
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from conftest import make_user
from core.tenancy import tenant_context
from events.models import OutboxEvent
from lots import selectors as lot_selectors
from lots.models import LotLink
from production.models import ProductionRun
from tenants.models import User

URL = "/api/v1/production/runs/"
BALANCE = "/api/v1/production/balance/"


def dry(client, orchard, inputs, kg, dryer="dryer1", **extra):
    data = {
        "step": "sechage", "equipment": str(orchard[dryer].id), "output_article": str(orchard["dried"].id),
        "output_quantity": kg, "inputs": [{"lot": str(lot.id), "quantity": q} for lot, q in inputs],
    }
    data.update(extra)
    return client.post(URL, data, format="json")


def test_one_lot_split_over_two_dryers(client_a, orchard, receive_fresh, tenant_a):
    fresh = receive_fresh(orchard["p_bio"], "2000")
    first = dry(client_a, orchard, [(fresh, "1300")], "100")
    assert first.status_code == 201, first.json()
    second = dry(client_a, orchard, [(fresh, "700")], "50", dryer="dryer2")
    assert second.status_code == 201, second.json()
    with tenant_context(tenant_a.id):
        assert lot_selectors.lot_balance(fresh.id) == 0
        assert LotLink.objects.filter(parent_lot=fresh).count() == 2
    body = first.json()
    assert body["equipment_code"] == "SEC-1"
    assert body["organic_status"] == "bio"
    assert body["inputs"][0]["parcel_code"] == "P-BIO"
    assert Decimal(body["yield_pct"]) == Decimal("7.69")
    assert body["yield_status"] == "conforme"


def test_partial_consumption_leaves_the_rest_in_stock(client_a, orchard, receive_fresh, tenant_a):
    fresh = receive_fresh(orchard["p_bio"], "1000")
    assert dry(client_a, orchard, [(fresh, "400")], "28").status_code == 201
    with tenant_context(tenant_a.id):
        assert lot_selectors.lot_balance(fresh.id) == Decimal("600")


def test_mixing_organic_and_conventional_is_refused(client_a, orchard, receive_fresh):
    bio = receive_fresh(orchard["p_bio"], "500")
    conv = receive_fresh(orchard["p_conv"], "500")
    response = dry(client_a, orchard, [(bio, "500"), (conv, "500")], "70")
    assert response.status_code == 400
    assert "Mélange interdit" in response.json()["inputs"][0]


def test_two_organic_parcels_can_be_mixed(client_a, orchard, receive_fresh):
    a = receive_fresh(orchard["p_bio"], "500")
    b = receive_fresh(orchard["p_bio2"], "500")
    response = dry(client_a, orchard, [(a, "500"), (b, "500")], "70")
    assert response.status_code == 201
    assert response.json()["organic_status"] == "bio"


def test_more_output_than_input_is_refused(client_a, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "100")
    response = dry(client_a, orchard, [(fresh, "100")], "150")
    assert response.status_code == 400
    assert "output_quantity" in response.json()


def test_cannot_consume_more_than_the_lot_holds(client_a, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "100")
    assert dry(client_a, orchard, [(fresh, "150")], "10").status_code == 400


def test_cannot_consume_a_lot_before_it_was_received(client_a, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "100")
    yesterday = (timezone.now() - datetime.timedelta(days=1)).isoformat()
    response = dry(client_a, orchard, [(fresh, "100")], "7", started_at=yesterday,
                   ended_at=(timezone.now() - datetime.timedelta(hours=20)).isoformat(),
                   late_reason_code="ressaisie_papier")
    assert response.status_code == 400
    assert "occurred_at" in response.json()


def test_yield_out_of_range_is_flagged_not_blocked(client_a, orchard, receive_fresh, tenant_a):
    fresh = receive_fresh(orchard["p_bio"], "1000")
    response = dry(client_a, orchard, [(fresh, "1000")], "40")  # 4 % : sous la fourchette 5,5 a 7,7 %
    assert response.status_code == 201
    assert response.json()["yield_status"] == "bas"
    with tenant_context(tenant_a.id):
        assert OutboxEvent.objects.filter(event_type="production.yield_deviation").count() == 1


def test_waste_is_coded_and_counted(client_a, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "1000")
    data = {"waste_quantity": "300", "waste_code": "peaux_noyaux"}
    body = dry(client_a, orchard, [(fresh, "1000")], "70", **data).json()
    assert Decimal(body["waste_quantity"]) == 300
    assert Decimal(body["unexplained_quantity"]) == 630  # eau evaporee
    assert body["waste_label"] == "Peaux et noyaux"
    other = dry(client_a, orchard, [(receive_fresh(orchard["p_bio"], "100"), "100")], "7", waste_quantity="5")
    assert other.status_code == 400  # nature des dechets obligatoire


def test_packing_in_cartons_uses_the_conversion(client_a, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "1300")
    dried = dry(client_a, orchard, [(fresh, "1300")], "100").json()
    response = client_a.post(URL, {
        "step": "conditionnement", "output_article": str(orchard["carton"].id), "output_quantity": "9",
        "output_unit": "carton", "inputs": [{"lot": dried["output_lot_id"], "quantity": "90"}],
    }, format="json")
    assert response.status_code == 201, response.json()
    assert Decimal(response.json()["output_quantity"]) == 90
    assert Decimal(response.json()["yield_pct"]) == 100


def test_late_declaration_requires_reason(client_a, orchard, receive_fresh, tenant_a):
    with tenant_context(tenant_a.id):
        from lots import services
        fresh = services.receive_lot(
            tenant_id=tenant_a.id, user=None, article=orchard["fresh"], supplier=orchard["producer"],
            supplier_lot_code="", quantity=Decimal("100"), unit="kg", date_type="ddm",
            expiry_date=datetime.date.today() + datetime.timedelta(days=9), parcel=orchard["p_bio"],
            occurred_at=timezone.now() - datetime.timedelta(days=3), late_reason_code="oubli",
        )
    ended = (timezone.now() - datetime.timedelta(days=1)).isoformat()
    assert dry(client_a, orchard, [(fresh, "100")], "7", ended_at=ended).status_code == 400
    response = dry(client_a, orchard, [(fresh, "100")], "7", ended_at=ended, late_reason_code="tablette_indisponible")
    assert response.status_code == 201
    assert response.json()["late"] is True
    assert response.json()["late_reason_label"] == "Tablette ou réseau indisponible"


def test_material_balance_totals_by_step(client_a, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "2000")
    dry(client_a, orchard, [(fresh, "1300")], "100")
    dry(client_a, orchard, [(fresh, "700")], "30", dryer="dryer2")
    body = client_a.get(BALANCE).json()
    assert len(body["runs"]) == 2
    total = body["totals"][0]
    assert total["step"] == "sechage"
    assert Decimal(total["input_quantity"]) == 2000
    assert Decimal(total["output_quantity"]) == 130
    assert Decimal(total["yield_pct"]) == Decimal("6.50")
    assert total["deviations"] == 1  # 30 / 700 = 4,3 %
    assert client_a.get(BALANCE, {"step": "tri"}).json()["runs"] == []


def test_runs_are_append_only(client_a, orchard, receive_fresh, tenant_a):
    fresh = receive_fresh(orchard["p_bio"], "100")
    dry(client_a, orchard, [(fresh, "100")], "7")
    with tenant_context(tenant_a.id):
        with pytest.raises(DatabaseError), transaction.atomic():
            ProductionRun.objects.update(output_quantity=Decimal("8"))


def test_operator_declares_reader_cannot(tenant_a, orchard, receive_fresh):
    from rest_framework.test import APIClient

    fresh = receive_fresh(orchard["p_bio"], "100")
    operator, reader = APIClient(), APIClient()
    operator.force_authenticate(make_user(tenant_a, "op", role=User.Role.OPERATEUR))
    reader.force_authenticate(make_user(tenant_a, "lec", role=User.Role.LECTURE))
    assert dry(reader, orchard, [(fresh, "100")], "7").status_code == 403
    assert dry(operator, orchard, [(fresh, "100")], "7").status_code == 201
    assert operator.get(BALANCE).status_code == 403
    assert reader.get(BALANCE).status_code == 200


def test_isolation_other_company_lots_and_runs(client_a, client_b, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "100")
    run = dry(client_a, orchard, [(fresh, "100")], "7").json()
    assert client_b.get(f"{URL}{run['id']}/").status_code == 404
    assert client_b.get(BALANCE).json()["runs"] == []
    assert client_b.get("/api/v1/equipment/").json() == []
    other = client_b.post(URL, {"step": "sechage", "output_article": str(orchard["dried"].id), "output_quantity": "1",
                                "inputs": [{"lot": str(fresh.id), "quantity": "1"}]}, format="json")
    assert other.status_code == 400
