"""Commande demo_mangue_bio : entreprise de demo a part, parcours amont et aval, rien ne fuit ailleurs."""

import pytest
from django.core.management import CommandError, call_command

from rest_framework.test import APIClient

from audit.models import AuditLog
from conftest import PASSWORD, make_user
from core.tenancy import tenant_context
from lots.models import ApprovalRequest, Lot
from lots.tests.conftest import client_for
from tenants.models import Tenant, User
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


def test_reset_archives_the_old_demo_and_creates_a_fresh_one(demo, tenant_a, admin_a):
    old_tenant_id = demo.tenant_id
    with tenant_context(old_tenant_id):
        old_lots = Lot.objects.count()
    call_command("demo_mangue_bio", password=PASSWORD, reset=True)

    fresh = find_user_by_username("demo.direction")
    assert fresh.tenant_id != old_tenant_id and fresh.is_active
    old = Tenant.objects.get(pk=old_tenant_id)
    assert not old.is_active and "archivée" in old.name
    with tenant_context(old_tenant_id):
        # Rien n'est efface : les lots et le journal de l'ancienne demo restent, comptes desactives.
        assert Lot.objects.count() == old_lots
        assert not User.objects.filter(tenant_id=old_tenant_id, is_active=True).exists()
        assert AuditLog.objects.filter(entity_type="tenants.user", new_values__is_active=False).count() == 4
    with tenant_context(fresh.tenant_id):
        assert Lot.objects.get(status=Lot.Status.BLOQUE).article.code == "ANAS"
    # L'autre entreprise n'est pas touchee.
    tenant_a.refresh_from_db()
    assert tenant_a.is_active and tenant_a.name == "Entreprise A"
    with tenant_context(tenant_a.id):
        assert User.objects.get(pk=admin_a.pk).is_active


def test_archived_demo_accounts_cannot_log_in(demo):
    call_command("demo_mangue_bio", password=PASSWORD, reset=True)
    with tenant_context(demo.tenant_id):
        old = User.objects.get(pk=demo.pk)
    assert old.username.startswith("demo.direction.archive")
    client = APIClient()
    assert not client.login(username=old.username, password=PASSWORD)


def test_reset_without_existing_demo_just_creates_it(db):
    call_command("demo_mangue_bio", password=PASSWORD, reset=True)
    assert find_user_by_username("demo.qualite") is not None


def test_reset_refuses_when_a_demo_username_belongs_to_a_real_client(tenant_a):
    make_user(tenant_a, "demo.qualite")
    with pytest.raises(CommandError, match="Remise à zéro refusée"):
        call_command("demo_mangue_bio", password=PASSWORD, reset=True)
    tenant_a.refresh_from_db()
    assert tenant_a.is_active and tenant_a.name == "Entreprise A"
