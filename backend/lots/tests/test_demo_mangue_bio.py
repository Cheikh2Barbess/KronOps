"""Commande demo_mangue_bio : entreprise de demo a part, saison complete de fruits seches, rien ne fuit ailleurs.

La demo met environ 10 secondes a se construire : les verifications en lecture sont regroupees par theme pour ne
la construire que quelques fois.
"""

import datetime
from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditLog
from catalog.models import Partner
from conftest import PASSWORD, make_user
from core.tenancy import tenant_context
from lots.management.commands.demo_mangue_bio import _container
from lots.models import ApprovalRequest, Lot, LotTransfer, Movement
from lots.tests.conftest import client_for
from tenants.models import Tenant, User
from tenants.selectors import find_user_by_username

ROTTERDAM = _container("260600")
LYON = _container("260700")
HAMBOURG_COCO = _container("260900")


@pytest.fixture
def demo(db):
    call_command("demo_mangue_bio", password=PASSWORD)
    return find_user_by_username("demo.direction")


def _carton_of_dryer(demo, dryer):
    with tenant_context(demo.tenant_id):
        # Carton <- mangue triee (tri finition) <- mangue sechee (sechoir), lot du 9 juin.
        dried = "parent_links__parent_lot__parent_links__parent_lot__production_run__"
        return Lot.objects.get(**{"article__code": "MGAC", dried + "equipment__code": dryer,
                                  dried + "ended_at__date": datetime.date(2026, 6, 13)})


def test_creates_a_separate_company_and_refuses_to_load_twice(demo, tenant_a):
    assert demo.role == User.Role.ADMIN and demo.tenant_id != tenant_a.id
    for username in ("demo.qualite", "demo.production", "demo.reception"):
        assert find_user_by_username(username).tenant_id == demo.tenant_id
    with tenant_context(tenant_a.id):
        assert not Lot.objects.exists()
    with pytest.raises(CommandError, match="déjà chargée"):
        call_command("demo_mangue_bio", password=PASSWORD)


def test_traceability_story(demo, client_a):
    client = client_for(demo)
    # Rappel depuis un carton du sechoir 2 : trois parcelles bio, la palette partie a Rotterdam.
    carton = _carton_of_dryer(demo, "SEC-N2")
    data = client.get("/api/v1/traceability/recall/", {"search": carton.code}).json()
    fruit = [r for r in data["roots"] if r["article_type"] != "emballage"]
    assert {r["parcel_code"] for r in fruit} == {"NAP-07", "SIN-03", "KAR-12"}
    assert {r["organic_status"] for r in fruit} == {"bio"}
    assert data["summary"]["producers"] == 3
    assert "NIO-05" not in {r["parcel_code"] for r in data["affected"]}  # livraison refusee, jamais utilisee
    assert [(s["container_number"], s["customer_name"]) for s in data["shipments"]] == [
        (ROTTERDAM, "Importateur bio Rotterdam (démo)")
    ]
    assert {r["equipment_code"] for r in data["runs"] if r["step"] == "sechage"} == {"SEC-N1", "SEC-N2"}
    # Toutes les etapes du parcours mangue sont tracees.
    assert {"murissement", "lavage", "tri", "epluchage_decoupe", "pretraitement", "sechage", "tri_finition",
            "conditionnement", "palettisation"} <= {r["step"] for r in data["runs"]}

    data = client.get("/api/v1/traceability/recall/", {"search": ROTTERDAM}).json()
    assert data["container"] == ROTTERDAM and data["summary"]["parcels"] == 3

    # Coco : du conteneur a la parcelle, toutes les etapes propres a la coco.
    data = client.get("/api/v1/traceability/recall/", {"search": HAMBOURG_COCO}).json()
    assert {r["parcel_code"] for r in data["roots"] if r["article_type"] != "emballage"} == {"JAC-04"}
    assert [s["customer_name"] for s in data["shipments"]] == ["Biscuiterie bio Hambourg (démo)"]
    assert {"cassage", "parage", "rapage", "pasteurisation", "sechage", "refroidissement",
            "conditionnement"} <= {r["step"] for r in data["runs"]}

    # Lot partiellement expedie a Lyon : 12 cartons restent en stock, les cartons vides ne sont pas du produit.
    data = client.get("/api/v1/traceability/recall/", {"search": LYON}).json()
    assert [Decimal(r["balance"]) for r in data["in_stock"] if r["article_code"] == "MGAC"] == [Decimal("120")]
    assert all(r["article_type"] != "emballage" for r in data["in_stock"] + data["affected"])

    with tenant_context(demo.tenant_id):
        assert set(Lot.objects.values_list("site__name", flat=True)) == {"Usine Nord (démo)", "Usine Sud (démo)"}
        dried = Lot.objects.select_related("production_run").get(article__code="ANAS", block_code="autre")
        peeled = Lot.objects.select_related("production_run").get(pk=dried.parent_links.get().parent_lot_id)
        assert peeled.production_run.step == "epluchage_decoupe" and dried.production_run.step == "sechage"
    # Une autre entreprise ne voit rien de la demo.
    assert client_a.get("/api/v1/traceability/recall/", {"search": ROTTERDAM}).status_code == 404


