"""Etapes de production activables par entreprise : catalogue complet (etapes COLEAD et coco), chaque client
active, desactive et ordonne ses etapes. Une etape desactivee disparait des ecrans et l'API la refuse."""

import pytest
from rest_framework.test import APIClient

from audit.models import AuditLog
from conftest import make_user
from core.tenancy import tenant_context
from events.models import OutboxEvent
from production.models import ProductionRun, StepSetting
from tenants.models import User

STEPS = "/api/v1/production/steps/"
OPTIONS = "/api/v1/production/runs/options/"
RUNS = "/api/v1/production/runs/"

DEFAULT_ACTIVE = ["murissement", "tri", "preparation", "sechage", "conditionnement", "palettisation"]


def codes(rows, active=None):
    return [r["code"] for r in rows if active is None or r["is_active"] == active]


def wash(client, orchard, lot, kg="100", step="lavage"):
    return client.post(RUNS, {
        "step": step, "output_article": str(orchard["dried"].id), "output_quantity": "90",
        "inputs": [{"lot": str(lot.id), "quantity": kg}],
    }, format="json")


def test_catalog_lists_every_step_and_keeps_the_six_historic_ones_active(client_a):
    rows = client_a.get(STEPS).json()
    assert sorted(codes(rows)) == sorted(ProductionRun.Step.values)
    for code in ["lavage", "epluchage_decoupe", "pretraitement", "refroidissement", "tri_finition",
                 "cassage", "parage", "rapage", "pasteurisation"]:
        assert code in codes(rows)
    assert codes(rows, active=True) == DEFAULT_ACTIVE
    assert all(r["label"] for r in rows)


def test_options_only_offer_active_steps(client_a):
    steps = [s["code"] for s in client_a.get(OPTIONS).json()["steps"]]
    assert steps == DEFAULT_ACTIVE


def test_admin_activates_reorders_and_deactivates(client_a, tenant_a):
    wanted = [
        {"code": "lavage", "is_active": True},
        {"code": "murissement", "is_active": True},
        {"code": "sechage", "is_active": True},
        {"code": "refroidissement", "is_active": True},
        {"code": "conditionnement", "is_active": True},
    ]
    response = client_a.put(STEPS, {"steps": wanted}, format="json")
    assert response.status_code == 200, response.json()
    rows = response.json()
    # Les etapes actives d'abord, dans l'ordre choisi. Les etapes non citees restent desactivees.
    assert codes(rows, active=True) == ["lavage", "murissement", "sechage", "refroidissement", "conditionnement"]
    assert "tri" in codes(rows, active=False)
    assert [s["code"] for s in client_a.get(OPTIONS).json()["steps"]] == codes(rows, active=True)
    with tenant_context(tenant_a.id):
        assert AuditLog.objects.filter(entity_type="production.stepsetting").exists()
        assert OutboxEvent.objects.filter(event_type="production.steps_configured").count() == 1


def test_deactivated_step_is_refused_and_activated_one_accepted(client_a, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "300")
    refused = wash(client_a, orchard, fresh)
    assert refused.status_code == 400
    assert "désactivée" in refused.json()["step"][0]

    client_a.put(STEPS, {"steps": [{"code": c, "is_active": True} for c in ["lavage", *DEFAULT_ACTIVE]]},
                 format="json")
    accepted = wash(client_a, orchard, fresh)
    assert accepted.status_code == 201, accepted.json()
    assert accepted.json()["step"] == "lavage"

    client_a.put(STEPS, {"steps": [{"code": c, "is_active": True} for c in DEFAULT_ACTIVE]}, format="json")
    assert wash(client_a, orchard, fresh).status_code == 400


def test_history_keeps_runs_of_a_deactivated_step(client_a, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "300")
    client_a.put(STEPS, {"steps": [{"code": c, "is_active": True} for c in ["lavage", *DEFAULT_ACTIVE]]},
                 format="json")
    run = wash(client_a, orchard, fresh).json()
    client_a.put(STEPS, {"steps": [{"code": c, "is_active": True} for c in DEFAULT_ACTIVE]}, format="json")
    assert client_a.get(f"{RUNS}{run['id']}/").json()["step"] == "lavage"
    # Le filtre du bilan matiere garde toutes les etapes : l'historique reste consultable.
    balance_steps = [s["code"] for s in client_a.get("/api/v1/production/balance/").json()["steps"]]
    assert "lavage" in balance_steps


@pytest.mark.parametrize("payload, field", [
    ({"steps": [{"code": "inconnue", "is_active": True}]}, "steps"),
    ({"steps": [{"code": "sechage", "is_active": True}, {"code": "sechage", "is_active": False}]}, "steps"),
    ({"steps": [{"code": "sechage", "is_active": False}]}, "steps"),
    ({"steps": []}, "steps"),
])
def test_invalid_configurations_are_refused(client_a, payload, field):
    response = client_a.put(STEPS, payload, format="json")
    assert response.status_code == 400
    assert field in response.json()


def test_only_admin_configures_other_roles_read(tenant_a):
    body = {"steps": [{"code": "sechage", "is_active": True}]}
    for role in [User.Role.QUALITE, User.Role.PRODUCTION, User.Role.OPERATEUR, User.Role.LECTURE]:
        client = APIClient()
        client.force_authenticate(make_user(tenant_a, f"u_{role}", role=role))
        assert client.put(STEPS, body, format="json").status_code == 403
        # Lecture : roles des referentiels. L'operateur voit les etapes actives dans l'ecran de declaration.
        assert client.get(STEPS).status_code == (403 if role == User.Role.OPERATEUR else 200)


def test_isolation_between_companies(client_a, client_b, tenant_a, tenant_b):
    client_a.put(STEPS, {"steps": [{"code": "lavage", "is_active": True}]}, format="json")
    assert codes(client_b.get(STEPS).json(), active=True) == DEFAULT_ACTIVE
    with tenant_context(tenant_b.id):
        assert StepSetting.objects.count() == 0
    with tenant_context(tenant_a.id):
        assert StepSetting.objects.filter(step="lavage", is_active=True).exists()
