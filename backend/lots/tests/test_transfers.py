"""Transfert d'un lot d'une usine a une autre : tout le lot (meme code) ou une partie (nouveau lot enfant)."""

import datetime
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from conftest import make_user
from core.tenancy import tenant_context
from lots import selectors
from lots import services as lots
from lots.models import LotTransfer
from tenants.models import Site, User

URL = "/api/v1/lots/transfers/"


@pytest.fixture
def two_sites(tenant_a, admin_a, orchard):
    with tenant_context(tenant_a.id):
        north = Site.objects.create(tenant=tenant_a, name="Nord")
        south = Site.objects.create(tenant=tenant_a, name="Sud")
        fresh = lots.receive_lot(
            tenant_id=tenant_a.id, user=admin_a, article=orchard["fresh"], supplier=orchard["producer"],
            supplier_lot_code="", quantity=Decimal("500"), unit="kg", date_type="ddm",
            expiry_date=datetime.date.today() + datetime.timedelta(days=10), parcel=orchard["p_bio"], site=north,
        )
    return {"north": north, "south": south, "fresh": fresh}


def test_whole_lot_moves_and_keeps_its_code(client_a, two_sites, tenant_a):
    fresh = two_sites["fresh"]
    response = client_a.post(URL, {"lot": str(fresh.id), "to_site": str(two_sites["south"].id)}, format="json")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["whole_lot"] is True and body["lot_code"] == fresh.code
    assert body["from_site_name"] == "Nord" and body["to_site_name"] == "Sud"
    assert Decimal(body["quantity"]) == Decimal("500")
    with tenant_context(tenant_a.id):
        assert selectors.lot_or_404(lot_id=fresh.id).site_id == two_sites["south"].id


def test_partial_transfer_creates_a_child_lot_that_keeps_organic_status(client_a, two_sites, tenant_a):
    fresh = two_sites["fresh"]
    response = client_a.post(URL, {"lot": str(fresh.id), "to_site": str(two_sites["south"].id), "quantity": "200"},
                             format="json")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["whole_lot"] is False and body["lot_code"] != fresh.code
    with tenant_context(tenant_a.id):
        source = selectors.lot_or_404(lot_id=fresh.id)
        child = selectors.lot_or_404(lot_id=body["lot_id"])
        assert source.balance == Decimal("300") and source.site_id == two_sites["north"].id
        assert child.balance == Decimal("200") and child.site_id == two_sites["south"].id
        assert child.organic_status == "bio" and child.parcel_id == fresh.parcel_id
        # Le rappel suit le transfert : le nouveau lot est un enfant du lot recu.
        found, _ = selectors.downstream(origins=[source])
        assert child.id in {lot.id for lot in found}


def test_transfer_checks(client_a, two_sites):
    fresh = two_sites["fresh"]
    same = client_a.post(URL, {"lot": str(fresh.id), "to_site": str(two_sites["north"].id)}, format="json")
    assert same.status_code == 400 and "déjà" in same.json()["to_site"][0]
    too_much = client_a.post(URL, {"lot": str(fresh.id), "to_site": str(two_sites["south"].id), "quantity": "900"},
                             format="json")
    assert too_much.status_code == 400


def test_production_refuses_a_lot_from_another_site(client_a, two_sites, orchard, tenant_a, admin_a):
    from production import services as production

    with tenant_context(tenant_a.id):
        dryer = production.create_equipment(tenant_id=tenant_a.id, user=admin_a, code="SEC-SUD", name="Séchoir Sud",
                                            equipment_type="sechoir", site=two_sites["south"])
    data = {"step": "sechage", "equipment": str(dryer.id), "output_article": str(orchard["dried"].id),
            "output_quantity": "30", "inputs": [{"lot": str(two_sites["fresh"].id), "quantity": "500"}]}
    refused = client_a.post("/api/v1/production/runs/", data, format="json")
    assert refused.status_code == 400 and "transférez-le" in refused.json()["inputs"][0]
    client_a.post(URL, {"lot": str(two_sites["fresh"].id), "to_site": str(two_sites["south"].id)}, format="json")
    assert client_a.post("/api/v1/production/runs/", data, format="json").status_code == 201


def test_transfers_are_append_only_and_cannot_be_reversed(client_a, two_sites, tenant_a):
    body = client_a.post(URL, {"lot": str(two_sites["fresh"].id), "to_site": str(two_sites["south"].id),
                               "quantity": "100"}, format="json").json()
    with tenant_context(tenant_a.id):
        with pytest.raises(DatabaseError), transaction.atomic():
            LotTransfer.objects.update(quantity=Decimal("1"))
        movement = selectors.movements_of(lot=selectors.lot_or_404(lot_id=body["lot_id"])).first()
    response = client_a.post(f"/api/v1/movements/{movement.id}/reverse/", {"reason_code": "erreur_saisie"},
                             format="json")
    assert response.status_code == 400


def test_reader_cannot_transfer(tenant_a, two_sites):
    from rest_framework.test import APIClient

    reader = APIClient()
    reader.force_authenticate(make_user(tenant_a, "lec", role=User.Role.LECTURE))
    data = {"lot": str(two_sites["fresh"].id), "to_site": str(two_sites["south"].id)}
    assert reader.post(URL, data, format="json").status_code == 403
    assert reader.get(URL).status_code == 200


def test_isolation_other_company(client_b, two_sites, site_of_tenant_b, client_a):
    data = {"lot": str(two_sites["fresh"].id), "to_site": str(site_of_tenant_b.id)}
    assert client_b.post(URL, data, format="json").status_code == 404
    # Le site d'une autre entreprise est introuvable pour A.
    assert client_a.post(URL, data, format="json").status_code == 400
    client_a.post(URL, {"lot": str(two_sites["fresh"].id), "to_site": str(two_sites["south"].id)}, format="json")
    assert client_b.get(URL).json() == []
    assert client_b.get(f"{URL}options/").json()["lots"] == []