def test_production_story_with_sourced_ratios(demo):
    client = client_for(demo)
    data = client.get("/api/v1/production/balance/", {"step": "sechage", "date_from": "2026-04-01",
                                                      "date_to": "2026-08-31"}).json()
    mango = [r for r in data["runs"] if r["output_article_code"] == "MGAS"]
    assert len(mango) == 17
    # Cycle de sechoir : environ 220 kg seches (COLEAD), deux ecarts signales (sechoir 2 et fin de saison).
    assert all(140 <= Decimal(r["output_quantity"]) <= 225 for r in mango)
    assert sorted(r["yield_status"] for r in mango).count("bas") == 2
    assert not any(r["late"] for r in data["runs"])  # horloge simulee : saisies au fil de la saison

    # 13 kg de mangue fraiche pour 1 kg sechee en debut de saison (COLEAD 2023, Amelie et Kent).
    balance = client.get("/api/v1/production/balance/", {"date_from": "2026-04-13", "date_to": "2026-04-19"}).json()
    totals = {t["step"]: t for t in balance["totals"]}
    ratio = Decimal(totals["murissement"]["input_quantity"]) / Decimal(totals["sechage"]["output_quantity"])
    assert 12 <= ratio <= 14

    steps = client.get("/api/v1/production/steps/").json()
    active = [r["code"] for r in steps if r["is_active"]]
    assert active[0] == "murissement" and active[-1] == "palettisation" and len(active) == 14
    assert "preparation" not in active

    from production.models import Equipment, RunCancellation
    from production.selectors import routes

    with tenant_context(demo.tenant_id):
        found = {r.name: [s["code"] for s in r.step_rows] for r in routes()}
        mango_lot = Lot.objects.filter(article__code="MGAS").first()
        bio = Lot.objects.filter(article__code="ANAF", parcel__code="BON-21").order_by("-created_at").first()
        conv = Lot.objects.filter(article__code="ANAF", parcel__code="ADI-02").order_by("-created_at").first()
        peeled = Lot.objects.filter(article__code="ANAP").first().article
        table = Equipment.objects.get(code="PRE-S1")
        cancelled = RunCancellation.objects.select_related("run__output_lot").get()
        assert cancelled.run.step == "murissement" and cancelled.run.output_lot.status == Lot.Status.BLOQUE
        transfer = LotTransfer.objects.select_related("to_site").get()
        assert transfer.to_site.name == "Usine Sud (démo)" and transfer.lot_id != transfer.source_lot_id
    assert set(found) == {"Mangue séchée", "Ananas séché", "Coco râpée séchée"}
    coco = found["Coco râpée séchée"]
    assert coco.index("cassage") < coco.index("parage") < coco.index("lavage")
    production = client_for(find_user_by_username("demo.production"))
    # Le rapage est une etape de la coco : refuse sur de la mangue.
    response = production.post("/api/v1/production/runs/", {
        "step": "rapage", "output_article": str(mango_lot.article_id), "output_quantity": "1",
        "inputs": [{"lot": str(mango_lot.id), "quantity": "1"}],
    }, format="json")
    assert response.status_code == 400 and "parcours" in str(response.json())
    # Melange bio et conversion refuse en direct.
    response = production.post("/api/v1/production/runs/", {
        "step": "epluchage_decoupe", "output_article": str(peeled.id), "output_quantity": "300",
        "equipment": str(table.id),
        "inputs": [{"lot": str(bio.id), "quantity": "300"}, {"lot": str(conv.id), "quantity": "300"}],
    }, format="json")
    assert response.status_code == 400 and "Mélange interdit" in response.json()["inputs"][0]

    ripening = client.get("/api/v1/production/balance/", {"date_from": "2026-06-09", "date_to": "2026-06-20"}).json()
    ripening = next(t for t in ripening["totals"] if t["step"] == "murissement")
    assert ripening["runs"] == 2 and ripening["deviations"] == 0


