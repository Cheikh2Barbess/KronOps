"""Ecran Pipeline en 8 blocs : chaque etape de l'etude, activable par entreprise selon sa nature.

Transformation : meme reglage que les etapes de production. Obligatoire : toujours actif. Module : activable,
desactive il est refuse par l'API. Prevu : affiche avec sa phase, jamais activable.
"""

import datetime
from decimal import Decimal

from rest_framework.test import APIClient

from audit.models import AuditLog
from conftest import make_user
from core.tenancy import tenant_context
from events.models import OutboxEvent
from lots import services as lots
from production.models import PipelineSetting, ProductionRun
from production.pipeline import CATALOG
from tenants.models import Site, User

PIPELINE = "/api/v1/production/pipeline/"
OPTIONS = "/api/v1/production/runs/options/"


def steps_of(body):
    return {s["code"]: s for block in body for s in block["steps"]}


def put(client, changes):
    return client.put(PIPELINE, {"steps": [{"code": c, "is_active": a} for c, a in changes]}, format="json")


def test_eight_blocks_with_every_production_step(client_a):
    body = client_a.get(PIPELINE).json()
    assert [b["number"] for b in body] == list(range(1, 9))
    assert all(b["label"] and b["steps"] for b in body)
    steps = steps_of(body)
    for code in ProductionRun.Step.values:
        assert steps[code]["kind"] == "transformation"
    assert steps["sechage"]["is_active"] is True and steps["lavage"]["is_active"] is False
    assert steps["reception"] == {**steps["reception"], "kind": "obligatoire", "is_active": True, "locked": True}
    assert steps["transfert"]["kind"] == "module" and steps["transfert"]["is_active"] is True
    assert steps["transfert"]["locked"] is False
    prevu = steps["analyses_labo"]
    assert prevu["kind"] == "prevu" and prevu["is_active"] is False and prevu["locked"] is True and prevu["phase"]
    assert len(steps) == len(CATALOG)


def test_activating_a_transformation_step_offers_it_in_production(client_a, tenant_a):
    response = put(client_a, [("lavage", True), ("tri", False)])
    assert response.status_code == 200, response.json()
    steps = steps_of(response.json())
    assert steps["lavage"]["is_active"] is True and steps["tri"]["is_active"] is False
    offered = [s["code"] for s in client_a.get(OPTIONS).json()["steps"]]
    assert "lavage" in offered and "tri" not in offered
    with tenant_context(tenant_a.id):
        assert OutboxEvent.objects.filter(event_type="production.pipeline_configured").count() == 1


def test_deactivated_transfer_module_is_refused(client_a, tenant_a, admin_a, orchard):
    with tenant_context(tenant_a.id):
        north = Site.objects.create(tenant=tenant_a, name="Nord")
        south = Site.objects.create(tenant=tenant_a, name="Sud")
        fresh = lots.receive_lot(
            tenant_id=tenant_a.id, user=admin_a, article=orchard["fresh"], supplier=orchard["producer"],
            supplier_lot_code="", quantity=Decimal("100"), unit="kg", date_type="ddm",
            expiry_date=datetime.date.today() + datetime.timedelta(days=10), parcel=orchard["p_bio"], site=north,
        )
    assert put(client_a, [("transfert", False)]).status_code == 200
    data = {"lot": str(fresh.id), "to_site": str(south.id)}
    refused = client_a.post("/api/v1/lots/transfers/", data, format="json")
    assert refused.status_code == 400
    assert "désactivé" in str(refused.json())
    with tenant_context(tenant_a.id):
        assert AuditLog.objects.filter(entity_type="production.pipelinesetting").exists()
    put(client_a, [("transfert", True)])
    assert client_a.post("/api/v1/lots/transfers/", data, format="json").status_code == 201


def test_deactivated_shipping_module_is_refused(client_a, orchard):
    put(client_a, [("expedition", False)])
    response = client_a.post("/api/v1/shipments/", {"customer": str(orchard["customer"].id), "lines": []},
                             format="json")
    assert response.status_code == 400
    assert "désactivé" in str(response.json())


def test_locked_unknown_and_empty_changes_are_refused(client_a):
    for changes in ([("reception", False)], [("analyses_labo", True)], [("inconnue", True)], [],
                    [("lavage", True), ("lavage", False)]):
        response = put(client_a, changes)
        assert response.status_code == 400, (changes, response.json())
        assert "steps" in response.json()


def test_cannot_deactivate_every_production_step(client_a):
    active = [c for c in ["murissement", "tri", "preparation", "sechage", "conditionnement", "palettisation"]]
    response = put(client_a, [(c, False) for c in active])
    assert response.status_code == 400


def test_only_admin_changes_every_role_reads(tenant_a):
    for role in [User.Role.QUALITE, User.Role.PRODUCTION, User.Role.OPERATEUR, User.Role.LECTURE]:
        client = APIClient()
        client.force_authenticate(make_user(tenant_a, f"p_{role}", role=role))
        assert put(client, [("transfert", False)]).status_code == 403
        # Lecture ouverte a tous : l'accueil masque les ecrans desactives.
        assert client.get(PIPELINE).status_code == 200


def test_isolation_between_companies(client_a, client_b, tenant_b):
    put(client_a, [("transfert", False), ("lavage", True)])
    steps = steps_of(client_b.get(PIPELINE).json())
    assert steps["transfert"]["is_active"] is True and steps["lavage"]["is_active"] is False
    with tenant_context(tenant_b.id):
        assert PipelineSetting.objects.count() == 0
