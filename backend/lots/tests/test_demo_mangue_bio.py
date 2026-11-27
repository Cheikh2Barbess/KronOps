"""Commande demo_mangue_bio : entreprise de demo a part, parcours amont et aval, rien ne fuit ailleurs."""

import pytest
from django.core.management import CommandError, call_command

from conftest import PASSWORD
from core.tenancy import tenant_context
from lots.models import ApprovalRequest, Lot
from lots.tests.conftest import client_for
from tenants.models import User
from tenants.selectors import find_user_by_username


@pytest.fixture
def demo(db):
    call_command("demo_mangue_bio", password=PASSWORD)
    return find_user_by_username("demo.direction")


def test_creates_a_separate_company_with_four_accounts(demo, tenant_a):
    assert demo.role == User.Role.ADMIN and demo.tenant_id != tenant_a.id
    for username in ("demo.qualite", "demo.production", "demo.reception"):
        assert find_user_by_username(username).tenant_id == demo.tenant_id
    with tenant_context(tenant_a.id):
        assert not Lot.objects.exists()


def test_refuses_to_load_twice(demo):
    with pytest.raises(CommandError, match="déjà chargée"):
        call_command("demo_mangue_bio", password=PASSWORD)


def test_upstream_from_a_bag_reaches_three_parcels(demo):
    with tenant_context(demo.tenant_id):
        bag = Lot.objects.filter(article__code="MGS100").order_by("production_date").first()
    data = client_for(demo).get("/api/v1/traceability/upstream/", {"search": bag.code}).json()
    parcels = {lot["supplier_lot_code"] for lot in data["lots"] if lot["article_code"] == "MGAF"}
    assert parcels == {"NAP-07", "SIN-03", "KAR-12"}
    # Le lot refuse a reception n'est entre dans aucun sachet.
    assert "NIO-05" not in {lot["supplier_lot_code"] for lot in data["lots"]}


def test_parcel_recall_reaches_only_the_affected_customer(demo):
    data = client_for(demo).get("/api/v1/traceability/downstream/", {"search": "NAP-07"}).json()
    assert {s["customer_name"] for s in data["shipments"]} == {"Importateur bio Rotterdam (démo)"}


def test_history_has_a_destroyed_lot_and_a_blocked_lot_to_release(demo):
    with tenant_context(demo.tenant_id):
        assert Lot.objects.filter(status=Lot.Status.DETRUIT, supplier_lot_code="NIO-05").count() == 1
        assert ApprovalRequest.objects.filter(status=ApprovalRequest.Status.APPROVED).count() == 1
        blocked = Lot.objects.get(status=Lot.Status.BLOQUE)
        assert blocked.article.code == "ANAS"


def test_other_company_cannot_see_demo_lots(demo, client_a):
    assert client_a.get("/api/v1/traceability/downstream/", {"search": "NAP-07"}).status_code == 404