def test_quality_story_and_realistic_actions(demo):
    with tenant_context(demo.tenant_id):
        assert Lot.objects.filter(status=Lot.Status.DETRUIT, parcel__code="NIO-05").count() == 1
        coco = Lot.objects.get(status=Lot.Status.BLOQUE, block_code="controle_qualite_non_conforme")
        assert coco.article.code == "COCK"
        assert Lot.objects.get(status=Lot.Status.BLOQUE, block_code="autre").article.code == "ANAS"
        requests = {(r.action, r.status) for r in ApprovalRequest.objects.all()}
        assert requests == {("destroy", "approved"), ("release", "approved"), ("scrap", "approved"),
                            ("adjust", "rejected"), ("scrap", "pending")}
        # Saisie en double a la reception, annulee par un contre-mouvement.
        assert Movement.objects.filter(movement_type=Movement.Type.ANNULATION, reason_code="doublon").count() == 1
        # Horloge simulee : l'historique est saisi au fil de la saison, l'heure reelle est rendue.
        first = AuditLog.objects.order_by("created_at").first()
        assert first.created_at < timezone.now() - datetime.timedelta(days=200)
        late = Movement.objects.exclude(late_reason_code="").values_list("late_reason_code", flat=True)
        assert set(late) == {"tablette_indisponible", "oubli", "ressaisie_papier"}
        customer = Partner.objects.get(name="Biscuiterie bio Hambourg (démo)")
    assert abs(timezone.now() - datetime.datetime.now(datetime.UTC)) < datetime.timedelta(minutes=1)
    production = client_for(find_user_by_username("demo.production"))
    response = production.post("/api/v1/shipments/", {
        "customer": str(customer.id), "lines": [{"lot": str(coco.id), "quantity": "1", "unit": "carton"}],
        "container_number": "TRCU2611000",
    }, format="json")
    assert response.status_code == 400


def test_dashboards_tell_the_dried_fruit_story(demo):
    def tiles(username):
        data = client_for(find_user_by_username(username)).get("/api/v1/dashboard/").json()
        return {t["code"]: t for t in data["tiles"]}

    boss = tiles("demo.direction")
    assert not any(t["empty"] for t in boss.values())
    names = str(boss["produced"]["subtitle"])
    assert "Mangue" in names and "Ananas" in names and "Coco" in names
    assert boss["bottleneck"]["status"] == "warn" and "Épluchage" in boss["bottleneck"]["value_label"]
    assert boss["shipped"]["status"] == "warn"  # une expedition sans connaissement
    assert boss["blocked"]["value"] == 2 and boss["blocked"]["status"] == "warn"
    assert boss["approvals"]["value"] == 1 and boss["approvals"]["status"] == "warn"
    assert boss["yields"]["status"] == "ok" and boss["reception_conformity"]["status"] == "ok"
    assert boss["qc"]["status"] == "ok" and 95 <= boss["qc"]["value"] < 100  # deux non conformes sur la saison
    curves = [d for d in boss["yields"]["detail"] if d["kind"] == "line"]
    assert len(curves) == 3  # une courbe par produit seche
    mango = next(c["series"][0] for c in curves if c["series"][0]["name"].startswith("Mangue"))
    assert mango["band"] == {"min": 14.0, "max": 19.0}
    assert len([p for p in mango["points"] if p["y"] is not None]) >= 4
    # Actions : revision SEC-S2 en retard, lot de coco en cours de decision, cartons commandes pour l'arret en cours.
    assert boss["actions"]["value"] == 3 and boss["actions"]["status"] == "bad"
    alerts = client_for(demo).get("/api/v1/actions/alerts/").json()
    codes = {a["code"] for a in alerts}
    assert {"late_action", "blocked_lot", "target"} <= codes
    blocked = {a["title"]: a["open_action"] for a in alerts if a["code"] == "blocked_lot"}
    assert len(blocked) == 2  # comme la tuile : un lot bloque sans stock n'est pas une alerte
    assert sum(1 for v in blocked.values() if v is None) == 1  # l'ananas bloque reste a traiter en direct
    production = tiles("demo.production")
    assert production["late_entries"]["status"] == "ok" and production["late_entries"]["value"] < 3
    assert production["late_entries"]["threshold"]["is_default"] is False  # seuil propre a l'entreprise
    quality = tiles("demo.qualite")
    assert quality["ready_without_qc"]["value"] == 1
    operator = tiles("demo.reception")
    assert operator["wip"]["value"] >= 1 and operator["approvals"]["value"] == 1
    assert not operator["my_entries"]["empty"]


def test_reset_archives_the_old_demo_and_old_accounts_cannot_log_in(demo, tenant_a, admin_a):
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
        old_user = User.objects.get(pk=demo.pk)
    assert old_user.username.startswith("demo.direction.archive")
    assert not APIClient().login(username=old_user.username, password=PASSWORD)
    with tenant_context(fresh.tenant_id):
        assert Lot.objects.get(status=Lot.Status.BLOQUE, block_code="autre").article.code == "ANAS"
    # L'autre entreprise n'est pas touchee.
    tenant_a.refresh_from_db()
    assert tenant_a.is_active and tenant_a.name == "Entreprise A"
    with tenant_context(tenant_a.id):
        assert User.objects.get(pk=admin_a.pk).is_active


def test_reset_without_existing_demo_just_creates_it(db):
    call_command("demo_mangue_bio", password=PASSWORD, reset=True)
    assert find_user_by_username("demo.qualite") is not None


def test_reset_refuses_when_a_demo_username_belongs_to_a_real_client(tenant_a):
    make_user(tenant_a, "demo.qualite")
    with pytest.raises(CommandError, match="Remise à zéro refusée"):
        call_command("demo_mangue_bio", password=PASSWORD, reset=True)
    tenant_a.refresh_from_db()
    assert tenant_a.is_active and tenant_a.name == "Entreprise A"
