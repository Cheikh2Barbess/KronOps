"""Commande demo_mangue_bio : entreprise de demo a part, parcours bio complet, rien ne fuit ailleurs."""

from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from audit.models import AuditLog
from catalog.models import Partner
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
        ("TRCU2606003", "Importateur bio Rotterdam (démo)")
    ]
    assert {r["equipment_code"] for r in data["runs"] if r["step"] == "sechage"} == {"SEC-N1", "SEC-N2"}


def test_recall_from_the_container(demo):
    data = client_for(demo).get("/api/v1/traceability/recall/", {"search": "TRCU2606003"}).json()
    assert data["container"] == "TRCU2606003"
    assert data["summary"]["parcels"] == 3


def test_drying_ratio_follows_public_reference_and_one_deviation_is_flagged(demo):
    # Lots du 12 au 20 juin (l'historique de saison du tableau de bord est a d'autres dates).
    data = client_for(demo).get("/api/v1/production/balance/", {"step": "sechage", "date_from": "2026-06-12",
                                                                  "date_to": "2026-06-20"}).json()
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
        peeled = Lot.objects.filter(article__code="ANAP").first().article
        from production.models import Equipment
        table = Equipment.objects.get(code="PRE-S1")
    production = client_for(find_user_by_username("demo.production"))
    response = production.post("/api/v1/production/runs/", {
        "step": "epluchage_decoupe", "output_article": str(peeled.id), "output_quantity": "300",
        "equipment": str(table.id),
        "inputs": [{"lot": str(bio.id), "quantity": "300"}, {"lot": str(conv.id), "quantity": "300"}],
    }, format="json")
    assert response.status_code == 400
    assert "Mélange interdit" in response.json()["inputs"][0]


def test_steps_are_set_for_dried_fruit_and_one_step_is_switched_off(demo):
    data = client_for(demo).get("/api/v1/production/steps/").json()
    active = [r["code"] for r in data if r["is_active"]]
    assert active[0] == "murissement" and active[-1] == "palettisation" and len(active) == 14
    assert "preparation" not in active
    assert active.index("epluchage_decoupe") < active.index("sechage") < active.index("conditionnement")


def test_three_product_routes_and_a_step_outside_the_route_is_refused(demo):
    from production.selectors import routes

    with tenant_context(demo.tenant_id):
        found = {r.name: [s["code"] for s in r.step_rows] for r in routes()}
        mango = Lot.objects.filter(article__code="MGAS").first()
    assert set(found) == {"Mangue séchée", "Ananas séché", "Coco râpée séchée"}
    assert "rapage" in found["Coco râpée séchée"] and "rapage" not in found["Mangue séchée"]
    # Chaque parcours a son ordre : la coco est cassee et paree avant le lavage.
    coco = found["Coco râpée séchée"]
    assert coco.index("cassage") < coco.index("parage") < coco.index("lavage")
    mango_route = found["Mangue séchée"]
    assert mango_route.index("murissement") < mango_route.index("lavage")
    # Le rapage est une etape de la coco : refuse sur de la mangue.
    production = client_for(find_user_by_username("demo.production"))
    response = production.post("/api/v1/production/runs/", {
        "step": "rapage", "output_article": str(mango.article_id), "output_quantity": "1",
        "inputs": [{"lot": str(mango.id), "quantity": "1"}],
    }, format="json")
    assert response.status_code == 400
    assert "parcours" in str(response.json())


def test_coconut_flow_is_traced_from_the_container_to_the_parcel(demo):
    data = client_for(demo).get("/api/v1/traceability/recall/", {"search": "TRCU2609002"}).json()
    assert {r["parcel_code"] for r in data["roots"] if r["article_type"] != "emballage"} == {"JAC-04"}
    assert [s["customer_name"] for s in data["shipments"]] == ["Biscuiterie bio Hambourg (démo)"]
    steps = {r["step"] for r in data["runs"]}
    assert {"cassage", "parage", "rapage", "pasteurisation", "sechage", "refroidissement",
            "conditionnement"} <= steps


def test_pineapple_is_peeled_before_drying(demo):
    with tenant_context(demo.tenant_id):
        dried = Lot.objects.select_related("production_run").get(article__code="ANAS", block_code="autre")
        peeled = Lot.objects.select_related("production_run").get(pk=dried.parent_links.get().parent_lot_id)
        assert peeled.production_run.step == "epluchage_decoupe"
        assert dried.production_run.step == "sechage"
        assert dried.parent_links.get().parent_lot_id == peeled.id


