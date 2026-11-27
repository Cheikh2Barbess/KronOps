"""Commande demo_mangue_bio : entreprise de demo a part, parcours bio complet, rien ne fuit ailleurs."""

from decimal import Decimal

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


def _carton_of_dryer(demo, dryer):
    with tenant_context(demo.tenant_id):
        return Lot.objects.get(article__code="MGAC", parent_links__parent_lot__production_run__equipment__code=dryer)


def test_creates_a_separate_company_with_four_accounts(demo, tenant_a):
    assert demo.role == User.Role.ADMIN and demo.tenant_id != tenant_a.id
    for username in ("demo.qualite", "demo.production", "demo.reception"):
        assert find_user_by_username(username).tenant_id == demo.tenant_id
    with tenant_context(tenant_a.id):
        assert not Lot.objects.exists()


def test_refuses_to_load_twice(demo):
    with pytest.raises(CommandError, match="déjà chargée"):
        call_command("demo_mangue_bio", password=PASSWORD)


def test_recall_from_a_carton_reaches_three_bio_parcels_and_the_container(demo):
    carton = _carton_of_dryer(demo, "SEC-N2")
    data = client_for(demo).get("/api/v1/traceability/recall/", {"search": carton.code}).json()
    fruit = [r for r in data["roots"] if r["article_type"] != "emballage"]
    assert {r["parcel_code"] for r in fruit} == {"NAP-07", "SIN-03", "KAR-12"}
    assert {r["organic_status"] for r in fruit} == {"bio"}
    assert data["summary"]["producers"] == 3
    # Le lot refuse a reception n'est entre dans aucun carton.
    assert "NIO-05" not in {r["parcel_code"] for r in data["affected"]}
    assert [(s["container_number"], s["customer_name"]) for s in data["shipments"]] == [
        ("TRCU2606001", "Importateur bio Rotterdam (démo)")
    ]
    assert {r["equipment_code"] for r in data["runs"] if r["step"] == "sechage"} == {"SEC-N1", "SEC-N2"}


def test_recall_from_the_container(demo):
    data = client_for(demo).get("/api/v1/traceability/recall/", {"search": "TRCU2606001"}).json()
    assert data["container"] == "TRCU2606001"
    assert data["summary"]["parcels"] == 3


def test_drying_ratio_follows_public_reference_and_one_deviation_is_flagged(demo):
    data = client_for(demo).get("/api/v1/production/balance/", {"step": "sechage"}).json()
    mango = {r["equipment_code"]: r for r in data["runs"] if r["output_article_code"] == "MGAS"}
    assert mango["SEC-N1"]["yield_status"] == "conforme"
    # 13 kg de mangue pour 1 kg sechee (COLEAD 2023, Kent et Amelie).
    ratio = Decimal(mango["SEC-N1"]["input_quantity"]) / Decimal(mango["SEC-N1"]["output_quantity"])
    assert round(ratio) == 13
    assert mango["SEC-N2"]["yield_status"] == "bas"
    assert mango["SEC-N3"]["yield_status"] == "conforme"
    assert all(r["late"] for r in data["runs"])  # historique ressaisi apres coup


def test_mixing_bio_and_conversion_is_refused_live(demo):
    with tenant_context(demo.tenant_id):
        bio = Lot.objects.get(article__code="ANAF", parcel__code="BON-21")
        conv = Lot.objects.get(article__code="ANAF", parcel__code="ADI-02")
        dried = Lot.objects.filter(article__code="ANAS").first().article
        from production.models import Equipment
        dryer = Equipment.objects.get(code="SEC-S1")
    production = client_for(find_user_by_username("demo.production"))
    response = production.post("/api/v1/production/runs/", {
        "step": "sechage", "output_article": str(dried.id), "output_quantity": "60", "equipment": str(dryer.id),
        "inputs": [{"lot": str(bio.id), "quantity": "600"}, {"lot": str(conv.id), "quantity": "600"}],
    }, format="json")
    assert response.status_code == 400
    assert "Mélange interdit" in response.json()["inputs"][0]


def test_two_sites_and_cartons_still_in_stock(demo):
    with tenant_context(demo.tenant_id):
        assert set(Lot.objects.values_list("site__name", flat=True)) == {"Usine Nord (démo)", "Usine Sud (démo)"}
    data = client_for(demo).get("/api/v1/traceability/recall/", {"search": "TRCU2607002"}).json()
    assert [Decimal(r["balance"]) for r in data["in_stock"] if r["article_code"] == "MGAC"] == [Decimal("70")]
    # Les cartons vides (emballage) ne sont pas du produit a bloquer.
    assert all(r["article_type"] != "emballage" for r in data["in_stock"] + data["affected"])


def test_history_has_a_destroyed_lot_and_a_blocked_lot_to_release(demo):
    with tenant_context(demo.tenant_id):
        assert Lot.objects.filter(status=Lot.Status.DETRUIT, parcel__code="NIO-05").count() == 1
        assert ApprovalRequest.objects.filter(status=ApprovalRequest.Status.APPROVED).count() == 1
        blocked = Lot.objects.get(status=Lot.Status.BLOQUE)
        assert blocked.article.code == "ANAS"


def test_other_company_cannot_see_demo_lots(demo, client_a):
    assert client_a.get("/api/v1/traceability/recall/", {"search": "TRCU2606001"}).status_code == 404


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