def test_a_non_conforming_quality_check_blocks_a_coconut_lot(demo):
    with tenant_context(demo.tenant_id):
        blocked = Lot.objects.get(status=Lot.Status.BLOQUE, block_code="controle_qualite_non_conforme")
        assert blocked.article.code == "COCK"
        customer = Partner.objects.get(name="Biscuiterie bio Hambourg (démo)")
    production = client_for(find_user_by_username("demo.production"))
    response = production.post("/api/v1/shipments/", {
        "customer": str(customer.id), "lines": [{"lot": str(blocked.id), "quantity": "1", "unit": "carton"}],
        "container_number": "TRCU2611000",
    }, format="json")
    assert response.status_code == 400


def test_two_sites_and_cartons_still_in_stock(demo):
    with tenant_context(demo.tenant_id):
        assert set(Lot.objects.values_list("site__name", flat=True)) == {"Usine Nord (démo)", "Usine Sud (démo)"}
    data = client_for(demo).get("/api/v1/traceability/recall/", {"search": "TRCU2607000"}).json()
    assert [Decimal(r["balance"]) for r in data["in_stock"] if r["article_code"] == "MGAC"] == [Decimal("70")]
    # Les cartons vides (emballage) ne sont pas du produit a bloquer.
    assert all(r["article_type"] != "emballage" for r in data["in_stock"] + data["affected"])


def test_history_has_a_destroyed_lot_and_a_blocked_lot_to_release(demo):
    with tenant_context(demo.tenant_id):
        assert Lot.objects.filter(status=Lot.Status.DETRUIT, parcel__code="NIO-05").count() == 1
        assert ApprovalRequest.objects.filter(status=ApprovalRequest.Status.APPROVED).count() == 1
        blocked = Lot.objects.get(status=Lot.Status.BLOQUE, block_code="autre")
        assert blocked.article.code == "ANAS"


def test_other_company_cannot_see_demo_lots(demo, client_a):
    assert client_a.get("/api/v1/traceability/recall/", {"search": "TRCU2606003"}).status_code == 404


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
        assert Lot.objects.get(status=Lot.Status.BLOQUE, block_code="autre").article.code == "ANAS"
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


def test_demo_shows_a_cancelled_run_and_a_transfer(demo):
    from lots.models import LotTransfer
    from production.models import RunCancellation

    with tenant_context(demo.tenant_id):
        cancelled = RunCancellation.objects.select_related("run__output_lot").get()
        assert cancelled.run.step == "murissement" and cancelled.run.output_lot.status == Lot.Status.BLOQUE
        transfer = LotTransfer.objects.select_related("to_site").get()
        assert transfer.to_site.name == "Usine Sud (démo)" and transfer.lot_id != transfer.source_lot_id
    balance = client_for(demo).get("/api/v1/production/balance/", {"date_from": "2026-06-09",
                                                                    "date_to": "2026-06-20"}).json()
    ripening = next(t for t in balance["totals"] if t["step"] == "murissement")
    assert ripening["runs"] == 2 and ripening["deviations"] == 0


def test_dashboards_tell_the_dried_fruit_story(demo):
    """Historique de saison FICTIF : mangue, ananas et coco, avec un goulot au sechage et des alertes reelles."""
    def tiles(username):
        data = client_for(find_user_by_username(username)).get("/api/v1/dashboard/").json()
        return {t["code"]: t for t in data["tiles"]}

    boss = tiles("demo.direction")
    assert not any(t["empty"] for t in boss.values())
    names = str(boss["produced"]["subtitle"])
    assert "Mangue" in names and "Ananas" in names and "Coco" in names
    assert boss["bottleneck"]["status"] == "warn" and "Séchage" in boss["bottleneck"]["value_label"]
    assert boss["shipped"]["status"] == "warn"  # une expedition sans connaissement
    assert boss["blocked"]["value"] == 2
    curves = [d for d in boss["yields"]["detail"] if d["kind"] == "line"]
    assert len(curves) == 3  # une courbe par produit seche
    mango = next(c["series"][0] for c in curves if c["series"][0]["name"].startswith("Mangue"))
    assert mango["band"] == {"min": 5.5, "max": 7.7}
    assert len([p for p in mango["points"] if p["y"] is not None]) >= 4
    quality = tiles("demo.qualite")
    assert quality["ready_without_qc"]["value"] == 1 and quality["qc"]["status"] == "ok"
    operator = tiles("demo.reception")
    assert operator["wip"]["value"] >= 1
